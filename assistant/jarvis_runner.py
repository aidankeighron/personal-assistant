"""Runs Claude Code for Jarvis.

Flow
----
1. ``request_run(project, prompt)`` creates a run. If approval is required and there
   is no active lease, the run waits as ``awaiting_approval`` and your phone gets an
   ntfy push with Approve / Deny buttons.
2. Approving grants a lease (default 20 min). Runs requested during a lease start
   immediately.
3. ``start_run`` launches ``claude -p`` (in the sandbox container or locally) inside
   the project directory on a ``jarvis/draft-*`` branch and streams its JSON output
   into a log file.
4. ``refresh_status`` (scheduled every couple of minutes) turns the latest activity
   into a short spoken status line. That line is what Jarvis reads back to you.
5. When Claude finishes, a final report is written to ``<project>/.jarvis/`` and
   you get a push.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

RUN_RULES = (
    "You are working autonomously for Jarvis, the user's coding agent. Rules: work only on the current "
    "git branch ({branch}); commit your work with clear messages; never push to main/master; don't print or "
    "commit secrets; keep a short running log of what you did. When finished, end with a concise summary "
    "(what changed, how to test it, anything blocked)."
)


GIT_ENV = ["-e", "GIT_AUTHOR_NAME=Jarvis", "-e", "GIT_AUTHOR_EMAIL=jarvis@localhost",
           "-e", "GIT_COMMITTER_NAME=Jarvis", "-e", "GIT_COMMITTER_EMAIL=jarvis@localhost",
           "-e", "GIT_CONFIG_COUNT=1", "-e", "GIT_CONFIG_KEY_0=safe.directory", "-e", "GIT_CONFIG_VALUE_0=*"]


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")[:40] or "project"


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------
def list_projects(rt) -> list[dict]:
    return rt.db.query("SELECT name, path, description, status_text, updated FROM projects ORDER BY updated DESC")


def get_project(rt, name: str | None) -> dict | None:
    if not name:
        return None
    rows = list_projects(rt)
    s = slug(name)
    for r in rows:
        if r["name"] == s:
            return r
    for r in rows:  # fuzzy: substring either way
        if s in r["name"] or r["name"] in s:
            return r
    return None


def create_project(rt, name: str, description: str = "", git_url: str | None = None,
                   path: str | None = None) -> dict:
    s = slug(name)
    existing = get_project(rt, s)
    if existing and existing["name"] == s:
        return existing
    p = Path(path) if path else rt.settings.projects_dir / s
    if git_url and not p.exists():
        subprocess.run(["git", "clone", git_url, str(p)], check=True, capture_output=True, timeout=600)
    p.mkdir(parents=True, exist_ok=True)
    if not (p / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=p, check=False)
    (p / ".jarvis").mkdir(exist_ok=True)
    now = time.time()
    rt.db.execute(
        "INSERT OR REPLACE INTO projects(name, path, description, created, updated, status_text) VALUES (?,?,?,?,?,?)",
        (s, str(p), description, now, now, "New project, nothing run yet."))
    return get_project(rt, s)  # type: ignore[return-value]


def set_status(rt, project: str, text: str) -> None:
    rt.db.execute("UPDATE projects SET status_text=?, updated=? WHERE name=?", (text, time.time(), project))


# ---------------------------------------------------------------------------
# approvals / leases
# ---------------------------------------------------------------------------
def lease_active(rt) -> bool:
    return (rt.db.kv_get("jarvis:lease_until") or 0) > time.time()


def grant_lease(rt, minutes: float | None = None) -> float:
    minutes = minutes or float(rt.settings["jarvis"].get("lease_minutes", 20))
    until = time.time() + minutes * 60
    rt.db.kv_set("jarvis:lease_until", until)
    return until


def revoke_lease(rt) -> None:
    rt.db.kv_set("jarvis:lease_until", 0)


async def _ask_approval(rt, run_id: int, project: str, prompt: str) -> int:
    token = secrets.token_urlsafe(24)
    ttl = 6 * 3600
    aid = rt.db.execute(
        "INSERT INTO approvals(token, kind, payload, created, expires) VALUES (?,?,?,?,?)",
        (token, "jarvis_run", json.dumps({"run_id": run_id}), time.time(), time.time() + ttl))
    rt.db.execute("UPDATE runs SET approval_id=? WHERE id=?", (aid, run_id))
    base = rt.settings["server"]["public_url"].rstrip("/")
    await rt.notifier.send(
        "Jarvis wants to code",
        f"[{project}] {prompt[:180]}",
        priority=4,
        tags=["robot"],
        actions=[
            {"action": "http", "label": "Approve", "url": f"{base}/approvals/{token}/approve", "method": "POST",
             "clear": True},
            {"action": "http", "label": "Deny", "url": f"{base}/approvals/{token}/deny", "method": "POST",
             "clear": True},
        ],
    )
    return aid


async def decide(rt, token: str, approve: bool) -> dict:
    row = rt.db.one("SELECT * FROM approvals WHERE token=?", (token,))
    if not row:
        return {"error": "unknown approval"}
    if row["status"] != "pending":
        return {"status": row["status"]}
    if row["expires"] < time.time():
        rt.db.execute("UPDATE approvals SET status='expired' WHERE id=?", (row["id"],))
        return {"status": "expired"}
    status = "approved" if approve else "denied"
    rt.db.execute("UPDATE approvals SET status=?, decided=? WHERE id=?", (status, time.time(), row["id"]))
    payload = json.loads(row["payload"] or "{}")
    run_id = payload.get("run_id")
    if approve:
        grant_lease(rt)
        # start this run and anything else waiting
        waiting = rt.db.query("SELECT id FROM runs WHERE status='awaiting_approval' ORDER BY created")
        for w in waiting:
            await start_run(rt, w["id"])
    elif run_id:
        rt.db.execute("UPDATE runs SET status='denied', finished=? WHERE id=?", (time.time(), run_id))
    return {"status": status, "run_id": run_id}


# ---------------------------------------------------------------------------
# runs
# ---------------------------------------------------------------------------
async def request_run(rt, project_name: str, prompt: str) -> dict:
    proj = get_project(rt, project_name) or create_project(rt, project_name)
    active = rt.db.one("SELECT id FROM runs WHERE project=? AND status IN ('running','starting')", (proj["name"],))
    if active:
        return {"status": "busy", "project": proj["name"], "run_id": active["id"]}
    run_id = rt.db.execute(
        "INSERT INTO runs(project, prompt, created) VALUES (?,?,?)", (proj["name"], prompt, time.time()))
    rt.db.execute("UPDATE projects SET last_run_id=?, updated=? WHERE name=?", (run_id, time.time(), proj["name"]))
    rt.db.kv_set("jarvis:last_project", proj["name"])
    need = rt.settings["jarvis"].get("approval_required", True) and not lease_active(rt)
    if need:
        await _ask_approval(rt, run_id, proj["name"], prompt)
        set_status(rt, proj["name"], "Waiting for your approval on your phone before I start.")
        return {"status": "awaiting_approval", "project": proj["name"], "run_id": run_id}
    await start_run(rt, run_id)
    return {"status": "started", "project": proj["name"], "run_id": run_id}


def _git(path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=path, capture_output=True, text=True, timeout=60)


def build_command(rt, proj_path: Path, prompt: str, session_id: str | None, run_id: int) -> list[str]:
    jc = rt.settings["jarvis"]
    claude = ["claude", "-p", prompt, *jc.get("claude_args", [])]
    if session_id and jc.get("continue_sessions", True):
        claude += ["--resume", session_id]
    if jc.get("model"):
        claude += ["--model", jc["model"]]
    if jc.get("runner", "docker") != "docker":
        return claude
    claude_home = Path(jc.get("claude_home") or rt.settings.data_dir / "claude-home")
    claude_home.mkdir(parents=True, exist_ok=True)
    cmd = ["docker", "run", "--rm", "-i", "--name", f"jarvis-run-{run_id}",
           "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/home/agent", *GIT_ENV,
           "-v", f"{proj_path}:/work", "-v", f"{claude_home}:/home/agent", "-w", "/work",
           "--memory", jc.get("container_memory", "3g"), "--cpus", str(jc.get("container_cpus", 2))]
    for env in jc.get("pass_env", ["ANTHROPIC_API_KEY"]):
        cmd += ["-e", env]
    return cmd + [jc.get("docker_image", "pa-sandbox:latest"), *claude]


async def start_run(rt, run_id: int) -> dict:
    run = rt.db.one("SELECT * FROM runs WHERE id=?", (run_id,))
    if not run or run["status"] not in ("awaiting_approval", "queued"):
        return {"error": "run not startable", "status": run and run["status"]}
    proj = get_project(rt, run["project"])
    path = Path(proj["path"])
    branch = rt.settings["jarvis"].get("branch_prefix", "jarvis/draft-") + slug(run["project"])
    if (path / ".git").exists():
        cur = _git(path, "rev-parse", "--abbrev-ref", "HEAD").stdout.strip()
        if cur != branch:
            if _git(path, "rev-parse", "--verify", branch).returncode == 0:
                _git(path, "checkout", branch)
            else:
                _git(path, "checkout", "-b", branch)
    prev = rt.db.one(
        "SELECT session_id FROM runs WHERE project=? AND session_id IS NOT NULL AND id<>? ORDER BY id DESC LIMIT 1",
        (run["project"], run_id))
    prompt = RUN_RULES.format(branch=branch) + "\n\nTASK:\n" + run["prompt"]
    log_path = path / ".jarvis" / f"run-{run_id}.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    cmd = build_command(rt, path, prompt, prev["session_id"] if prev else None, run_id)
    rt.db.execute("UPDATE runs SET status='starting', started=?, log_path=? WHERE id=?",
                  (time.time(), str(log_path), run_id))
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=str(path), stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL)
    except FileNotFoundError as e:
        rt.db.execute("UPDATE runs SET status='failed', result=?, finished=? WHERE id=?",
                      (f"could not launch: {e}", time.time(), run_id))
        set_status(rt, run["project"], f"I couldn't start Claude Code: {e}.")
        return {"error": str(e)}
    rt.db.execute("UPDATE runs SET status='running', pid=? WHERE id=?", (proc.pid, run_id))
    set_status(rt, run["project"], "Started working on it.")
    task = asyncio.create_task(_pump(rt, run_id, proc, log_path))
    rt.state.setdefault("jarvis_tasks", {})[run_id] = (proc, task)
    return {"status": "running", "run_id": run_id}


def parse_stream_line(line: str) -> dict[str, Any]:
    """Extract what we care about from one Claude Code stream-json line."""
    try:
        ev = json.loads(line)
    except json.JSONDecodeError:
        return {"text": line.strip()} if line.strip() else {}
    out: dict[str, Any] = {}
    t = ev.get("type")
    if ev.get("session_id"):
        out["session_id"] = ev["session_id"]
    if t == "assistant":
        for block in (ev.get("message", {}) or {}).get("content", []) or []:
            if block.get("type") == "text" and block.get("text"):
                out.setdefault("texts", []).append(block["text"])
            elif block.get("type") == "tool_use":
                inp = block.get("input", {}) or {}
                detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") or ""
                out.setdefault("actions", []).append(f"{block.get('name')} {str(detail)[:120]}".strip())
    elif t == "result":
        out["result"] = ev.get("result") or ""
        out["is_error"] = bool(ev.get("is_error"))
        out["cost_usd"] = ev.get("total_cost_usd")
    return out


async def _pump(rt, run_id: int, proc: asyncio.subprocess.Process, log_path: Path) -> None:
    run = rt.db.one("SELECT project FROM runs WHERE id=?", (run_id,))
    project = run["project"]
    recent: list[str] = []
    result_text = ""
    is_error = False
    max_minutes = float(rt.settings["jarvis"].get("max_run_minutes", 90))
    deadline = time.time() + max_minutes * 60
    assert proc.stdout is not None
    with log_path.open("a", encoding="utf-8") as logf:
        while True:
            try:
                raw = await asyncio.wait_for(proc.stdout.readline(), timeout=max(1.0, deadline - time.time()))
            except asyncio.TimeoutError:
                proc.kill()
                result_text = f"Stopped: exceeded {max_minutes:.0f} minute limit."
                is_error = True
                break
            if not raw:
                break
            line = raw.decode(errors="replace")
            logf.write(line)
            logf.flush()
            info = parse_stream_line(line)
            if info.get("session_id"):
                rt.db.execute("UPDATE runs SET session_id=? WHERE id=? AND session_id IS NULL",
                              (info["session_id"], run_id))
            recent += [f"did: {a}" for a in info.get("actions", [])]
            recent += [f"said: {x[:400]}" for x in info.get("texts", [])]
            if "text" in info:
                recent.append(info["text"][:300])
            recent = recent[-40:]
            rt.state.setdefault("jarvis_recent", {})[run_id] = recent
            if "result" in info:
                result_text, is_error = info["result"], info["is_error"]
    code = await proc.wait()
    status = "failed" if (code != 0 or is_error) else "done"
    if not result_text:
        result_text = "\n".join(recent[-8:]) or f"exited with code {code}"
    rt.db.execute("UPDATE runs SET status=?, result=?, finished=? WHERE id=?",
                  (status, result_text, time.time(), run_id))
    rt.state.get("jarvis_tasks", {}).pop(run_id, None)
    await finalize(rt, run_id, project, status, result_text)


async def finalize(rt, run_id: int, project: str, status: str, result_text: str) -> None:
    spoken = await summarize(rt, project, [result_text], final=True, ok=(status == "done"))
    set_status(rt, project, spoken)
    proj = get_project(rt, project)
    if proj:
        rp = Path(proj["path"]) / ".jarvis" / f"report-{run_id}.md"
        rp.write_text(f"# Jarvis report — {project} (run {run_id}, {status})\n\n{spoken}\n\n## Claude's summary\n\n"
                      f"{result_text}\n", encoding="utf-8")
    await rt.notifier.send(f"Jarvis: {project} {status}", spoken[:300], tags=["robot"])


async def summarize(rt, project: str, items: list[str], final: bool = False, ok: bool = True) -> str:
    """Turn raw Claude activity into 1-3 sentences Jarvis can read aloud."""
    from .llm import LLMUnavailable
    what = "finished" if final else "is in progress"
    prompt = (
        f"You are Jarvis, a crisp British butler-style coding assistant. Project '{project}' {what}"
        f"{'' if ok else ' (with problems)'}. In 1-3 short spoken sentences (no markdown, no code), tell the user "
        "what has been done and what's next or blocked.\n\nACTIVITY:\n" + "\n".join(items)[-6000:]
    )
    try:
        msg = await rt.llm.chat(rt.settings.model("router"), [{"role": "user", "content": prompt}],
                                temperature=0.2, max_tokens=160)
        text = (msg.get("content") or "").strip()
        if text:
            return text
    except LLMUnavailable:
        pass
    # PC offline: fall back to something useful without an LLM
    last = next((i for i in reversed(items) if i.strip()), "")
    prefix = "Finished." if final and ok else ("Finished with problems." if final else "Still working.")
    return f"{prefix} Last update: {last[:240]}"


async def refresh_status(rt) -> int:
    """Scheduled: update spoken status for every running run."""
    n = 0
    for run in rt.db.query("SELECT id, project FROM runs WHERE status='running'"):
        recent = rt.state.get("jarvis_recent", {}).get(run["id"]) or []
        if not recent:
            continue
        key = f"jarvis:last_summarized:{run['id']}"
        if rt.state.get(key) == len(recent) and recent == rt.state.get(key + ":items"):
            continue
        rt.state[key] = len(recent)
        rt.state[key + ":items"] = list(recent)
        set_status(rt, run["project"], await summarize(rt, run["project"], recent))
        n += 1
    return n


async def cancel(rt, project: str) -> dict:
    run = rt.db.one("SELECT id, status FROM runs WHERE project=? AND status IN "
                    "('running','starting','awaiting_approval') ORDER BY id DESC LIMIT 1", (project,))
    if not run:
        return {"status": "nothing running"}
    entry = rt.state.get("jarvis_tasks", {}).get(run["id"])
    if entry:
        proc, _ = entry
        proc.kill()
        if rt.settings["jarvis"].get("runner", "docker") == "docker":
            subprocess.run(["docker", "kill", f"jarvis-run-{run['id']}"], capture_output=True)
    rt.db.execute("UPDATE runs SET status='cancelled', finished=? WHERE id=?", (time.time(), run["id"]))
    set_status(rt, project, "Cancelled at your request.")
    return {"status": "cancelled", "run_id": run["id"]}


def mark_orphans(rt) -> None:
    """On startup: runs that were 'running' when the server died can't be resumed by pid."""
    rt.db.execute("UPDATE runs SET status='interrupted', finished=? WHERE status IN ('running','starting')",
                  (time.time(),))

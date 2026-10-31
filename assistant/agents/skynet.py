"""Skynet: passive security, compliance and memory auditor. Mostly deterministic rules.

You don't talk to Skynet much; ask "Skynet, status" for the latest audit.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import time
from pathlib import Path

from .. import jarvis_runner as jr
from ..host import HostUnavailable
from ..memory import add_fact
from .base import EventCB, Agent, Reply

SECRET_PATTERNS = {
    "anthropic key": re.compile(r"sk-ant-[A-Za-z0-9_-]{20,}"),
    "openai key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "github token": re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    "aws key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "google key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
    "slack token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}
GPU_RE = re.compile(r"\b(?:rtx|gtx)\s?(\d{4})(\s?ti)?\b", re.I)
DAY = 86400


class Skynet(Agent):
    async def handle(self, rt, text: str, conversation: str, on_event: EventCB = None) -> Reply:
        if re.search(r"\b(run|audit|check|scan)\b", text.lower()):
            await audit(rt)
        rows = rt.db.query(
            "SELECT severity, message FROM findings WHERE resolved=0 AND ts>? ORDER BY ts DESC LIMIT 6",
            (time.time() - DAY,))
        last = rt.db.kv_get("skynet:last_audit")
        if not rows:
            return Reply(self.name, "All systems nominal. No open findings.", "All systems nominal.")
        crit = sum(r["severity"] == "critical" for r in rows)
        lines = "; ".join(r["message"] for r in rows)
        return Reply(self.name, f"{len(rows)} open findings ({crit} critical): {lines}",
                     f"{len(rows)} open findings, {crit} critical. {rows[0]['message']}", {"last_audit": last})


def _finding(rt, severity: str, check: str, message: str, out: list[dict]) -> None:
    out.append({"severity": severity, "check": check, "message": message})
    recent = rt.db.one("SELECT id FROM findings WHERE message=? AND ts>? AND resolved=0", (message, time.time() - DAY))
    if not recent:
        rt.db.execute("INSERT INTO findings(ts, severity, check_name, message) VALUES (?,?,?,?)",
                      (time.time(), severity, check, message))
        out[-1]["new"] = True


async def audit(rt) -> list[dict]:
    out: list[dict] = []
    now = time.time()
    s = rt.settings

    # 1. Claude lease hygiene
    until = rt.db.kv_get("jarvis:lease_until") or 0
    if 0 < until < now:
        jr.revoke_lease(rt)
    rt.db.execute("UPDATE approvals SET status='expired' WHERE status='pending' AND expires<?", (now,))

    # 2. Disk space on the vault
    du = shutil.disk_usage(s.data_dir)
    free_pct = du.free / du.total * 100
    if free_pct < 5:
        _finding(rt, "critical", "disk", f"Vault disk almost full ({free_pct:.1f}% free).", out)
    elif free_pct < 12:
        _finding(rt, "warn", "disk", f"Vault disk getting full ({free_pct:.1f}% free).", out)

    # 3. Backups
    if s["backup"].get("target"):
        last = rt.db.kv_get("backup:last") or 0
        if now - last > 2 * DAY:
            _finding(rt, "warn", "backup", "Memory backup hasn't succeeded in over 2 days.", out)

    # 4. Collector freshness
    for name in s["collectors"].get("enabled", []):
        last = rt.db.kv_get(f"collector:{name}:last_ok")
        err = rt.db.kv_get(f"collector:{name}:last_error")
        if err and (not last or err.get("ts", 0) > last):
            _finding(rt, "warn", "collector", f"Collector {name} failing: {err.get('error', '')[:120]}", out)

    # 5. Failed Jarvis runs / jobs in the last day
    for r in rt.db.query("SELECT id, project FROM runs WHERE status='failed' AND finished>?", (now - DAY,)):
        _finding(rt, "info", "jarvis", f"Jarvis run {r['id']} on {r['project']} failed.", out)
    for j in rt.db.query("SELECT id, kind, error FROM jobs WHERE status='failed' AND finished>?", (now - DAY,)):
        _finding(rt, "warn", "jobs", f"Job {j['kind']} #{j['id']} failed: {(j['error'] or '')[:100]}", out)

    # 6. Secret scan of Jarvis projects (tracked files only)
    for p in jr.list_projects(rt):
        for hit in scan_secrets(Path(p["path"])):
            _finding(rt, "critical", "secrets", f"Possible {hit['kind']} in {p['name']}/{hit['file']}", out)

    # 7. Memory audit: verify hardware ground truth, quarantine contradictions, promote repeats
    await memory_audit(rt, out)

    summary = {"ts": now, "findings": len(out), "new": sum(1 for f in out if f.get("new"))}
    rt.db.kv_set("skynet:last_audit", summary)
    new_bad = [f for f in out if f.get("new") and f["severity"] in ("warn", "critical")]
    if new_bad:
        await rt.notifier.send("Skynet", "; ".join(f["message"] for f in new_bad)[:400],
                               priority=5 if any(f["severity"] == "critical" for f in new_bad) else 3,
                               tags=["shield"])
    return out


def scan_secrets(path: Path, max_bytes: int = 300_000) -> list[dict]:
    if not (path / ".git").exists():
        return []
    try:
        files = subprocess.run(["git", "ls-files"], cwd=path, capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    hits = []
    for rel in files.splitlines():
        f = path / rel
        if rel.startswith(".jarvis/") or not f.is_file() or f.stat().st_size > max_bytes:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for kind, pat in SECRET_PATTERNS.items():
            if pat.search(text):
                hits.append({"file": rel, "kind": kind})
    return hits


async def memory_audit(rt, out: list[dict]) -> None:
    now = time.time()
    # Ground truth from the PC itself
    try:
        stats = await rt.host.stats()
        gpu = (stats.get("gpu") or {}).get("name")
        if gpu:
            add_fact(rt.db, f"The user's PC GPU is {gpu}", tier="verified", domain="hardware", source="nvidia-smi")
        if stats.get("ram_total_gb"):
            add_fact(rt.db, f"The user's PC has {round(stats['ram_total_gb'])} GB RAM", tier="verified",
                     domain="hardware", source="host-agent")
    except HostUnavailable:
        pass

    verified = rt.db.query("SELECT text FROM facts WHERE tier='verified' AND domain='hardware'")
    true_gpus = {m.group(1) + ("ti" if m.group(2) else "")
                 for v in verified for m in GPU_RE.finditer(v["text"])}
    for f in rt.db.query("SELECT id, text, mentions FROM facts WHERE tier IN ('candidate','explicit')"):
        mentioned = {m.group(1) + ("ti" if m.group(2) else "") for m in GPU_RE.finditer(f["text"])}
        if true_gpus and mentioned and not (mentioned & true_gpus):
            rt.db.execute("UPDATE facts SET tier='quarantined', reason=?, updated=? WHERE id=?",
                          (f"contradicts verified GPU {sorted(true_gpus)}", now, f["id"]))
            _finding(rt, "info", "memory", f"Quarantined fact contradicting hardware: {f['text']}", out)

    # promote repeated candidates, quarantine stale one-offs
    rt.db.execute("UPDATE facts SET tier='explicit', reason='repeated 3+ times', updated=? "
                  "WHERE tier='candidate' AND mentions>=3", (now,))
    rt.db.execute("UPDATE facts SET tier='quarantined', reason='single mention, stale', updated=? "
                  "WHERE tier='candidate' AND mentions<2 AND created<?", (now, now - 30 * DAY))


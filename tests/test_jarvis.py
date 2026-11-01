"""Jarvis end-to-end with a fake `claude` binary that emits stream-json."""

from __future__ import annotations

import asyncio
import json
import sys
import textwrap

from assistant import jarvis_runner as jr
from assistant.agents.jarvis import keyword_intent
from assistant.orchestrator import Orchestrator

FAKE_CLAUDE = textwrap.dedent('''
    import json, sys, time
    def out(o): print(json.dumps(o), flush=True)
    out({"type": "system", "subtype": "init", "session_id": "sess-123"})
    out({"type": "assistant", "message": {"content": [{"type": "text", "text": "Creating the app skeleton"}]}})
    out({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "app.py"}}]}})
    open("app.py", "w").write("print('hi')\\n")
    out({"type": "result", "subtype": "success", "is_error": False, "result": "Built app.py. Run python app.py.",
         "session_id": "sess-123", "total_cost_usd": 0.01})
''')


def use_fake_claude(rt, tmp_path, monkeypatch):
    script = tmp_path / "fake_claude.py"
    script.write_text(FAKE_CLAUDE)
    monkeypatch.setattr(jr, "build_command", lambda rt, p, prompt, sid, rid: [sys.executable, str(script)])


async def wait_done(rt, run_id, timeout=10):
    for _ in range(int(timeout * 20)):
        r = rt.db.one("SELECT status FROM runs WHERE id=?", (run_id,))
        if r["status"] in ("done", "failed"):
            return r["status"]
        await asyncio.sleep(0.05)
    raise AssertionError("run did not finish")


def test_keyword_intents():
    assert keyword_intent("list all the projects") == "list_projects"
    assert keyword_intent("status update on the project") == "status"
    assert keyword_intent("what's going on with everything, all projects status") in ("status_all", "list_projects")
    assert keyword_intent("build me a new budgeting app") == "new_project"
    assert keyword_intent("cancel that") == "cancel"


async def test_parse_stream_line():
    info = jr.parse_stream_line(json.dumps({"type": "result", "result": "done", "is_error": False, "session_id": "s"}))
    assert info["result"] == "done" and info["session_id"] == "s"
    info = jr.parse_stream_line(json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Bash", "input": {"command": "pytest -q"}}]}}))
    assert info["actions"] == ["Bash pytest -q"]


async def test_jarvis_full_flow_with_approval(rt, tmp_path, monkeypatch):
    use_fake_claude(rt, tmp_path, monkeypatch)
    orch = Orchestrator(rt)

    # "Hey Jarvis, build me ..." -> classifier says new_project
    rt.llm.script({"content": json.dumps({"intent": "new_project", "project": "budget app",
                                          "task": "build a budgeting CLI"})})
    res = await orch.handle("Hey Jarvis, build me a budgeting CLI", "j")
    assert res["agent"] == "jarvis"
    assert "approve" in res["text"].lower()
    run = rt.db.one("SELECT id, status, approval_id FROM runs")
    assert run["status"] == "awaiting_approval"
    # phone got a push with Approve/Deny buttons
    push = rt.notifier.sent[-1]
    assert [a["label"] for a in push["actions"]] == ["Approve", "Deny"]

    # tap Approve
    token = rt.db.one("SELECT token FROM approvals WHERE id=?", (run["approval_id"],))["token"]
    assert (await jr.decide(rt, token, True))["status"] == "approved"
    assert await wait_done(rt, run["id"]) == "done"
    assert rt.db.one("SELECT session_id FROM runs")["session_id"] == "sess-123"
    proj = jr.get_project(rt, "budget-app")
    assert (tmp_path / "projects" / "budget-app" / "app.py").exists()
    assert list((tmp_path / "projects" / "budget-app" / ".jarvis").glob("report-*.md"))
    assert proj["status_text"]  # summarized by (fake) LLM

    # "status update on that project" -> uses last project, reads the status line back
    rt.llm.script({"content": json.dumps({"intent": "status", "project": None})})
    res = await orch.handle("jarvis, status update on that project", "j")
    assert res["text"].startswith("budget app:")

    # lease is active now, so the next task starts without asking again
    rt.llm.script({"content": json.dumps({"intent": "build", "project": "budget-app", "task": "add tests"})})
    res = await orch.handle("jarvis add tests to budget app", "j")
    assert "begun" in res["text"]
    run2 = rt.db.one("SELECT id FROM runs ORDER BY id DESC LIMIT 1")
    await wait_done(rt, run2["id"])


async def test_jarvis_works_without_llm(rt):
    from assistant.llm import LLMUnavailable

    async def boom(*a, **k):
        raise LLMUnavailable("pc asleep")
    rt.llm.chat = boom
    rt.llm.chat_json = boom
    jr.create_project(rt, "half-full")
    res = await Orchestrator(rt).handle("Jarvis, list all the projects", "j2")
    assert "half full" in res["text"]


def test_parse_real_claude_stream_shapes():
    """Event shapes captured from a real `claude -p --output-format stream-json --verbose` run."""
    lines = [
        {"type": "active_goal", "value": None, "uuid": "u1", "session_id": "S"},
        {"type": "system", "subtype": "init", "cwd": "/work", "session_id": "S", "tools": ["Bash"]},
        {"type": "system", "subtype": "status", "session_id": "S"},
        {"type": "stream_event", "event": {"type": "content_block_delta"}, "session_id": "S"},
        {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}, "session_id": "S"},
        {"type": "rate_limit_event", "session_id": "S"},
        {"type": "system", "subtype": "post_turn_summary", "session_id": "S"},
        {"type": "result", "subtype": "success", "is_error": False, "result": "ok",
         "session_id": "S", "total_cost_usd": 0.0074},
    ]
    parsed = [jr.parse_stream_line(json.dumps(x)) for x in lines]
    assert all(p["session_id"] == "S" for p in parsed)
    assert parsed[4]["texts"] == ["ok"]
    assert not any("texts" in p or "actions" in p for i, p in enumerate(parsed) if i != 4)
    assert parsed[-1] == {"session_id": "S", "result": "ok", "is_error": False, "cost_usd": 0.0074}


def test_docker_command_shape(rt):
    rt.settings.raw["jarvis"]["runner"] = "docker"
    cmd = jr.build_command(rt, rt.settings.projects_dir / "x", "do it", "sess-1", 5)
    assert cmd[:5] == ["docker", "run", "--rm", "-i", "--init"]
    assert "--user" in cmd and "HOME=/home/agent" in cmd and "GIT_CONFIG_VALUE_0=*" in cmd
    assert f"type=bind,source={rt.settings.projects_dir / 'x'},target=/work" in cmd
    i = cmd.index("pa-sandbox:latest")
    assert cmd[i + 1:i + 3] == ["claude", "-p"] and "do it" not in cmd   # prompt goes on stdin
    assert cmd[-2:] == ["--resume", "sess-1"]


async def test_draft_branch_exclude_and_refuses_dirty_switch(rt, tmp_path, monkeypatch):
    import subprocess
    use_fake_claude(rt, tmp_path, monkeypatch)
    rt.settings.raw["jarvis"]["approval_required"] = False
    p = jr.create_project(rt, "fresh")
    res = await jr.request_run(rt, "fresh", "build it")
    await wait_done(rt, res["run_id"])
    path = tmp_path / "projects" / "fresh"
    git = lambda *a: subprocess.run(["git", *a], cwd=path, capture_output=True, text=True)  # noqa: E731
    assert git("symbolic-ref", "--short", "HEAD").stdout.strip() == "jarvis/draft-fresh"   # even with no commits
    assert ".jarvis/" in (path / ".git" / "info" / "exclude").read_text()
    assert ".jarvis" not in git("status", "--porcelain").stdout                              # logs never committed

    # user is on main with a change that conflicts with the draft branch -> Jarvis refuses to start
    env = ["-c", "user.name=t", "-c", "user.email=t@t"]
    git(*env, "add", "-A"); git(*env, "commit", "-qm", "draft")
    git("checkout", "-q", "-b", "main"); (path / "app.py").write_text("print('main')\n")
    git(*env, "commit", "-qam", "main change"); (path / "app.py").write_text("print('dirty')\n")
    res = await jr.request_run(rt, "fresh", "more")
    run = rt.db.one("SELECT status, result FROM runs WHERE id=?", (res["run_id"],))
    assert run["status"] == "failed" and "couldn't switch" in run["result"]
    assert git("symbolic-ref", "--short", "HEAD").stdout.strip() == "main"
    assert "stash" in jr.get_project(rt, "fresh")["status_text"]
    _ = p

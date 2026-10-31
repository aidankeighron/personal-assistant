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

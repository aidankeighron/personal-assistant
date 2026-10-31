from __future__ import annotations

import time
from datetime import datetime

import pytest

from assistant.agents.rocky import eridian, filler_for
from assistant.agents.skynet import audit, scan_secrets
from assistant.host import heavy_gpu_allowed, in_window
from assistant.memory import add_fact, extract_explicit, relevant_facts
from assistant.orchestrator import Orchestrator
from assistant.router import choose_agent, parse_address
from assistant.scheduler import next_run, parse_every


# -- routing ----------------------------------------------------------------
@pytest.mark.parametrize("text,agent,rest", [
    ("Hey Jarvis, status update on the project", "jarvis", "status update on the project"),
    ("jarvis list all the projects", "jarvis", "list all the projects"),
    ("Okay Mother: what's the distribution of my screen time?", "mother", "what's the distribution of my screen time?"),
    ("hey rockie what's the weather", "rocky", "what's the weather"),
    ("Skynet, status", "skynet", "status"),
    ("what's the weather", None, "what's the weather"),
])
def test_parse_address(text, agent, rest):
    assert parse_address(text) == (agent, rest)


def test_sticky_agent():
    avail = {"rocky", "jarvis", "mother", "skynet"}
    now = time.time()
    assert choose_agent("and the other one?", "jarvis", now - 30, avail, now)[0] == "jarvis"
    assert choose_agent("and the other one?", "jarvis", now - 3600, avail, now)[0] == "rocky"


# -- memory -----------------------------------------------------------------
def test_explicit_memory_and_domain_filter(rt):
    assert extract_explicit("Remember that I keep my bike in the garage") == "I keep my bike in the garage"
    assert extract_explicit("From now on, never max out my GPU during the day") == "never max out my GPU during the day"
    add_fact(rt.db, "User drives a 2003 Corvette", tier="explicit", domain="media")
    add_fact(rt.db, "User prefers low-overhead Python", tier="explicit", domain="coding")
    facts = relevant_facts(rt.db, "write me a python script")
    assert any("Python" in f for f in facts)
    assert not any("Corvette" in f for f in facts)  # anti-shoehorn


async def test_skynet_quarantines_wrong_gpu(rt):
    add_fact(rt.db, "User has an RTX 3080", tier="candidate", domain="hardware")
    await audit(rt)
    row = rt.db.one("SELECT tier FROM facts WHERE text LIKE '%3080%'")
    assert row["tier"] == "quarantined"
    assert rt.db.one("SELECT tier FROM facts WHERE text LIKE '%3070 Ti%'")["tier"] == "verified"


def test_secret_scan(tmp_path):
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=tmp_path)
    (tmp_path / "config.py").write_text('KEY = "sk-ant-' + "a" * 40 + '"\n')
    subprocess.run(["git", "add", "."], cwd=tmp_path)
    hits = scan_secrets(tmp_path)
    assert hits and hits[0]["kind"] == "anthropic key"


# -- rocky ------------------------------------------------------------------
def test_eridian_and_filler():
    assert eridian("I have to check. Want to play?") == "I must check. Want to play, question?"
    assert filler_for("what's the weather outside") is not None
    assert filler_for("tell me a joke") is None


async def test_rocky_tool_loop_sets_timer(rt):
    rt.llm.script(
        {"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "set_reminder", "arguments": {"text": "pasta", "minutes": 10, "kind": "timer"}}}]},
        {"role": "assistant", "content": "Timer set for pasta. Ten minutes!"},
    )
    events = []

    async def on_event(e):
        events.append(e)

    orch = Orchestrator(rt)
    res = await orch.handle("hey rocky set a timer for pasta for 10 minutes", "t1", on_event=on_event)
    assert res["agent"] == "rocky"
    assert "pasta" in res["text"].lower()
    assert rt.db.one("SELECT kind, text FROM reminders") == {"kind": "timer", "text": "pasta"}
    assert any(e["type"] == "tool" for e in events)


async def test_rocky_disallowed_tool_is_refused(rt):
    rt.llm.script(
        {"role": "assistant", "content": "", "tool_calls": [{"function": {"name": "query_data", "arguments": {"sql": "select 1"}}}]},
        {"role": "assistant", "content": "done"},
    )
    await Orchestrator(rt).handle("rocky run sql", "t2")
    tool_msg = [m for m in rt.llm.calls[-1]["messages"] if m.get("role") == "tool"][0]
    assert "not allowed" in tool_msg["content"]


async def test_offline_pc_gives_friendly_reply(rt):
    from assistant.llm import LLMUnavailable

    async def boom(*a, **k):
        raise LLMUnavailable("down")
    rt.llm.chat = boom
    res = await Orchestrator(rt).handle("rocky hi", "t3")
    assert "offline" in res["text"].lower()


async def test_remember_is_captured_without_llm(rt):
    await Orchestrator(rt).handle("Rocky, remember that my gym is Planet Fitness", "t4")
    assert rt.db.one("SELECT tier FROM facts WHERE text LIKE '%Planet Fitness%'")["tier"] == "explicit"


# -- scheduling / gpu gate --------------------------------------------------
def test_schedule_math():
    now = datetime(2026, 11, 2, 4, 0)  # Monday
    assert next_run({"daily": "05:00"}, now) == datetime(2026, 11, 2, 5, 0)
    assert next_run({"daily": "03:00"}, now) == datetime(2026, 11, 3, 3, 0)
    assert next_run({"weekly": "sun 03:00"}, now) == datetime(2026, 11, 8, 3, 0)
    assert parse_every("30m") == 1800


def test_window():
    assert in_window("04:30-06:30", datetime(2026, 1, 1, 5, 0))
    assert not in_window("04:30-06:30", datetime(2026, 1, 1, 12, 0))
    assert in_window("23:00-02:00", datetime(2026, 1, 1, 1, 0))


async def test_gpu_gate(rt):
    gate = rt.settings["gpu_gate"]
    noon = datetime(2026, 1, 1, 12, 0)
    ok, _ = await heavy_gpu_allowed(rt.host, gate, noon)
    assert not ok
    rt.host.idle_info = {"idle_seconds": 900, "fullscreen": False}
    assert (await heavy_gpu_allowed(rt.host, gate, noon))[0]
    rt.host.idle_info = {"idle_seconds": 900, "fullscreen": True, "foreground": "Assetto Corsa"}
    assert not (await heavy_gpu_allowed(rt.host, gate, noon))[0]

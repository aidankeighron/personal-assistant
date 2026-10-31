from __future__ import annotations

import json
import time

import pytest
from fastapi.testclient import TestClient

from assistant import reports, tasks
from assistant.api import create_app
from assistant.collectors import run_collectors
from assistant.tools import ToolContext
from assistant.tools.data import query_data
from assistant.tools.groceries import add_groceries, expiring_soon, shelf_days


def test_readonly_sql(rt):
    rt.db.add_event("test", "x", time.time(), "hello", "world")
    assert query_data(ToolContext(rt, "mother", "c"), "SELECT count(*) AS n FROM events")["rows"][0]["n"] == 1
    for bad in ("DELETE FROM events", "SELECT 1; DROP TABLE events", "UPDATE events SET title='x'"):
        with pytest.raises(ValueError):
            rt.db.readonly_query(bad)


async def test_report_is_editable_and_generates(rt):
    names = [r["name"] for r in reports.list_reports(rt)]
    assert "daily" in names and "weekly" in names
    reports.update_spec(rt, "daily", instruction="Always include total screen time",
                        add_section={"title": "Places", "prompt": "where I went", "sources": ["location"]})
    spec = reports.load_spec(rt, "daily")
    assert "Always include total screen time" in spec["instructions"]
    assert spec["sections"][-1]["title"] == "Places"
    assert list((rt.settings.data_dir / "reports" / "history").glob("daily.*.yaml"))  # old version kept

    rt.db.add_event("gcal", "calendar_event", time.time(), "Dentist", "")
    out = await reports.generate(rt, "daily")
    assert "## Schedule" in out["markdown"]
    # standing instruction was passed to the model
    assert any("Always include total screen time" in c["messages"][0]["content"] for c in rt.llm.calls)


async def test_inbox_and_notes_collectors(rt):
    d = rt.settings.inbox_dir / "finance"
    d.mkdir(parents=True)
    (d / "jan.csv").write_text("Date,Description,Amount\n2026-01-03,Kroger,54.20\n2026-01-04,Shell,40.00\n")
    notes = rt.settings.data_dir / "notes"
    notes.mkdir(parents=True)
    (notes / "2026-01-04.md").write_text("- idea: projector weather widget\n")
    res = await run_collectors(rt, ["inbox", "notes"])
    assert res == {"inbox": 2, "notes": 1}
    assert rt.db.one("SELECT COUNT(*) AS n FROM events WHERE source='finance'")["n"] == 2
    assert rt.db.search_events('"projector"')[0]["source"] == "notes"
    assert not list(d.iterdir())  # moved to _done


async def test_store_visit_asks_and_tracks_fridge(rt):
    res = await tasks.handle_location(rt, {"_type": "transition", "event": "leave", "desc": "Kroger"})
    assert res["asked"]
    assert "What did you buy" in rt.notifier.sent[-1]["message"]
    assert rt.db.kv_get("pending_grocery_question")["place"] == "Kroger"
    add_groceries(ToolContext(rt, "rocky", "c"), ["milk", "chicken breast", "rice"])
    assert rt.db.kv_get("pending_grocery_question") is None
    soon = [r["item"] for r in expiring_soon(rt.db, 3)]
    assert "chicken breast" in soon and "rice" not in soon
    assert shelf_days("rice") is None


async def test_due_reminder_fires(rt):
    rt.db.execute("INSERT INTO reminders(text, due, kind, created) VALUES ('pasta', ?, 'timer', ?)",
                  (time.time() - 1, time.time()))
    assert await tasks.fire_due_reminders(rt) == 1
    assert rt.notifier.sent[-1]["message"] == "pasta"
    assert ("speak", "Timer done: pasta") in rt.host.calls


async def test_brief_and_backup(rt, monkeypatch):
    rt.db.add_event("gcal", "calendar_event", time.time() + 60, "Standup", "")
    rt.llm.script({"content": "Morning! Standup soon."})
    import assistant.tools.general as g

    async def fake_weather(ctx, city=""):
        return {"temp_f": 48, "condition": "clear"}
    monkeypatch.setattr(g, "get_weather", fake_weather)
    brief = await tasks.build_brief(rt)
    assert brief["spoken"] and rt.db.kv_get("brief")["calendar"]
    path = tasks.backup(rt)
    assert path.endswith(".db")


def test_api(rt):
    app = create_app(rt, start_scheduler=False)
    with TestClient(app) as c:
        assert c.get("/health").json()["ok"]
        assert c.post("/chat", json={"text": "hi"}).status_code == 401
        h = {"Authorization": "Bearer test-token"}
        r = c.post("/chat", json={"text": "rocky hello", "conversation": "api"}, headers=h)
        assert r.status_code == 200 and r.json()["agent"] == "rocky"
        # streaming
        r = c.post("/chat", json={"text": "rocky what's the weather", "stream": True}, headers=h)
        types = [json.loads(line)["type"] for line in r.text.splitlines() if line]
        assert types[0] == "routed" and "filler" in types and types[-1] == "reply"
        # ingest + location (OwnTracks style auth via ?token=)
        assert c.post("/ingest/phone_usage?token=test-token", json=[{"app": "TikTok", "minutes": 34}]).json() == {"ingested": 1}
        assert c.post("/location?token=test-token", json={"_type": "location", "lat": 42.7, "lon": -84.5, "tst": 1}).status_code == 200
        assert c.get("/app").status_code == 200
        assert "agents" in c.get("/status", headers=h).json()
        # unknown approval token is harmless
        assert c.post("/approvals/nope/approve").json() == {"error": "unknown approval"}

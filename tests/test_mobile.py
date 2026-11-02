"""The Android app's sync endpoint (contract mirrored in mobile/.../sync/Payload.kt)."""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from assistant import mobile, reports
from assistant.api import create_app

NOW = int(time.time() * 1000)


def payload(n=1):
    return {
        "device": "Pixel 8",
        "app_sessions": [{"package": "com.discord", "label": "Discord", "start": NOW - 600_000, "end": NOW - 300_000}],
        "web_visits": [{"url": "github.com/aidankeighron", "domain": "github.com", "browser": "com.android.chrome",
                        "start": NOW - 200_000, "end": NOW - 80_000}],
        "locations": [{"ts": NOW - i * 300_000, "lat": 42.73, "lon": -84.55, "accuracy": 12.0} for i in range(n)],
    }


def test_ingest_is_idempotent_and_queryable(rt):
    first = mobile.ingest(rt, payload(3))
    assert first == {"app_sessions": 1, "web_visits": 1, "locations": 3, "skipped": 0}
    assert mobile.ingest(rt, payload(3)) == {"app_sessions": 0, "web_visits": 0, "locations": 0, "skipped": 0}
    rows = rt.db.query("SELECT source, kind, title, json_extract(data,'$.duration_s') AS d FROM events ORDER BY source")
    assert {(r["source"], r["kind"]) for r in rows} == {("phone_usage", "app_session"), ("phone_web", "web_visit"),
                                                        ("location", "point")}
    assert next(r for r in rows if r["source"] == "phone_usage")["d"] == 300


def test_bad_rows_are_skipped_not_fatal(rt):
    res = mobile.ingest(rt, {"app_sessions": [{"package": "x", "start": 10, "end": 5}, {"start": "nope"}],
                             "locations": [{"ts": NOW, "lat": 200, "lon": 0}, {"ts": NOW, "lat": "a", "lon": 1}]})
    assert res["skipped"] == 4 and res["app_sessions"] == 0


async def test_phone_sections_in_daily_report(rt):
    mobile.ingest(rt, payload())
    spec = reports.load_spec(rt, "daily")
    phone = next(s for s in spec["sections"] if s["title"] == "Phone")
    rows = reports.gather_section_data(rt, phone, time.time() - 86400)
    assert rows and rows[0]["app"] == "Discord" and rows[0]["sessions"] == 1


def test_endpoint(rt):
    with TestClient(create_app(rt, start_scheduler=False)) as c:
        assert c.post("/mobile/sync", json=payload()).status_code == 401
        r = c.post("/mobile/sync", json=payload(2), headers={"Authorization": "Bearer test-token"})
        assert r.status_code == 200 and r.json()["accepted"]["locations"] == 2
        assert c.post("/mobile/sync", json=[1, 2], headers={"Authorization": "Bearer test-token"}).status_code == 400

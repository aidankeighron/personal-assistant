"""Data from the Android app (mobile/). POST /mobile/sync with:

    {"device": "Pixel 8",
     "app_sessions": [{"package", "label", "start", "end"}],          # epoch ms
     "web_visits":   [{"url", "domain", "browser", "start", "end"}],
     "locations":    [{"ts", "lat", "lon", "accuracy"}]}

Stored as events (so Mother, reports and search see them):
    phone_usage / app_session   title = app name, data.duration_s
    phone_web   / web_visit     title = domain,   data.duration_s
    location    / point         (same kind as OwnTracks points), data.source = "mobile"

Event uids are derived from content, so re-sending a batch (e.g. after a timeout) never
duplicates anything. Keep this in sync with mobile/app/.../sync/Payload.kt.
"""

from __future__ import annotations

import logging
import math
from typing import Any

log = logging.getLogger(__name__)
MAX_ITEMS = 5000


def _ms(v: Any) -> int | None:
    try:
        x = int(float(v))
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None


def ingest(rt, payload: dict) -> dict[str, int]:
    device = str(payload.get("device") or "phone")[:60]
    db = rt.db
    out = {"app_sessions": 0, "web_visits": 0, "locations": 0, "skipped": 0}

    for s in (payload.get("app_sessions") or [])[:MAX_ITEMS]:
        start, end, pkg = _ms(s.get("start")), _ms(s.get("end")), str(s.get("package") or "")
        if not (start and end and pkg) or end < start:
            out["skipped"] += 1
            continue
        label = str(s.get("label") or pkg)[:120]
        data = {"package": pkg, "label": label, "start": start, "end": end,
                "duration_s": round((end - start) / 1000), "device": device}
        if db.add_event("phone_usage", "app_session", start / 1000, label, pkg, data,
                        uid=f"m:{device}:app:{pkg}:{start}"):
            out["app_sessions"] += 1

    for v in (payload.get("web_visits") or [])[:MAX_ITEMS]:
        start, end = _ms(v.get("start")), _ms(v.get("end"))
        url, domain = str(v.get("url") or "")[:2000], str(v.get("domain") or "")[:200]
        if not (start and end and domain) or end < start:
            out["skipped"] += 1
            continue
        data = {"url": url, "domain": domain, "browser": str(v.get("browser") or ""), "start": start, "end": end,
                "duration_s": round((end - start) / 1000), "device": device}
        if db.add_event("phone_web", "web_visit", start / 1000, domain, url, data,
                        uid=f"m:{device}:web:{url}:{start}"):
            out["web_visits"] += 1

    for p in (payload.get("locations") or [])[:MAX_ITEMS]:
        ts = _ms(p.get("ts"))
        try:
            lat, lon = float(p.get("lat")), float(p.get("lon"))
        except (TypeError, ValueError):
            lat = lon = math.nan
        if not ts or not (-90 <= lat <= 90 and -180 <= lon <= 180):
            out["skipped"] += 1
            continue
        acc = p.get("accuracy")
        data = {"lat": lat, "lon": lon, "acc": acc, "device": device, "source": "mobile"}
        if db.add_event("location", "point", ts / 1000, "", "", data, uid=f"m:{device}:loc:{ts}"):
            out["locations"] += 1

    rt.db.kv_set("mobile:last_sync", {"device": device, **out})
    return out

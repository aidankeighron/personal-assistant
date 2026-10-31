"""PC usage from ActivityWatch, relayed through the host agent (AW stays bound to localhost)."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import collector


@collector("activitywatch")
async def collect_activitywatch(rt, cfg: dict) -> int:
    cursor = rt.db.kv_get("collector:activitywatch:cursor") or (time.time() - 86400)
    since = datetime.fromtimestamp(cursor, timezone.utc).isoformat()
    data = await rt.host.activitywatch(since)
    n = 0
    newest = cursor
    for ev in data.get("events", []):
        ts = datetime.fromisoformat(ev["timestamp"].replace("Z", "+00:00")).timestamp()
        d = ev.get("data", {})
        kind = ev.get("kind", "window")
        title = d.get("app") or d.get("status") or d.get("url") or ""
        body = d.get("title", "")
        if rt.db.add_event("activitywatch", kind, ts, title, body,
                           {**d, "duration": ev.get("duration", 0)}, uid=f"aw:{ev.get('bucket')}:{ev.get('id', ts)}"):
            n += 1
        newest = max(newest, ts)
    rt.db.kv_set("collector:activitywatch:cursor", newest)
    return n

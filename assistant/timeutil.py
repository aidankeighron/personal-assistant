"""Timezone-aware helpers (M7 may run in UTC; you live in local time)."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import Settings


def tz(settings: Settings) -> ZoneInfo:
    return ZoneInfo(settings.get("timezone") or "UTC")


def now_local(settings: Settings) -> datetime:
    return datetime.now(tz(settings))


def fmt_ts(settings: Settings, ts: float | None) -> str:
    if ts is None:
        return ""
    return datetime.fromtimestamp(ts, tz(settings)).strftime("%a %b %d %I:%M %p")


def parse_when(settings: Settings, minutes: float | None = None, at: str | None = None) -> float:
    """Return an epoch timestamp from 'N minutes' or a clock/ISO time (next occurrence)."""
    now = now_local(settings)
    if minutes is not None:
        return (now + timedelta(minutes=float(minutes))).timestamp()
    if not at:
        raise ValueError("need minutes or at")
    at = at.strip().lower()
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", at)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3)
        if ap == "pm" and h < 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target.timestamp()
    dt = datetime.fromisoformat(at.upper() if "t" in at else at)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz(settings))
    return dt.timestamp()

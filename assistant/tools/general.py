"""Everyday tools: time, weather, web lookup, timers/reminders, notes, memory, notify."""

from __future__ import annotations

import time
import urllib.parse

import httpx

from ..timeutil import fmt_ts, now_local, parse_when
from . import ToolContext, tool


@tool("Get the current local date and time.")
def get_time(ctx: ToolContext) -> dict:
    n = now_local(ctx.rt.settings)
    return {"now": n.strftime("%A %B %d %Y, %I:%M %p"), "iso": n.isoformat()}


@tool(
    "Get live current weather for a city (Open-Meteo, no key).",
    city={"type": "string", "description": "City name, e.g. 'East Lansing'"},
)
async def get_weather(ctx: ToolContext, city: str = "") -> dict:
    city = city or ctx.rt.settings["weather"]["default_city"]
    async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "personal-assistant/0.1"}) as c:
        g = (await c.get("https://geocoding-api.open-meteo.com/v1/search",
                         params={"name": city, "count": 1, "format": "json"})).json()
        if not g.get("results"):
            return {"error": f"unknown city {city}"}
        loc = g["results"][0]
        w = (await c.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "current": "temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
            "forecast_days": 1, "timezone": "auto",
            "temperature_unit": "fahrenheit", "wind_speed_unit": "mph",
        })).json()
    cur, day = w.get("current", {}), w.get("daily", {})
    return {
        "location": f"{loc['name']}, {loc.get('admin1', '')}",
        "temp_f": cur.get("temperature_2m"),
        "feels_like_f": cur.get("apparent_temperature"),
        "humidity": cur.get("relative_humidity_2m"),
        "wind_mph": cur.get("wind_speed_10m"),
        "condition": _wmo(cur.get("weather_code", 0)),
        "high_f": (day.get("temperature_2m_max") or [None])[0],
        "low_f": (day.get("temperature_2m_min") or [None])[0],
        "precip_chance": (day.get("precipitation_probability_max") or [None])[0],
    }


def _wmo(code: int) -> str:
    if code == 0:
        return "clear"
    if code < 4:
        return "partly cloudy"
    if code < 50:
        return "fog"
    if code < 70:
        return "rain"
    if code < 80:
        return "snow"
    if code < 90:
        return "showers"
    return "thunderstorm"


@tool("Quick web lookup (DuckDuckGo instant answers).", query={"type": "string", "description": "Search query"})
async def search_web(ctx: ToolContext, query: str) -> dict:
    url = "https://api.duckduckgo.com/?" + urllib.parse.urlencode(
        {"q": query, "format": "json", "no_html": 1, "skip_disambig": 1})
    async with httpx.AsyncClient(timeout=6, headers={"User-Agent": "personal-assistant/0.1"}) as c:
        d = (await c.get(url)).json()
    if d.get("AbstractText"):
        return {"summary": d["AbstractText"], "source": d.get("AbstractURL")}
    related = [t.get("Text") for t in d.get("RelatedTopics", [])[:4] if isinstance(t, dict) and t.get("Text")]
    return {"related": related} if related else {"note": "no instant answer; say you don't know or answer from knowledge"}


@tool(
    "Set a timer, alarm, or reminder. Use `minutes` for relative times or `at` for clock times.",
    text={"type": "string", "description": "What to remind about, e.g. 'pasta' or 'call mom'"},
    minutes={"type": "number", "description": "Minutes from now (for timers)"},
    at={"type": "string", "description": "Clock time or ISO datetime, e.g. '07:30' or '2026-11-02T09:00'"},
    kind={"type": "string", "enum": ["timer", "alarm", "reminder"]},
)
def set_reminder(ctx: ToolContext, text: str, minutes: float | None = None, at: str | None = None,
                 kind: str = "reminder") -> dict:
    due = parse_when(ctx.rt.settings, minutes=minutes, at=at)
    rid = ctx.rt.db.execute(
        "INSERT INTO reminders(text, due, kind, created) VALUES (?,?,?,?)", (text, due, kind, time.time()))
    return {"id": rid, "kind": kind, "text": text, "due": fmt_ts(ctx.rt.settings, due)}


@tool("List pending timers, alarms and reminders.")
def list_reminders(ctx: ToolContext) -> list:
    rows = ctx.rt.db.query("SELECT id, kind, text, due FROM reminders WHERE status='pending' ORDER BY due")
    return [{**r, "due": fmt_ts(ctx.rt.settings, r["due"])} for r in rows]


@tool("Cancel a timer/alarm/reminder by id.", id={"type": "integer"})
def cancel_reminder(ctx: ToolContext, id: int) -> dict:
    n = ctx.rt.db.execute("UPDATE reminders SET status='cancelled' WHERE id=? AND status='pending'", (id,))
    return {"cancelled": bool(n)}


@tool(
    "Save something the user explicitly asked you to remember, or a standing rule ('from now on ...').",
    fact={"type": "string", "description": "The fact or rule, written as a short standalone sentence"},
    domain={"type": "string", "description": "Topic tag: general, coding, hardware, food, schedule, reports, ..."},
)
def remember(ctx: ToolContext, fact: str, domain: str = "general") -> dict:
    from ..memory import add_fact
    return add_fact(ctx.rt.db, fact, tier="explicit", domain=domain, source=f"{ctx.agent}:{ctx.conversation}")


@tool("Append a line to today's daily note.", text={"type": "string"})
def take_note(ctx: ToolContext, text: str) -> dict:
    n = now_local(ctx.rt.settings)
    d = ctx.rt.settings.data_dir / "notes"
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{n:%Y-%m-%d}.md"
    with path.open("a", encoding="utf-8") as f:
        f.write(f"- {n:%H:%M} {text}\n")
    return {"saved": str(path.name)}


@tool("Read the morning brief Mother pre-computed (schedule, email digest, tasks, weather).")
def read_morning_brief(ctx: ToolContext) -> dict:
    brief = ctx.rt.db.kv_get("brief")
    if not brief:
        return {"note": "no brief yet; Mother's nightly run hasn't produced one"}
    return brief


@tool(
    "Send a push notification to the user's phone.",
    title={"type": "string"}, message={"type": "string"},
)
async def send_notification(ctx: ToolContext, title: str, message: str) -> dict:
    ok = await ctx.rt.notifier.send(title, message)
    return {"sent": ok}


@tool("Search everything collected (email, calendar, notes, activity, location...) by keywords.",
      text={"type": "string", "description": "Keywords"})
def search_memory(ctx: ToolContext, text: str) -> list:
    from ..memory import fts_query
    rows = ctx.rt.db.search_events(fts_query(text), limit=12)
    for r in rows:
        r["ts"] = fmt_ts(ctx.rt.settings, r["ts"])
    return rows


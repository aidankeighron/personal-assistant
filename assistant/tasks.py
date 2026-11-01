"""Scheduled / background tasks: nightly pipeline, reminders, perishables, location, backups."""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
import subprocess
import time
from datetime import timedelta
from pathlib import Path

from . import jarvis_runner, reports
from .agents.skynet import audit as skynet_audit
from .collectors import run_collectors
from .host import HostUnavailable, heavy_gpu_allowed, wake_on_lan
from .llm import LLMUnavailable
from .memory import add_fact
from .timeutil import fmt_ts, now_local
from .tools.groceries import expiring_soon

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PC / GPU helpers
# ---------------------------------------------------------------------------
async def ensure_pc_awake(rt, wait_seconds: int = 180) -> bool:
    try:
        await rt.llm.models()
        return True
    except LLMUnavailable:
        pass
    mac = rt.settings["pc"].get("mac_address")
    if not mac:
        return False
    log.info("waking PC via WOL")
    wake_on_lan(mac, rt.settings["pc"].get("broadcast", "255.255.255.255"))
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        await asyncio.sleep(10)
        try:
            await rt.llm.models()
            return True
        except LLMUnavailable:
            continue
    return False


async def wait_for_gpu(rt, max_wait: int = 3600, poll: int = 60) -> tuple[bool, str]:
    deadline = time.time() + max_wait
    reason = ""
    while True:
        ok, reason = await heavy_gpu_allowed(rt.host, rt.settings["gpu_gate"], now_local(rt.settings))
        if ok or time.time() > deadline:
            return ok, reason
        await asyncio.sleep(poll)


# ---------------------------------------------------------------------------
# Morning brief
# ---------------------------------------------------------------------------
def _day_bounds(rt, offset_days: int = 0) -> tuple[float, float]:
    d = now_local(rt.settings).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=offset_days)
    return d.timestamp(), (d + timedelta(days=1)).timestamp()


def gather_brief_data(rt) -> dict:
    t0, t1 = _day_bounds(rt)
    y0, y1 = _day_bounds(rt, -1)
    db = rt.db
    calendar = [{"time": fmt_ts(rt.settings, r["ts"]), "title": r["title"]} for r in db.query(
        "SELECT ts, title FROM events WHERE source='gcal' AND ts>=? AND ts<? ORDER BY ts", (t0, t1))]
    emails = db.query("SELECT title, substr(body,1,200) AS body FROM events WHERE source='gmail' AND ts>=? "
                      "ORDER BY ts DESC LIMIT 40", (time.time() - 86400,))
    apps = db.query(
        "SELECT title AS app, ROUND(SUM(CAST(json_extract(data,'$.duration') AS REAL))/3600.0, 2) AS hours "
        "FROM events WHERE source='activitywatch' AND kind='window' AND ts>=? AND ts<? "
        "GROUP BY title ORDER BY hours DESC LIMIT 8", (y0, y1))
    reminders = [{"time": fmt_ts(rt.settings, r["due"]), "text": r["text"]} for r in db.query(
        "SELECT text, due FROM reminders WHERE status='pending' AND due<? ORDER BY due", (t1,))]
    fridge = [r["item"] for r in expiring_soon(db, 2)]
    projects = [{"name": p["name"], "status": p["status_text"]} for p in jarvis_runner.list_projects(rt)[:5]]
    findings = db.query("SELECT severity, message FROM findings WHERE resolved=0 AND ts>? ORDER BY ts DESC LIMIT 5",
                        (time.time() - 86400,))
    return {"calendar": calendar, "emails": emails, "yesterday_apps": apps, "reminders": reminders,
            "fridge_expiring": fridge, "projects": projects, "findings": findings}


async def build_brief(rt) -> dict:
    from .tools import ToolContext
    from .tools.general import get_weather

    data = gather_brief_data(rt)
    try:
        data["weather"] = await get_weather(ToolContext(rt, "mother", "nightly"))
    except Exception as e:  # network hiccup shouldn't kill the brief
        data["weather"] = {"error": str(e)}
    email_digest = ""
    spoken = ""
    model = rt.settings.model("heavy")
    try:
        if data["emails"]:
            msg = await rt.llm.chat(model, [{"role": "user", "content":
                "Summarize these emails into at most 5 bullets of what actually needs attention. Skip noise.\n\n"
                + json.dumps(data["emails"])[:8000]}], max_tokens=300)
            email_digest = (msg.get("content") or "").strip()
        msg = await rt.llm.chat(model, [{"role": "user", "content":
            "Write a 3-5 sentence spoken morning briefing (plain text, warm but efficient) from this data. "
            "Mention weather, the day's schedule, anything urgent, and food about to expire.\n\n"
            + json.dumps({**data, "emails": email_digest}, default=str)[:9000]}], max_tokens=260)
        spoken = (msg.get("content") or "").strip()
    except LLMUnavailable:
        spoken = f"{len(data['calendar'])} events today. " + (
            f"Use soon: {', '.join(data['fridge_expiring'])}." if data["fridge_expiring"] else "")
    brief = {**data, "email_digest": email_digest, "spoken": spoken,
             "built_at": now_local(rt.settings).isoformat()}
    brief.pop("emails", None)
    rt.db.kv_set("brief", brief)
    return brief


# ---------------------------------------------------------------------------
# Memory extraction from yesterday's conversations
# ---------------------------------------------------------------------------
async def extract_memories(rt) -> int:
    since = time.time() - 86400
    rows = rt.db.query("SELECT content FROM messages WHERE role='user' AND ts>? ORDER BY ts", (since,))
    if not rows:
        return 0
    text = "\n".join(r["content"] for r in rows)[-8000:]
    d = await rt.llm.chat_json(rt.settings.model("heavy"), [{"role": "user", "content":
        "From these messages the user said to their assistant, extract durable facts about the user "
        "(preferences, projects, people, routines, hardware). Only things clearly stated, not guesses. "
        'JSON: {"facts": [{"text": "...", "domain": "coding|hardware|food|schedule|media|health|finance|general"}]}'
        "\n\n" + text}], max_tokens=500)
    n = 0
    for f in d.get("facts", [])[:20]:
        if isinstance(f, dict) and f.get("text"):
            add_fact(rt.db, f["text"], tier="candidate", domain=f.get("domain", "general"), source="nightly")
            n += 1
    return n


# ---------------------------------------------------------------------------
# Backup
# ---------------------------------------------------------------------------
def backup(rt) -> str:
    s = rt.settings
    out_dir = s.data_dir / "backups"
    out_dir.mkdir(exist_ok=True)
    dest = out_dir / f"assistant-{now_local(s):%Y%m%d-%H%M}.db"
    src = sqlite3.connect(str(s.db_path))
    dst = sqlite3.connect(str(dest))
    with dst:
        src.backup(dst)
    src.close()
    dst.close()
    keep = int(s["backup"].get("keep", 14))
    for old in sorted(out_dir.glob("assistant-*.db"))[:-keep]:
        old.unlink()
    target = s["backup"].get("target")
    if target:
        # rsync the db snapshot + editable config (reports, hud, notes) to the target
        srcs = [p for p in (dest, s.data_dir / "reports", s.data_dir / "notes") if Path(p).exists()]
        subprocess.run(["rsync", "-a", *map(str, srcs), target], check=True, timeout=1800)
    rt.db.kv_set("backup:last", time.time())
    return str(dest)


# ---------------------------------------------------------------------------
# Nightly pipeline
# ---------------------------------------------------------------------------
async def nightly(rt) -> dict:
    log.info("nightly: start")
    result: dict = {"started": now_local(rt.settings).isoformat()}
    result["collect"] = await run_collectors(rt)
    if rt.settings["gpu_gate"].get("wake_pc_for_nightly", True):
        result["pc_awake"] = await ensure_pc_awake(rt)
    if result.get("pc_awake") is False:
        ok, reason = False, "PC didn't come online (asleep with no Wake-on-LAN, or shut down)"
    else:
        ok, reason = await wait_for_gpu(rt, max_wait=int(rt.settings["gpu_gate"].get("nightly_max_wait", 5400)))
    result["gpu"] = reason
    if ok:
        try:
            result["brief"] = bool(await build_brief(rt))
            result["memories"] = await extract_memories(rt)
            for name in rt.settings.get("nightly_reports", ["daily"]):
                try:
                    r = await reports.generate(rt, name)
                    result.setdefault("reports", []).append(r["path"])
                except FileNotFoundError:
                    continue
        except LLMUnavailable as e:
            result["llm_error"] = str(e)
    result["audit"] = len(await skynet_audit(rt))
    try:
        result["backup"] = backup(rt)
    except Exception as e:
        result["backup_error"] = str(e)
        log.warning("backup failed: %s", e)
    rt.db.kv_set("nightly:last", result)
    brief = rt.db.kv_get("brief") or {}
    await rt.notifier.send("Mother: morning brief ready", (brief.get("spoken") or "Nightly run finished.")[:400],
                           tags=["sunrise"])
    log.info("nightly: done %s", result)
    return result


# ---------------------------------------------------------------------------
# Reminders / perishables
# ---------------------------------------------------------------------------
async def fire_due_reminders(rt) -> int:
    due = rt.db.query("SELECT id, text, kind FROM reminders WHERE status='pending' AND due<=?", (time.time(),))
    for r in due:
        rt.db.execute("UPDATE reminders SET status='fired' WHERE id=?", (r["id"],))
        label = {"timer": "Timer done", "alarm": "Alarm", "reminder": "Reminder"}.get(r["kind"], "Reminder")
        await rt.notifier.send(f"Rocky: {label}", r["text"], priority=5 if r["kind"] == "alarm" else 4,
                               tags=["alarm_clock"])
        try:
            await rt.host.speak(f"{label}: {r['text']}", agent="rocky")
        except HostUnavailable:
            pass
    return len(due)


async def perishables_reminder(rt) -> int:
    items = expiring_soon(rt.db, 2)
    if items:
        names = ", ".join(i["item"] for i in items)
        await rt.notifier.send("Rocky: eat these soon", f"Going bad soon: {names}", tags=["broccoli"])
    return len(items)


# ---------------------------------------------------------------------------
# Location (OwnTracks / Tasker / iOS Shortcuts webhook)
# ---------------------------------------------------------------------------
async def handle_location(rt, payload: dict) -> dict:
    """Accepts OwnTracks JSON or a simple {"event": "enter|leave", "place": "Kroger"}."""
    kind = payload.get("_type", "transition" if "event" in payload else "location")
    ts = float(payload.get("tst") or time.time())
    if kind == "location":
        rt.db.add_event("location", "point", ts, ",".join(payload.get("inregions", []) or []),
                        "", {k: payload.get(k) for k in ("lat", "lon", "acc", "batt", "inregions")},
                        uid=f"loc:{ts}")
        return {"stored": "point"}
    event = (payload.get("event") or "").lower()
    place = payload.get("desc") or payload.get("place") or payload.get("region") or "somewhere"
    rt.db.add_event("location", event or "transition", ts, place, f"{event} {place}", payload,
                    uid=f"loc:{event}:{place}:{ts}")
    gcfg = rt.settings["groceries"]
    is_store = any(k in place.lower() for k in gcfg.get("store_keywords", []))
    ask_on = gcfg.get("ask_on", "leave")
    if is_store and event == ask_on:
        rt.db.kv_set("pending_grocery_question", {"place": place, "ts": time.time()})
        base = rt.settings["server"]["public_url"].rstrip("/")
        await rt.notifier.send("Rocky", f"You were at {place}. What did you buy? Tell me and I track fridge.",
                               tags=["shopping_cart"], click=f"{base}/app")
        return {"asked": True, "place": place}
    return {"stored": event, "place": place}


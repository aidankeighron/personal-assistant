"""Tiny in-process scheduler (no cron dependency, survives on a weak box).

Schedule entries in settings.yaml:
    - {name: nightly, daily: "05:00", task: nightly}
    - {name: collect, every: "30m", task: collect}
    - {name: weekly_sync, weekly: "sun 03:00", task: collect, args: {names: [github]}}
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timedelta

from .timeutil import now_local

log = logging.getLogger(__name__)
DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def parse_every(spec: str) -> float:
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*([smhd])\s*", spec)
    if not m:
        raise ValueError(f"bad interval {spec!r}")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[m.group(2)]


def next_run(entry: dict, now: datetime) -> datetime:
    if "every" in entry:
        return now + timedelta(seconds=parse_every(entry["every"]))
    if "daily" in entry:
        h, m = map(int, entry["daily"].split(":"))
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        return t if t > now else t + timedelta(days=1)
    if "weekly" in entry:
        day, hm = entry["weekly"].lower().split()
        h, m = map(int, hm.split(":"))
        t = now.replace(hour=h, minute=m, second=0, microsecond=0)
        t += timedelta(days=(DAYS.index(day[:3]) - now.weekday()) % 7)
        return t if t > now else t + timedelta(days=7)
    raise ValueError(f"schedule entry needs every/daily/weekly: {entry}")


def task_table() -> dict:
    from . import jarvis_runner, models, reports, tasks
    from .agents.skynet import audit
    from .collectors import run_collectors
    return {
        "nightly": lambda rt, **kw: tasks.nightly(rt),
        "collect": lambda rt, names=None, **kw: run_collectors(rt, names),
        "skynet_audit": lambda rt, **kw: audit(rt),
        "perishables_reminder": lambda rt, **kw: tasks.perishables_reminder(rt),
        "jarvis_status": lambda rt, **kw: jarvis_runner.refresh_status(rt),
        "backup": lambda rt, **kw: asyncio.to_thread(tasks.backup, rt),
        "reminders": lambda rt, **kw: tasks.fire_due_reminders(rt),
        "brief": lambda rt, **kw: tasks.build_brief(rt),
        "report": lambda rt, name="daily", **kw: reports.generate(rt, name),
        "ensure_models": lambda rt, **kw: models.ensure_models(rt),
    }


class Scheduler:
    def __init__(self, rt):
        self.rt = rt
        self.entries = list(rt.settings.get("schedule") or [])
        # reminders must always be checked frequently
        if not any(e.get("task") == "reminders" for e in self.entries):
            self.entries.append({"name": "reminders", "every": "20s", "task": "reminders"})
        self.running: set[str] = set()
        self._stop = asyncio.Event()

    async def run(self) -> None:
        table = task_table()
        now = now_local(self.rt.settings)
        # run_at_start: fire once shortly after boot (e.g. ensure_models), then on schedule
        due = {e["name"]: (now if e.get("run_at_start") else next_run(e, now)) for e in self.entries}
        log.info("scheduler: %s", {k: v.strftime("%m-%d %H:%M:%S") for k, v in due.items()})
        while not self._stop.is_set():
            now = now_local(self.rt.settings)
            for e in self.entries:
                name = e["name"]
                if now >= due[name] and name not in self.running:
                    due[name] = next_run(e, now)
                    fn = table.get(e["task"])
                    if fn:
                        asyncio.create_task(self._run(name, fn, e.get("args", {})))
                    else:
                        log.warning("unknown task %s", e["task"])
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=5)
            except asyncio.TimeoutError:
                pass

    async def _run(self, name: str, fn, args: dict) -> None:
        self.running.add(name)
        t0 = time.time()
        try:
            res = await fn(self.rt, **args)
            self.rt.db.kv_set(f"task:{name}:last", {"ts": t0, "ok": True, "result": str(res)[:500]})
        except Exception as e:
            log.exception("task %s failed", name)
            self.rt.db.kv_set(f"task:{name}:last", {"ts": t0, "ok": False, "error": str(e)[:500]})
            jid = self.rt.db.enqueue(name)
            self.rt.db.execute("UPDATE jobs SET status='failed', error=?, finished=? WHERE id=?",
                               (str(e)[:500], time.time(), jid))
        finally:
            self.running.discard(name)

    def stop(self) -> None:
        self._stop.set()

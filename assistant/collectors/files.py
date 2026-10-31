"""File-based sources: the inbox drop folder and daily notes."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import collector

TS_KEYS = ("ts", "timestamp", "time", "date", "datetime", "created", "created_at", "Date", "Timestamp", "Time")
TITLE_KEYS = ("title", "name", "subject", "description", "Description", "Title", "Name", "app", "url", "merchant")


def _parse_ts(v) -> float | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v) / (1000 if v > 1e12 else 1)
    s = str(v).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        pass
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%d %H:%M:%S", "%d %b %Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return float(s)
    except ValueError:
        return None


def row_to_event(source: str, row: dict, fallback_ts: float) -> tuple[float, str, str]:
    ts = next((t for t in (_parse_ts(row.get(k)) for k in TS_KEYS) if t), None) or fallback_ts
    title = next((str(row[k]) for k in TITLE_KEYS if row.get(k)), source)
    body = " | ".join(f"{k}: {v}" for k, v in row.items() if v not in (None, "") and len(str(v)) < 500)
    return ts, title[:300], body[:4000]


def ingest_rows(rt, source: str, rows: list[dict], kind: str = "record", fallback_ts: float | None = None) -> int:
    n = 0
    fb = fallback_ts or time.time()
    for row in rows:
        if not isinstance(row, dict):
            row = {"value": row}
        ts, title, body = row_to_event(source, row, fb)
        uid = f"{source}:" + hashlib.sha1(json.dumps(row, sort_keys=True, default=str).encode()).hexdigest()
        if rt.db.add_event(source, row.get("kind", kind), ts, title, body, row, uid=uid):
            n += 1
    return n


def read_rows(path: Path) -> list[dict]:
    suf = path.suffix.lower()
    if suf == ".csv":
        with path.open(newline="", encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    if suf == ".jsonl":
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if suf == ".json":
        d = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            for k in ("items", "data", "records", "events", "results"):
                if isinstance(d.get(k), list):
                    return d[k]
            return [d]
        return d
    if suf in (".md", ".txt"):
        return [{"title": path.stem, "body": path.read_text(encoding="utf-8", errors="ignore")[:20000]}]
    return []


@collector("inbox")
async def collect_inbox(rt, cfg: dict) -> int:
    """<data>/inbox/<source>/<file>.(csv|json|jsonl|md|txt) -> events, then moved to inbox/_done/."""
    inbox = rt.settings.inbox_dir
    done = inbox / "_done"
    n = 0
    for src_dir in sorted(p for p in inbox.iterdir() if p.is_dir() and not p.name.startswith("_")):
        for f in sorted(src_dir.iterdir()):
            if not f.is_file():
                continue
            rows = read_rows(f)
            n += ingest_rows(rt, src_dir.name, rows, fallback_ts=f.stat().st_mtime)
            dest = done / src_dir.name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.move(str(f), dest / f"{int(time.time())}-{f.name}")
    return n


@collector("notes")
async def collect_notes(rt, cfg: dict) -> int:
    """Daily notes / voice transcripts: markdown files in <data>/notes and any extra dirs."""
    dirs = [rt.settings.data_dir / "notes"] + [Path(d).expanduser() for d in cfg.get("dirs", [])]
    n = 0
    for d in dirs:
        if not d.exists():
            continue
        for f in d.rglob("*"):
            if f.suffix.lower() not in (".md", ".txt") or not f.is_file():
                continue
            st = f.stat()
            text = f.read_text(encoding="utf-8", errors="ignore")
            # one event per file version; re-ingest when it changes (today's note grows)
            uid = f"note:{f}:{int(st.st_mtime)}"
            old_prefix = f"note:{f}:"
            if rt.db.add_event("notes", "note", st.st_mtime, f.stem, text[:20000], {"path": str(f)}, uid=uid):
                rt.db.execute("DELETE FROM events WHERE uid LIKE ? AND uid<>?", (old_prefix + "%", uid))
                n += 1
    return n

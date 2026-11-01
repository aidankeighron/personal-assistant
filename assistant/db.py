"""SQLite storage. One file on the vault drive; WAL mode keeps it fast on an HDD.

Tables
------
messages   conversation log (every agent turn)
facts      tiered memory ledger (verified / explicit / candidate / quarantined)
events     everything collectors ingest (gmail, calendar, AW, location, ...) + FTS
jobs       background job queue (GPU-gated work waits here)
kv         small JSON values (morning brief cache, collector cursors, ...)
approvals  phone approvals (Jarvis Claude leases)
reminders  timers / alarms / reminders
groceries  fridge tracker
findings   Skynet audit results
projects / runs   Jarvis project registry + Claude Code runs
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY, conversation TEXT NOT NULL, agent TEXT, role TEXT NOT NULL,
    content TEXT NOT NULL, ts REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation, ts);

CREATE TABLE IF NOT EXISTS facts (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL UNIQUE, tier TEXT NOT NULL DEFAULT 'candidate',
    domain TEXT NOT NULL DEFAULT 'general', mentions INTEGER NOT NULL DEFAULT 1,
    source TEXT, reason TEXT, created REAL NOT NULL, updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY, source TEXT NOT NULL, kind TEXT NOT NULL, ts REAL NOT NULL,
    title TEXT, body TEXT, data TEXT, uid TEXT UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_events_src_ts ON events(source, ts);
CREATE VIRTUAL TABLE IF NOT EXISTS events_fts USING fts5(title, body, content='events', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS events_ai AFTER INSERT ON events BEGIN
    INSERT INTO events_fts(rowid, title, body) VALUES (new.id, new.title, new.body);
END;
CREATE TRIGGER IF NOT EXISTS events_ad AFTER DELETE ON events BEGIN
    INSERT INTO events_fts(events_fts, rowid, title, body) VALUES ('delete', old.id, old.title, old.body);
END;

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, payload TEXT, status TEXT NOT NULL DEFAULT 'pending',
    requires_gpu INTEGER NOT NULL DEFAULT 0, created REAL NOT NULL, started REAL, finished REAL,
    result TEXT, error TEXT
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT, updated REAL NOT NULL);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY, token TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, payload TEXT,
    status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL, expires REAL NOT NULL, decided REAL
);

CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY, text TEXT NOT NULL, due REAL NOT NULL, kind TEXT NOT NULL DEFAULT 'reminder',
    status TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS groceries (
    id INTEGER PRIMARY KEY, item TEXT NOT NULL, bought REAL NOT NULL, expires REAL,
    status TEXT NOT NULL DEFAULT 'in_fridge'
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY, ts REAL NOT NULL, severity TEXT NOT NULL, check_name TEXT NOT NULL,
    message TEXT NOT NULL, resolved INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS projects (
    name TEXT PRIMARY KEY, path TEXT NOT NULL, description TEXT, created REAL NOT NULL,
    updated REAL NOT NULL, status_text TEXT, last_run_id INTEGER
);

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY, project TEXT NOT NULL, prompt TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'awaiting_approval', session_id TEXT, pid INTEGER,
    log_path TEXT, result TEXT, created REAL NOT NULL, started REAL, finished REAL,
    lease_expires REAL, approval_id INTEGER
);
"""


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    # -- primitives ---------------------------------------------------------
    def execute(self, sql: str, params: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._conn.execute(sql, tuple(params))
            self._conn.commit()
            return cur.lastrowid or cur.rowcount

    def query(self, sql: str, params: Iterable[Any] = ()) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict | None:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def readonly_query(self, sql: str, limit: int = 200) -> list[dict]:
        """For LLM-written SQL: separate read-only connection, single statement."""
        if self.path == ":memory:":
            raise RuntimeError("read-only queries need a file database")
        stripped = sql.strip().rstrip(";")
        if ";" in stripped:
            raise ValueError("only one statement allowed")
        if not stripped.lower().startswith(("select", "with")):
            raise ValueError("only SELECT / WITH queries allowed")
        uri = Path(self.path).resolve().as_uri() + "?mode=ro"   # file:///C:/... on Windows, file:///... on Linux
        conn = sqlite3.connect(uri, uri=True, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            cur = conn.execute(stripped)
            return [dict(r) for r in cur.fetchmany(limit)]
        finally:
            conn.close()

    # -- messages -----------------------------------------------------------
    def add_message(self, conversation: str, role: str, content: str, agent: str | None = None) -> None:
        self.execute(
            "INSERT INTO messages(conversation, agent, role, content, ts) VALUES (?,?,?,?,?)",
            (conversation, agent, role, content, time.time()),
        )

    def recent_messages(self, conversation: str, limit: int = 12) -> list[dict]:
        rows = self.query(
            "SELECT role, content, agent FROM messages WHERE conversation=? ORDER BY ts DESC, id DESC LIMIT ?",
            (conversation, limit),
        )
        return list(reversed(rows))

    # -- kv -----------------------------------------------------------------
    def kv_set(self, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO kv(key, value, updated) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
            (key, json.dumps(value), time.time()),
        )

    def kv_get(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value FROM kv WHERE key=?", (key,))
        return json.loads(row["value"]) if row else default

    def kv_updated(self, key: str) -> float | None:
        row = self.one("SELECT updated FROM kv WHERE key=?", (key,))
        return row["updated"] if row else None

    # -- events -------------------------------------------------------------
    def add_event(self, source: str, kind: str, ts: float, title: str = "", body: str = "",
                  data: Any = None, uid: str | None = None) -> bool:
        """Insert an event; returns False if the uid already exists (dedupe)."""
        try:
            self.execute(
                "INSERT INTO events(source, kind, ts, title, body, data, uid) VALUES (?,?,?,?,?,?,?)",
                (source, kind, ts, title, body, json.dumps(data) if data is not None else None, uid),
            )
            return True
        except sqlite3.IntegrityError:
            return False

    def search_events(self, text: str, limit: int = 20) -> list[dict]:
        return self.query(
            "SELECT e.id, e.source, e.kind, e.ts, e.title, substr(e.body,1,400) AS body FROM events_fts f "
            "JOIN events e ON e.id=f.rowid WHERE events_fts MATCH ? ORDER BY e.ts DESC LIMIT ?",
            (text, limit),
        )

    # -- jobs ---------------------------------------------------------------
    def enqueue(self, kind: str, payload: Any = None, requires_gpu: bool = False) -> int:
        return self.execute(
            "INSERT INTO jobs(kind, payload, requires_gpu, created) VALUES (?,?,?,?)",
            (kind, json.dumps(payload or {}), int(requires_gpu), time.time()),
        )

    def close(self) -> None:
        with self._lock:
            self._conn.close()

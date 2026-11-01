"""Gmail, Google Calendar and Drive (read-only scopes).

Setup: create an OAuth "Desktop app" client in Google Cloud Console, download it as
``<data_dir>/google/client_secret.json``, then run ``python -m assistant auth-google``
on a machine with a browser (your PC is fine) and copy the resulting token.json to
``<data_dir>/google/token.json`` on M7. Needs: pip install -e ".[google]"
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import collector

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/drive.metadata.readonly",
]


def google_dir(rt) -> Path:
    d = rt.settings.data_dir / "google"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _creds(rt):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials

    tok = google_dir(rt) / "token.json"
    if not tok.exists():
        raise RuntimeError(f"missing {tok}; run `python -m assistant auth-google`")
    creds = Credentials.from_authorized_user_file(str(tok), SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        tok.write_text(creds.to_json(), encoding="utf-8")
    return creds


def authorize(client_secret: Path, token_out: Path) -> None:
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
    creds = flow.run_local_server(port=0)
    token_out.write_text(creds.to_json(), encoding="utf-8")


def _service(rt, name: str, version: str):
    from googleapiclient.discovery import build
    return build(name, version, credentials=_creds(rt), cache_discovery=False)


@collector("gmail")
async def collect_gmail(rt, cfg: dict) -> int:
    def work() -> int:
        svc = _service(rt, "gmail", "v1")
        days = int(cfg.get("days", 2))
        q = cfg.get("query", f"newer_than:{days}d -category:promotions")
        msgs = svc.users().messages().list(userId="me", q=q, maxResults=int(cfg.get("max", 100))).execute()
        n = 0
        for m in msgs.get("messages", []):
            if rt.db.one("SELECT 1 FROM events WHERE uid=?", (f"gmail:{m['id']}",)):
                continue
            full = svc.users().messages().get(userId="me", id=m["id"], format="metadata",
                                              metadataHeaders=["From", "Subject", "Date"]).execute()
            h = {x["name"]: x["value"] for x in full.get("payload", {}).get("headers", [])}
            ts = int(full.get("internalDate", time.time() * 1000)) / 1000
            if rt.db.add_event("gmail", "email", ts, h.get("Subject", "(no subject)"),
                               f"From: {h.get('From', '')}\n{full.get('snippet', '')}",
                               {"from": h.get("From"), "labels": full.get("labelIds", [])}, uid=f"gmail:{m['id']}"):
                n += 1
        return n
    return await asyncio.to_thread(work)


@collector("gcal")
async def collect_gcal(rt, cfg: dict) -> int:
    def work() -> int:
        svc = _service(rt, "calendar", "v3")
        now = datetime.now(timezone.utc)
        n = 0
        for cal in cfg.get("calendars", ["primary"]):
            items = svc.events().list(
                calendarId=cal, timeMin=(now - timedelta(days=1)).isoformat(),
                timeMax=(now + timedelta(days=int(cfg.get("days_ahead", 7)))).isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=250).execute().get("items", [])
            for e in items:
                start = e.get("start", {}).get("dateTime") or e.get("start", {}).get("date")
                ts = datetime.fromisoformat(start.replace("Z", "+00:00")).timestamp() if start else time.time()
                uid = f"gcal:{e['id']}:{e.get('updated', '')}"
                if rt.db.add_event("gcal", "calendar_event", ts, e.get("summary", "(busy)"),
                                   e.get("description", "")[:2000],
                                   {"start": start, "end": (e.get("end") or {}).get("dateTime"),
                                    "location": e.get("location"), "calendar": cal}, uid=uid):
                    rt.db.execute("DELETE FROM events WHERE uid LIKE ? AND uid<>?", (f"gcal:{e['id']}:%", uid))
                    n += 1
        return n
    return await asyncio.to_thread(work)


@collector("drive")
async def collect_drive(rt, cfg: dict) -> int:
    def work() -> int:
        svc = _service(rt, "drive", "v3")
        since = (datetime.now(timezone.utc) - timedelta(days=int(cfg.get("days", 2)))).isoformat()
        files = svc.files().list(q=f"modifiedTime > '{since}' and trashed = false", pageSize=100,
                                 fields="files(id,name,mimeType,modifiedTime,webViewLink)").execute().get("files", [])
        n = 0
        for f in files:
            ts = datetime.fromisoformat(f["modifiedTime"].replace("Z", "+00:00")).timestamp()
            if rt.db.add_event("drive", "file_modified", ts, f["name"], f.get("mimeType", ""),
                               f, uid=f"drive:{f['id']}:{f['modifiedTime']}"):
                n += 1
        return n
    return await asyncio.to_thread(work)

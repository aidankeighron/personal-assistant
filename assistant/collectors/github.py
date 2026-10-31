"""GitHub activity (pushes, PRs, issues, reviews) via the REST API."""

from __future__ import annotations

from datetime import datetime

import httpx

from . import collector


@collector("github")
async def collect_github(rt, cfg: dict) -> int:
    user = cfg.get("username")
    token = cfg.get("token")
    if not user:
        raise ValueError("collectors.github.username not set")
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "personal-assistant"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    n = 0
    async with httpx.AsyncClient(timeout=20, headers=headers) as c:
        r = await c.get(f"https://api.github.com/users/{user}/events", params={"per_page": 100})
        r.raise_for_status()
        for ev in r.json():
            ts = datetime.fromisoformat(ev["created_at"].replace("Z", "+00:00")).timestamp()
            repo = ev.get("repo", {}).get("name", "")
            p = ev.get("payload", {})
            kind = ev.get("type", "Event")
            body = ""
            if kind == "PushEvent":
                body = "\n".join(c.get("message", "") for c in p.get("commits", []))
            elif kind in ("PullRequestEvent", "IssuesEvent"):
                obj = p.get("pull_request") or p.get("issue") or {}
                body = f"{p.get('action')}: {obj.get('title', '')}"
            elif kind in ("IssueCommentEvent", "PullRequestReviewCommentEvent"):
                body = (p.get("comment", {}) or {}).get("body", "")[:1000]
            if rt.db.add_event("github", kind, ts, repo, body, {"repo": repo, "type": kind}, uid=f"gh:{ev['id']}"):
                n += 1
    return n

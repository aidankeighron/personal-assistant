"""Phone notifications. ntfy works out of the box (self-host it on M7 or use ntfy.sh)
and supports action buttons, which is what the Jarvis approval flow uses.

FCM can be added later as another backend with the same `send` signature.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, cfg: dict[str, Any]):
        self.cfg = cfg
        self.sent: list[dict] = []  # handy for tests / the web UI

    @property
    def enabled(self) -> bool:
        return bool(self.cfg.get("topic"))

    async def send(
        self,
        title: str,
        message: str,
        priority: int = 3,
        tags: list[str] | None = None,
        actions: list[dict] | None = None,
        click: str | None = None,
    ) -> bool:
        record = {"title": title, "message": message, "priority": priority, "tags": tags or [], "actions": actions or []}
        self.sent.append(record)
        self.sent = self.sent[-50:]
        if not self.enabled:
            log.info("notify (no topic configured): %s - %s", title, message)
            return False
        body: dict[str, Any] = {
            "topic": self.cfg["topic"],
            "title": title,
            "message": message,
            "priority": priority,
            "tags": tags or [],
        }
        if actions:
            body["actions"] = actions
        if click:
            body["click"] = click
        headers = {}
        if self.cfg.get("token"):
            headers["Authorization"] = f"Bearer {self.cfg['token']}"
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(self.cfg.get("ntfy_url", "https://ntfy.sh").rstrip("/"), json=body, headers=headers)
                r.raise_for_status()
            return True
        except httpx.HTTPError as e:
            log.warning("notify failed: %s", e)
            return False

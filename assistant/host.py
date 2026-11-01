"""Client for the Windows host agent (pc/host_agent.py) + Wake-on-LAN + GPU gate.

The host agent exposes a *whitelist* of actions only. M7 never gets a shell on the PC.
"""

from __future__ import annotations

import socket
from datetime import datetime, time as dtime
from typing import Any

import httpx


class HostUnavailable(RuntimeError):
    """The PC's host agent couldn't be reached (asleep, not logged in, offline)."""


class HostRefused(HostUnavailable):
    """The host agent answered but said no (not whitelisted, unknown mode, bad token)."""


class HostClient:
    def __init__(self, base_url: str, token: str, timeout: float = 8.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    async def _req(self, method: str, path: str, **kw: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.request(method, f"{self.base_url}{path}", headers=headers, **kw)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPStatusError as e:
            try:
                detail = e.response.json().get("detail", e.response.text)
            except ValueError:
                detail = e.response.text
            if e.response.status_code == 401:
                detail = "bad host agent token (PC_HOST_TOKEN on M7 must match host_agent.token on the PC)"
            raise HostRefused(f"PC refused: {str(detail)[:200]}") from e
        except httpx.HTTPError as e:
            raise HostUnavailable(f"host agent unreachable: {e}") from e

    async def health(self) -> dict:
        return await self._req("GET", "/health")

    async def idle(self) -> dict:
        """{'idle_seconds': float, 'fullscreen': bool, 'foreground': str}"""
        return await self._req("GET", "/idle")

    async def stats(self) -> dict:
        return await self._req("GET", "/stats")

    async def display(self, mode: str) -> dict:
        return await self._req("POST", "/display", json={"mode": mode})

    async def launch(self, app: str) -> dict:
        return await self._req("POST", "/launch", json={"app": app})

    async def close_app(self, app: str) -> dict:
        return await self._req("POST", "/close", json={"app": app})

    async def apps(self) -> dict:
        return await self._req("GET", "/apps")

    async def projector(self, url: str | None) -> dict:
        return await self._req("POST", "/projector", json={"url": url})

    async def speak(self, text: str, agent: str = "rocky") -> dict:
        return await self._req("POST", "/speak", json={"text": text, "agent": agent})

    async def activitywatch(self, since_iso: str) -> dict:
        return await self._req("GET", "/activitywatch", params={"since": since_iso})


def wake_on_lan(mac: str, broadcast: str = "255.255.255.255", port: int = 9) -> None:
    clean = mac.replace(":", "").replace("-", "").strip()
    if len(clean) != 12:
        raise ValueError(f"bad MAC address: {mac!r}")
    packet = bytes.fromhex("FF" * 6 + clean * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(packet, (broadcast, port))


def in_window(window: str, now: datetime | None = None) -> bool:
    """'04:30-06:30' -> is now inside? Handles windows that cross midnight."""
    if not window:
        return False
    start_s, end_s = window.split("-")
    start = dtime.fromisoformat(start_s.strip())
    end = dtime.fromisoformat(end_s.strip())
    t = (now or datetime.now()).time()
    return start <= t <= end if start <= end else (t >= start or t <= end)


async def heavy_gpu_allowed(host: HostClient, gate: dict, now: datetime | None = None) -> tuple[bool, str]:
    """Decide whether background GPU work may run right now.

    Allowed when inside the night window, or the user has been idle long enough and
    nothing is fullscreen (games / movies). Pass `now` in the *user's* timezone
    (tasks.wait_for_gpu does); M7's clock is often UTC.
    """
    try:
        info = await host.idle()
    except HostUnavailable as e:
        # Nobody is gaming at 5 AM on a PC whose host agent isn't up yet (e.g. just woken):
        # inside the night window that's fine; outside it we can't tell, so don't.
        if in_window(gate.get("night_window", ""), now):
            return True, f"night window (host agent unreachable: {e})"
        return False, f"PC unreachable ({e})"
    if info.get("fullscreen"):
        return False, f"fullscreen app running ({info.get('foreground', '?')})"
    if in_window(gate.get("night_window", ""), now):
        return True, "night window"
    idle = float(info.get("idle_seconds", 0))
    need = float(gate.get("idle_seconds", 600))
    if idle >= need:
        return True, f"user idle {idle:.0f}s"
    return False, f"user active (idle {idle:.0f}s < {need:.0f}s)"

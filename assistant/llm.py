"""Thin async client for Ollama running on the Windows PC."""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

import httpx


class LLMUnavailable(RuntimeError):
    """Raised when the PC (Ollama) can't be reached: asleep, gaming, offline."""


class OllamaClient:
    def __init__(self, base_url: str, keep_alive: str = "2m", timeout: float = 120.0):
        self.base_url = base_url.rstrip("/")
        self.keep_alive = keep_alive
        self.timeout = timeout

    async def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        tools: list[dict] | None = None,
        json_mode: bool = False,
        temperature: float = 0.4,
        max_tokens: int = 400,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": temperature, "num_predict": max_tokens},
        }
        if tools:
            payload["tools"] = tools
        if json_mode:
            payload["format"] = "json"
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                r = await client.post(f"{self.base_url}/api/chat", json=payload)
                r.raise_for_status()
                return r.json().get("message", {})
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as e:
            raise LLMUnavailable(f"Ollama unreachable at {self.base_url}: {e}") from e
        except httpx.HTTPStatusError as e:
            hint = f" (run `ollama pull {model}` on the PC)" if e.response.status_code == 404 else ""
            raise LLMUnavailable(f"Ollama error {e.response.status_code}{hint}: {e.response.text[:200]}") from e

    async def chat_json(self, model: str, messages: list[dict[str, Any]], **kw: Any) -> dict[str, Any]:
        msg = await self.chat(model, messages, json_mode=True, temperature=0.0, **kw)
        try:
            return json.loads(msg.get("content") or "{}")
        except json.JSONDecodeError:
            return {}

    async def unload(self, model: str) -> None:
        """Free VRAM immediately (e.g. when a game starts)."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{self.base_url}/api/generate", json={"model": model, "keep_alive": 0})
        except httpx.HTTPError:
            pass

    async def models(self) -> list[str]:
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{self.base_url}/api/tags")
                r.raise_for_status()
                return [m["name"] for m in r.json().get("models", [])]
        except httpx.HTTPError as e:
            raise LLMUnavailable(str(e)) from e

    async def pull(self, model: str, on_progress: Callable[[dict], Awaitable[None] | None] | None = None) -> None:
        """Download a model onto the PC (POST /api/pull, streamed). Raises on failure."""
        timeout = httpx.Timeout(30.0, read=600.0)  # big layers can stall for a while
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream("POST", f"{self.base_url}/api/pull",
                                         json={"model": model, "stream": True}) as r:
                    if r.status_code >= 400:
                        body = (await r.aread()).decode(errors="replace")[:300]
                        raise RuntimeError(f"pull {model}: HTTP {r.status_code} {body}")
                    last = {}
                    async for line in r.aiter_lines():
                        if not line.strip():
                            continue
                        ev = json.loads(line)
                        if ev.get("error"):
                            raise RuntimeError(f"pull {model}: {ev['error']}")
                        last = ev
                        if on_progress:
                            res = on_progress(ev)
                            if hasattr(res, "__await__"):
                                await res
                    if last.get("status") != "success":
                        raise RuntimeError(f"pull {model}: stream ended without success ({last})")
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            raise LLMUnavailable(f"Ollama unreachable at {self.base_url}: {e}") from e

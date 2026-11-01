"""Test fixtures: a Runtime with a fake LLM and fake PC host, on a temp data dir."""

from __future__ import annotations

import json
from typing import Any

import pytest

from assistant.config import load_settings
from assistant.db import Database
from assistant.notify import Notifier
from assistant.runtime import Runtime


class FakeLLM:
    """Scripted Ollama. Push responses with .script(); falls back to echoing."""

    def __init__(self):
        self.calls: list[dict] = []
        self.queue: list[dict] = []

    def script(self, *msgs: dict) -> None:
        self.queue.extend(msgs)

    async def chat(self, model, messages, tools=None, json_mode=False, **kw) -> dict:
        self.calls.append({"model": model, "messages": messages, "tools": tools, "json": json_mode})
        if self.queue:
            return self.queue.pop(0)
        return {"role": "assistant", "content": "ok"}

    async def chat_json(self, model, messages, **kw) -> dict:
        msg = await self.chat(model, messages, json_mode=True)
        try:
            return json.loads(msg.get("content") or "{}")
        except json.JSONDecodeError:
            return {}

    async def unload(self, model):
        pass

    async def models(self):
        return ["qwen2.5:7b", "qwen2.5:3b"]


class FakeHost:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []
        self.idle_info = {"idle_seconds": 5, "fullscreen": False, "foreground": "Code"}

    async def idle(self):
        return self.idle_info

    async def stats(self):
        return {"gpu": {"name": "NVIDIA GeForce RTX 3070 Ti"}, "ram_total_gb": 63.8}

    async def display(self, mode):
        self.calls.append(("display", mode))
        return {"mode": mode}

    async def launch(self, app):
        self.calls.append(("launch", app))
        return {"launched": app}

    async def speak(self, text, agent="rocky"):
        self.calls.append(("speak", text))
        return {}

    async def projector(self, url):
        self.calls.append(("projector", url))
        return {"projector": "on" if url else "off"}


@pytest.fixture
def rt(tmp_path, monkeypatch):
    monkeypatch.setenv("ASSISTANT_API_TOKEN", "test-token")
    s = load_settings("config/settings.example.yaml")
    s.raw["data_dir"] = str(tmp_path / "data")
    s.raw["jarvis"]["projects_dir"] = str(tmp_path / "projects")
    s.raw["jarvis"]["claude_home"] = str(tmp_path / "claude-home")   # never touch /mnt/vault from tests
    s.raw["jarvis"]["runner"] = "local"
    s.raw["notify"]["topic"] = ""
    s.raw["server"]["api_token"] = "test-token"
    r = Runtime(settings=s, db=Database(s.db_path), llm=FakeLLM(), host=FakeHost(), notifier=Notifier(s["notify"]))
    yield r
    r.db.close()

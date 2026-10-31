"""Runtime: the shared handles every agent, tool and job gets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .config import Settings, load_settings
from .db import Database
from .host import HostClient
from .llm import OllamaClient
from .notify import Notifier


@dataclass
class Runtime:
    settings: Settings
    db: Database
    llm: OllamaClient
    host: HostClient
    notifier: Notifier
    state: dict[str, Any] = field(default_factory=dict)  # in-process scratch (running procs, etc.)

    @classmethod
    def create(cls, settings: Settings | None = None, db_path: str | None = None) -> "Runtime":
        settings = settings or load_settings()
        pc = settings["pc"]
        return cls(
            settings=settings,
            db=Database(db_path or settings.db_path),
            llm=OllamaClient(pc["ollama_url"], keep_alive=pc.get("keep_alive", "2m")),
            host=HostClient(pc["host_agent_url"], pc.get("host_agent_token", "")),
            notifier=Notifier(settings["notify"]),
        )

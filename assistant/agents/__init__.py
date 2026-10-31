"""Agents. Each YAML in config/agents/ has a `kind` that maps to a class here."""

from __future__ import annotations

from .base import Agent, LLMAgent, Reply
from .jarvis import Jarvis
from .mother import Mother
from .rocky import Rocky
from .skynet import Skynet

KINDS: dict[str, type[Agent]] = {
    "rocky": Rocky,
    "jarvis": Jarvis,
    "mother": Mother,
    "skynet": Skynet,
    "llm": LLMAgent,  # generic: add a new persona with just a YAML file
}


def build_agents(settings) -> dict[str, Agent]:
    return {name: KINDS.get(cfg.kind, LLMAgent)(cfg) for name, cfg in settings.agents().items()}


__all__ = ["Agent", "LLMAgent", "Reply", "build_agents", "KINDS"]

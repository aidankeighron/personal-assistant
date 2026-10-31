"""Entry point for every message, from any surface (voice, web, phone, Discord, CLI)."""

from __future__ import annotations

import logging
import time

from .agents import Agent, Reply, build_agents
from .agents.base import EventCB
from .memory import add_fact, detect_domains, extract_explicit
from .router import choose_agent
from .runtime import Runtime

log = logging.getLogger(__name__)


class Orchestrator:
    def __init__(self, rt: Runtime):
        self.rt = rt
        self.agents: dict[str, Agent] = build_agents(rt.settings)

    def reload(self) -> None:
        """Pick up edited agent YAML without restarting."""
        self.agents = build_agents(self.rt.settings)

    async def handle(self, text: str, conversation: str = "default", source: str = "api",
                     agent: str | None = None, on_event: EventCB = None) -> dict:
        text = (text or "").strip()
        if not text:
            return Reply("system", "").as_dict()
        last = self.rt.db.kv_get(f"conv:{conversation}:agent") or {}
        if agent and agent in self.agents:
            name, body = agent, text
        else:
            name, body = choose_agent(text, last.get("agent"), last.get("ts"), set(self.agents))
        body = body or text
        if on_event:
            await on_event({"type": "routed", "agent": name})

        # Deterministic memory capture: "remember that ..." / "from now on ..."
        rule = extract_explicit(body)
        if rule:
            domain = next(iter(detect_domains(rule)), "general")
            add_fact(self.rt.db, rule, tier="explicit", domain=domain, source=f"{source}:{conversation}")

        t0 = time.perf_counter()
        reply = await self.agents[name].handle(self.rt, body, conversation, on_event)
        ms = (time.perf_counter() - t0) * 1000
        self.rt.db.add_message(conversation, "user", body, agent=name)
        if reply.text:
            self.rt.db.add_message(conversation, "assistant", reply.text, agent=name)
        self.rt.db.kv_set(f"conv:{conversation}:agent", {"agent": name, "ts": time.time()})
        out = reply.as_dict()
        out["latency_ms"] = round(ms)
        out["voice"] = self.agents[name].cfg.voice
        log.info("[%s/%s] %s -> %s (%.0fms)", source, name, body[:80], reply.text[:80], ms)
        return out

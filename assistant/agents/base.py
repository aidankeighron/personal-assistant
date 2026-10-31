"""Agent base classes + the shared tool-calling loop."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from .. import tools as toolreg
from ..config import AgentConfig
from ..llm import LLMUnavailable
from ..memory import MEMORY_RULE, relevant_facts
from ..timeutil import now_local

log = logging.getLogger(__name__)

EventCB = Callable[[dict], Awaitable[None]] | None


@dataclass
class Reply:
    agent: str
    text: str                      # what to show
    speak: str | None = None       # what to say out loud (None = same as text, "" = silent)
    data: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {"agent": self.agent, "text": self.text,
                "speak": self.text if self.speak is None else self.speak, "data": self.data}


class Agent:
    def __init__(self, cfg: AgentConfig):
        self.cfg = cfg
        self.name = cfg.name

    async def handle(self, rt, text: str, conversation: str, on_event: EventCB = None) -> Reply:
        raise NotImplementedError

    def offline_reply(self) -> Reply:
        return Reply(self.name, "My brain (the PC) is offline or busy right now. Try again in a bit.")


class LLMAgent(Agent):
    """Generic persona + tools agent. Most agents are this plus tweaks."""

    max_tool_rounds = 4
    max_tokens = 400

    def system_prompt(self, rt, text: str, conversation: str) -> str:
        facts = relevant_facts(rt.db, text)
        parts = [
            self.cfg.persona.strip(),
            f"Current time: {now_local(rt.settings):%A %B %d %Y %I:%M %p}.",
            MEMORY_RULE,
        ]
        if facts:
            parts.append("Relevant user facts:\n- " + "\n- ".join(facts))
        extra = self.context_notes(rt, text, conversation)
        if extra:
            parts.append(extra)
        return "\n\n".join(p for p in parts if p)

    def context_notes(self, rt, text: str, conversation: str) -> str:
        return ""

    def history(self, rt, conversation: str) -> list[dict]:
        n = int(self.cfg.options.get("history_turns", 10))
        rows = rt.db.recent_messages(conversation, limit=n)
        return [{"role": r["role"], "content": r["content"]} for r in rows if r["role"] in ("user", "assistant")]

    def postprocess(self, text: str) -> tuple[str, str | None]:
        return text, None

    async def handle(self, rt, text: str, conversation: str, on_event: EventCB = None) -> Reply:
        messages = [{"role": "system", "content": self.system_prompt(rt, text, conversation)}]
        messages += self.history(rt, conversation)
        messages.append({"role": "user", "content": text})
        try:
            content, used = await self.run_tool_loop(rt, messages, conversation, on_event)
        except LLMUnavailable as e:
            log.warning("%s: %s", self.name, e)
            return self.offline_reply()
        shown, spoken = self.postprocess(content)
        return Reply(self.name, shown, spoken, {"tools": used})

    async def run_tool_loop(self, rt, messages: list[dict], conversation: str,
                            on_event: EventCB = None) -> tuple[str, list[str]]:
        model = rt.settings.model(self.cfg.model)
        tool_schemas = toolreg.schemas(self.cfg.tools)
        ctx = toolreg.ToolContext(rt=rt, agent=self.name, conversation=conversation)
        used: list[str] = []
        for _ in range(self.max_tool_rounds):
            msg = await rt.llm.chat(model, messages, tools=tool_schemas or None, max_tokens=self.max_tokens)
            calls = msg.get("tool_calls") or []
            if not calls:
                return (msg.get("content") or "").strip(), used
            messages.append(msg)
            for c in calls:
                fn = c.get("function", {})
                name = fn.get("name", "")
                used.append(name)
                if on_event:
                    await on_event({"type": "tool", "agent": self.name, "tool": name})
                result = await toolreg.call(ctx, name, fn.get("arguments"), self.cfg.tools)
                log.info("%s tool %s -> %s", self.name, name, result[:200])
                messages.append({"role": "tool", "content": result, "tool_name": name})
        # out of rounds: ask for a final answer without tools
        messages.append({"role": "user", "content": "Answer now using what you have. No more tools."})
        msg = await rt.llm.chat(model, messages, max_tokens=self.max_tokens)
        return (msg.get("content") or "").strip(), used


def dumps(o: Any) -> str:
    return json.dumps(o, default=str)

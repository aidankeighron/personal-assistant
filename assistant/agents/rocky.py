"""Rocky: fast, everyday, always-on voice agent (from the prototype harness)."""

from __future__ import annotations

import random
import re

from .base import EventCB, LLMAgent, Reply

FILLER_KEYWORDS = {
    "weather": [r"\bweather\b", r"\btemperature\b", r"\brain\b", r"\bsnow\b", r"\bforecast\b", r"\boutside\b"],
    "pc": [r"\blaunch\b", r"\bopen\b", r"\bclose\b", r"\bplay\b", r"\bmovie mode\b", r"\bracing\b", r"\bdisplay\b",
           r"\bprojector\b", r"\bscreen\b"],
    "lookup": [r"\bsearch\b", r"\blook up\b", r"\bwho is\b", r"\bwhat is\b", r"\bnews\b"],
    "schedule": [r"\bschedule\b", r"\bcalendar\b", r"\btoday\b", r"\bbrief\b", r"\bemail\b"],
}
FILLERS = {
    "weather": ["I check sky now.", "Checking weather. One moment."],
    "pc": ["I do it now.", "On it. Good, good."],
    "lookup": ["I look up now.", "Searching. One moment."],
    "schedule": ["I check your day now.", "Reading brief now."],
}


def filler_for(text: str) -> str | None:
    t = text.lower()
    for cat, pats in FILLER_KEYWORDS.items():
        if any(re.search(p, t) for p in pats):
            return random.choice(FILLERS[cat])
    return None


def eridian(text: str) -> str:
    """Deterministic grammar filter so even a small model sounds like Rocky."""
    if not text:
        return ""
    out = text.strip()
    for pat, rep in [
        (r"\bI have to\b", "I must"), (r"\bI need to\b", "I must"), (r"\bI've got to\b", "I must"),
        (r"\bamazing\b", "amaze, amaze"), (r"\bawesome\b", "amaze"), (r"\bvery good\b", "good, good, good"),
    ]:
        out = re.sub(pat, rep, out, flags=re.I)

    def q(m: re.Match) -> str:
        s = m.group(1).rstrip()
        return f"{s}?" if s.lower().endswith("question") else f"{s}, question?"

    return re.sub(r"([^.!?\n]+)\?", q, out)


class Rocky(LLMAgent):
    max_tool_rounds = 3
    max_tokens = 220

    def context_notes(self, rt, text: str, conversation: str) -> str:
        notes = []
        pending = rt.db.kv_get("pending_grocery_question")
        if pending:
            notes.append(
                f"You recently asked the user what they bought at {pending.get('place', 'the store')}. "
                "If they list items, call add_groceries with them.")
        return "\n".join(notes)

    def postprocess(self, text: str) -> tuple[str, str | None]:
        if not self.cfg.options.get("eridian_filter", True):
            return text, None
        out = eridian(text)
        return out, out

    async def handle(self, rt, text: str, conversation: str, on_event: EventCB = None) -> Reply:
        f = filler_for(text)
        if f and on_event:
            await on_event({"type": "filler", "agent": self.name, "text": f})
        return await super().handle(rt, text, conversation, on_event)

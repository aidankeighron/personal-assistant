"""Who is being addressed? "Hey Jarvis, status update" -> ("jarvis", "status update").

Speech-to-text mangles names, so each agent has a few aliases. If nobody is named,
the conversation sticks with whoever you talked to in the last few minutes, else Rocky.
"""

from __future__ import annotations

import re
import time

ALIASES = {
    "rocky": ["rocky", "rockie", "rocki", "roxy", "rocky's", "raki"],
    "jarvis": ["jarvis", "jarvas", "jervis", "travis", "jarvus"],
    "mother": ["mother", "mom", "mu-th-ur", "muthur", "mothers"],
    "skynet": ["skynet", "sky net", "skinet"],
}
DEFAULT_AGENT = "rocky"
STICKY_SECONDS = 180

_PREFIX = r"^\s*(?:(?:hey|hi|ok|okay|yo|hello)[\s,]+)?"


def parse_address(text: str) -> tuple[str | None, str]:
    """Return (agent or None, remaining text)."""
    for agent, names in ALIASES.items():
        for n in names:
            m = re.match(_PREFIX + re.escape(n) + r"\b[\s,.:!?-]*(.*)$", text, re.I | re.S)
            if m:
                return agent, m.group(1).strip()
    return None, text.strip()


def choose_agent(text: str, last_agent: str | None, last_ts: float | None,
                 available: set[str], now: float | None = None) -> tuple[str, str]:
    agent, rest = parse_address(text)
    if agent and agent in available:
        return agent, rest or text
    now = now or time.time()
    if last_agent in available and last_ts and now - last_ts < STICKY_SECONDS:
        return last_agent, rest
    return (DEFAULT_AGENT if DEFAULT_AGENT in available else sorted(available)[0]), rest

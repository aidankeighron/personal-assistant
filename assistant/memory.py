"""Tiered memory ledger (the "anti-3080" design from docs/design/system.html).

Tiers
-----
verified     ground truth checked against telemetry (e.g. GPU from nvidia-smi)
explicit     things you said to remember / standing rules — trusted immediately
candidate    facts extracted from conversations; need repeat mentions to count
quarantined  contradicted or one-off; never injected into prompts

Facts are injected *only* when their domain matches the current request, and the
system prompt tells agents never to mention a fact just to show they know it.
"""

from __future__ import annotations

import re
import time

from .db import Database

DOMAIN_KEYWORDS = {
    "coding": ["code", "python", "bug", "repo", "github", "function", "build", "deploy", "test", "api", "script"],
    "hardware": ["gpu", "vram", "cpu", "ram", "pc", "computer", "monitor", "display", "model", "run", "drive"],
    "food": ["eat", "food", "fridge", "grocer", "dinner", "lunch", "breakfast", "cook", "recipe", "bought"],
    "schedule": ["today", "tomorrow", "calendar", "meeting", "schedule", "when", "remind", "alarm", "week"],
    "media": ["movie", "watch", "game", "play", "racing", "steam", "tv", "projector", "music"],
    "reports": ["report", "summary", "distribution", "status", "stats", "how much", "how many"],
    "health": ["sleep", "workout", "gym", "run", "steps", "weight"],
    "finance": ["money", "spend", "spent", "budget", "bank", "cost", "price", "$"],
}

EXPLICIT_PATTERNS = [
    re.compile(r"^\s*(?:please\s+)?remember(?: that)?\s+(.+)", re.I),
    re.compile(r"^\s*from now on,?\s+(.+)", re.I),
    re.compile(r"^\s*(?:going forward|in the future),?\s+(.+)", re.I),
]

MEMORY_RULE = (
    "You may know facts about the user. Use them ONLY to resolve ambiguous requests or to respect "
    "their constraints. NEVER mention a user fact just to show you know it. Never invent facts."
)


def detect_domains(text: str) -> set[str]:
    t = text.lower()
    return {d for d, kws in DOMAIN_KEYWORDS.items() if any(k in t for k in kws)}


def add_fact(db: Database, text: str, tier: str = "candidate", domain: str = "general",
             source: str = "", reason: str = "") -> dict:
    text = text.strip().rstrip(".") + "."
    now = time.time()
    row = db.one("SELECT id, tier, mentions FROM facts WHERE lower(text)=lower(?)", (text,))
    if row:
        new_tier = row["tier"]
        rank = {"quarantined": 0, "candidate": 1, "explicit": 2, "verified": 3}
        if rank.get(tier, 1) > rank.get(row["tier"], 1):
            new_tier = tier
        db.execute("UPDATE facts SET mentions=mentions+1, tier=?, updated=? WHERE id=?", (new_tier, now, row["id"]))
        return {"id": row["id"], "tier": new_tier, "mentions": row["mentions"] + 1, "new": False}
    fid = db.execute(
        "INSERT INTO facts(text, tier, domain, source, reason, created, updated) VALUES (?,?,?,?,?,?,?)",
        (text, tier, domain, source, reason, now, now))
    return {"id": fid, "tier": tier, "mentions": 1, "new": True}


def relevant_facts(db: Database, text: str, limit: int = 12) -> list[str]:
    domains = detect_domains(text) | {"general"}
    marks = ",".join("?" for _ in domains)
    rows = db.query(
        f"SELECT text FROM facts WHERE tier IN ('verified','explicit') AND domain IN ({marks}) "
        f"ORDER BY CASE tier WHEN 'verified' THEN 0 ELSE 1 END, updated DESC LIMIT ?",
        (*domains, limit))
    return [r["text"] for r in rows]


def extract_explicit(text: str) -> str | None:
    """'Remember that X' / 'From now on X' -> X (handled deterministically, no LLM)."""
    for pat in EXPLICIT_PATTERNS:
        m = pat.match(text)
        if m:
            return m.group(1).strip()
    return None


def fts_query(text: str) -> str:
    """Turn free text into a safe FTS5 OR-query."""
    words = [w for w in re.findall(r"[A-Za-z0-9]{2,}", text)][:8]
    return " OR ".join(f'"{w}"' for w in words) or '""'

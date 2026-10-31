"""Fridge tracker: what you bought, when it goes bad."""

from __future__ import annotations

import time

from ..timeutil import fmt_ts
from . import ToolContext, tool

DAY = 86400

# Rough fridge shelf life in days. Mother/you can extend this via config later.
SHELF_LIFE = {
    "milk": 7, "cream": 7, "yogurt": 14, "cheese": 21, "shredded cheese": 7, "butter": 60, "eggs": 28,
    "chicken": 2, "ground beef": 2, "beef": 4, "steak": 4, "pork": 4, "fish": 2, "salmon": 2, "shrimp": 2,
    "turkey": 3, "bacon": 7, "deli": 5, "ham": 5, "sausage": 5, "hot dogs": 10, "tofu": 5,
    "lettuce": 7, "spinach": 5, "salad": 5, "kale": 7, "broccoli": 5, "berries": 4, "strawberries": 4,
    "blueberries": 7, "raspberries": 3, "grapes": 7, "avocado": 4, "tomato": 5, "tomatoes": 5,
    "cucumber": 7, "peppers": 7, "mushrooms": 5, "carrots": 21, "celery": 14, "herbs": 5, "cilantro": 5,
    "bread": 6, "tortillas": 14, "hummus": 7, "salsa": 10, "juice": 10, "leftovers": 4, "apples": 30,
    "bananas": 5, "lemons": 21, "limes": 21, "potatoes": 30, "onions": 30,
}
NON_PERISHABLE_DAYS = None


def shelf_days(item: str) -> int | None:
    name = item.lower().strip()
    if name in SHELF_LIFE:
        return SHELF_LIFE[name]
    for key in sorted(SHELF_LIFE, key=len, reverse=True):
        if key in name:
            return SHELF_LIFE[key]
    return NON_PERISHABLE_DAYS


@tool(
    "Record groceries the user bought so perishables can be tracked.",
    items={"type": "array", "items": {"type": "string"}, "description": "Item names, e.g. ['milk','chicken']"},
)
def add_groceries(ctx: ToolContext, items: list[str]) -> dict:
    now = time.time()
    added = []
    for it in items:
        it = str(it).strip()
        if not it:
            continue
        days = shelf_days(it)
        exp = now + days * DAY if days else None
        ctx.rt.db.execute("INSERT INTO groceries(item, bought, expires) VALUES (?,?,?)", (it, now, exp))
        added.append({"item": it, "expires": fmt_ts(ctx.rt.settings, exp) if exp else "shelf-stable"})
    ctx.rt.db.kv_set("pending_grocery_question", None)
    return {"added": added}


@tool("List what's in the fridge, soonest-expiring first.")
def list_fridge(ctx: ToolContext) -> list:
    rows = ctx.rt.db.query(
        "SELECT id, item, bought, expires FROM groceries WHERE status='in_fridge' "
        "ORDER BY expires IS NULL, expires")
    now = time.time()
    out = []
    for r in rows:
        left = None if r["expires"] is None else round((r["expires"] - now) / DAY, 1)
        out.append({"id": r["id"], "item": r["item"], "days_left": left})
    return out


@tool(
    "Mark fridge items as eaten or thrown out.",
    items={"type": "array", "items": {"type": "string"}},
    status={"type": "string", "enum": ["eaten", "tossed"]},
)
def finish_groceries(ctx: ToolContext, items: list[str], status: str = "eaten") -> dict:
    done = []
    for it in items:
        row = ctx.rt.db.one(
            "SELECT id, item FROM groceries WHERE status='in_fridge' AND lower(item) LIKE ? ORDER BY bought LIMIT 1",
            (f"%{it.lower().strip()}%",))
        if row:
            ctx.rt.db.execute("UPDATE groceries SET status=? WHERE id=?", (status, row["id"]))
            done.append(row["item"])
    return {status: done}


def expiring_soon(db, within_days: float = 2.0) -> list[dict]:
    now = time.time()
    return db.query(
        "SELECT item, expires FROM groceries WHERE status='in_fridge' AND expires IS NOT NULL AND expires < ? "
        "ORDER BY expires", (now + within_days * DAY,))

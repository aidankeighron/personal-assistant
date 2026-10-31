"""Mother's data tools: describe/query the collected data, run and edit reports."""

from __future__ import annotations

from .. import reports
from . import ToolContext, tool


@tool("Describe what data exists: sources, event kinds, counts, date ranges, and the table schema.")
def describe_data(ctx: ToolContext) -> dict:
    rows = ctx.rt.db.query(
        "SELECT source, kind, COUNT(*) AS n, MIN(ts) AS first, MAX(ts) AS last FROM events GROUP BY source, kind")
    return {
        "sources": rows,
        "schema": {
            "events": "id, source, kind, ts (unix seconds), title, body, data (JSON text; use json_extract)",
            "messages": "conversation, agent, role, content, ts",
            "groceries": "item, bought, expires, status",
            "reminders": "text, due, kind, status",
            "facts": "text, tier, domain, mentions",
        },
        "tips": "Use datetime(ts,'unixepoch','localtime') for dates. json_extract(data,'$.field') for fields.",
    }


@tool(
    "Run a read-only SQL SELECT over the user's data (SQLite). Returns up to 200 rows.",
    sql={"type": "string"},
)
def query_data(ctx: ToolContext, sql: str) -> dict:
    rows = ctx.rt.db.readonly_query(sql, limit=200)
    return {"rows": rows, "count": len(rows)}


@tool("List available report types.")
def list_reports(ctx: ToolContext) -> list:
    return reports.list_reports(ctx.rt)


@tool("Generate a report now.", name={"type": "string", "description": "Report name, e.g. daily"})
async def run_report(ctx: ToolContext, name: str) -> dict:
    r = await reports.generate(ctx.rt, name)
    return {"spoken": r["spoken"], "saved_to": r["path"], "markdown": r["markdown"][:3000]}


@tool(
    "Change a report for all future runs. Add a standing instruction, add a section, or remove one.",
    name={"type": "string"},
    instruction={"type": "string", "description": "e.g. 'Always include total screen time'"},
    add_section_title={"type": "string"},
    add_section_prompt={"type": "string", "description": "What the new section should cover"},
    add_section_sources={"type": "array", "items": {"type": "string"},
                         "description": "Event sources to pull, e.g. ['gmail','gcal','activitywatch']"},
    remove_section={"type": "string"},
)
def update_report(ctx: ToolContext, name: str, instruction: str = "", add_section_title: str = "",
                  add_section_prompt: str = "", add_section_sources: list | None = None,
                  remove_section: str = "") -> dict:
    sec = None
    if add_section_title:
        sec = {"title": add_section_title, "prompt": add_section_prompt or add_section_title,
               "sources": add_section_sources or []}
    spec = reports.update_spec(ctx.rt, name, instruction or None, sec, remove_section or None)
    return {"updated": name, "sections": [s.get("title") for s in spec.get("sections", [])],
            "instructions": spec.get("instructions", [])}


@tool(
    "Create a brand-new report type.",
    name={"type": "string"}, title={"type": "string"}, description={"type": "string"},
    window_hours={"type": "number"},
    sections={"type": "array", "items": {"type": "object"},
              "description": "List of {title, prompt, sources:[...]} objects"},
)
def create_report(ctx: ToolContext, name: str, title: str, description: str = "", window_hours: float = 24,
                  sections: list | None = None) -> dict:
    spec = {"title": title, "description": description, "window_hours": window_hours,
            "speak_summary": True, "instructions": [], "sections": sections or []}
    path = reports.save_spec(ctx.rt, name, spec)
    return {"created": path.stem}

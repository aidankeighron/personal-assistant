"""Mother: data aggregation, analysis questions, reports. Slower, smarter, thorough."""

from __future__ import annotations

from .base import LLMAgent


class Mother(LLMAgent):
    max_tool_rounds = 6
    max_tokens = 700

    def context_notes(self, rt, text: str, conversation: str) -> str:
        from .. import reports
        names = ", ".join(r["name"] for r in reports.list_reports(rt)) or "none"
        brief_age = rt.db.kv_updated("brief")
        return (
            f"Available reports: {names}. "
            "To answer data questions: call describe_data first if unsure, then query_data with SQL. "
            "If the user wants future reports changed, call update_report. "
            f"Morning brief last built: {'never' if not brief_age else 'available'}."
        )

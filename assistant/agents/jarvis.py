"""Jarvis: coding agent. Doesn't chat — classifies what you want, then answers with
pre-made responses filled from project state. The real work is done by Claude Code
(see jarvis_runner.py); Jarvis just manages it and reads you the status.
"""

from __future__ import annotations

import re

from .. import jarvis_runner as jr
from ..llm import LLMUnavailable
from ..timeutil import fmt_ts
from .base import EventCB, Agent, Reply

INTENTS = ["list_projects", "status", "status_all", "build", "new_project", "cancel", "approve", "help"]

CLASSIFY_PROMPT = """Classify the user's request to a coding-assistant manager. Reply as JSON:
{{"intent": one of {intents},
 "project": project name mentioned or null ("previous"/"that"/"it" -> null),
 "task": the coding instructions if intent is build/new_project, else null,
 "git_url": a git URL if they gave one, else null}}

Known projects: {projects}
Last discussed project: {last}

Intent guide:
- list_projects: "list projects", "what are you working on"
- status: status/update on ONE project ("how's X going", "what's going on with that project")
- status_all: status on everything
- build: work on an EXISTING project ("add a login page to X", "fix the tests in it")
- new_project: start something new ("build me a ...", "make a new app that ...")
- cancel: stop/cancel work
- approve: "go ahead", "approved", "start it"
- help: anything else

User: {text}"""


def keyword_intent(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(list|all)\b.*\bprojects?\b|\bwhat (are you|projects)\b", t):
        return "list_projects"
    if re.search(r"\b(cancel|stop|abort|kill)\b", t):
        return "cancel"
    if re.search(r"\b(approve|approved|go ahead|start it)\b", t):
        return "approve"
    if re.search(r"\bstatus\b|\bupdate\b|\bgoing on\b|\bprogress\b|\bhow'?s\b", t):
        return "status_all" if re.search(r"\b(all|everything|every)\b", t) else "status"
    if re.search(r"\b(new|build me|make me|create)\b", t):
        return "new_project"
    if re.search(r"\b(add|fix|implement|refactor|change|build|write|update)\b", t):
        return "build"
    return "help"


class Jarvis(Agent):
    async def classify(self, rt, text: str) -> dict:
        projects = [p["name"] for p in jr.list_projects(rt)]
        last = rt.db.kv_get("jarvis:last_project")
        try:
            d = await rt.llm.chat_json(rt.settings.model(self.cfg.model), [{"role": "user", "content":
                CLASSIFY_PROMPT.format(intents=INTENTS, projects=projects or "none", last=last or "none", text=text)}],
                max_tokens=200)
        except LLMUnavailable:
            d = {}
        if d.get("intent") not in INTENTS:
            d = {"intent": keyword_intent(text), "project": None, "task": text}
        # name mentioned literally? trust that over the model
        for p in projects:
            if re.search(rf"\b{re.escape(p.replace('-', ' '))}\b", text.lower().replace("-", " ")):
                d["project"] = p
        return d

    def resolve_project(self, rt, name: str | None) -> dict | None:
        proj = jr.get_project(rt, name) if name else None
        if not proj:
            last = rt.db.kv_get("jarvis:last_project")
            proj = jr.get_project(rt, last) if last else None
        if proj:
            rt.db.kv_set("jarvis:last_project", proj["name"])
        return proj

    async def handle(self, rt, text: str, conversation: str, on_event: EventCB = None) -> Reply:
        d = await self.classify(rt, text)
        intent = d.get("intent")
        say = self._say

        if intent == "list_projects":
            projects = jr.list_projects(rt)
            if not projects:
                return say("No projects yet, sir. Tell me what to build.")
            names = ", ".join(p["name"].replace("-", " ") for p in projects[:8])
            return say(f"You have {len(projects)} project{'s' if len(projects) != 1 else ''}: {names}.",
                       {"projects": projects})

        if intent == "status_all":
            projects = jr.list_projects(rt)[:5]
            if not projects:
                return say("Nothing on the books, sir.")
            lines = [f"{p['name'].replace('-', ' ')}: {p['status_text']}" for p in projects]
            return say(" ".join(lines), {"projects": projects})

        if intent == "status":
            proj = self.resolve_project(rt, d.get("project"))
            if not proj:
                return say("Which project, sir? I don't have a recent one.")
            run = rt.db.one("SELECT status, created FROM runs WHERE project=? ORDER BY id DESC LIMIT 1", (proj["name"],))
            when = f" Last run {run['status']}, started {fmt_ts(rt.settings, run['created'])}." if run else ""
            return say(f"{proj['name'].replace('-', ' ')}: {proj['status_text']}", {"project": proj, "detail": when})

        if intent == "cancel":
            proj = self.resolve_project(rt, d.get("project"))
            if not proj:
                return say("Nothing to cancel, sir.")
            res = await jr.cancel(rt, proj["name"])
            return say("Cancelled." if res.get("status") == "cancelled" else "Nothing was running.", res)

        if intent == "approve":
            jr.grant_lease(rt)
            waiting = rt.db.query("SELECT id FROM runs WHERE status='awaiting_approval'")
            for w in waiting:
                await jr.start_run(rt, w["id"])
            return say(f"Lease granted. Starting {len(waiting)} waiting job{'s' if len(waiting) != 1 else ''}."
                       if waiting else "Lease granted, sir. Nothing was waiting.")

        if intent in ("build", "new_project"):
            task = (d.get("task") or text).strip()
            if intent == "new_project" or not self.resolve_project(rt, d.get("project")):
                name = d.get("project") or await self._name_for(rt, task)
                proj = jr.create_project(rt, name, description=task, git_url=d.get("git_url"))
            else:
                proj = self.resolve_project(rt, d.get("project"))
            res = await jr.request_run(rt, proj["name"], task)
            pretty = proj["name"].replace("-", " ")
            msg = {
                "awaiting_approval": f"Very good. I've queued {pretty}; approve it on your phone and I'll begin.",
                "started": f"Very good. Work has begun on {pretty}. Ask me for a status update any time.",
                "busy": f"{pretty} is already in progress, sir. I'll take that up once the current job finishes.",
            }.get(res["status"], f"Something went wrong starting {pretty}.")
            return say(msg, res)

        return say("I handle your coding projects, sir: list projects, status updates, or tell me what to build.")

    async def _name_for(self, rt, task: str) -> str:
        try:
            d = await rt.llm.chat_json(rt.settings.model("router"), [{"role": "user", "content":
                f'Give a 1-3 word kebab-case project name for: "{task}". JSON: {{"name": "..."}}'}], max_tokens=40)
            if d.get("name"):
                return jr.slug(d["name"])
        except LLMUnavailable:
            pass
        words = re.findall(r"[a-z0-9]+", task.lower())
        stop = {"build", "me", "a", "an", "the", "make", "new", "create", "that", "app", "for", "to", "please"}
        return "-".join([w for w in words if w not in stop][:3]) or "project"

    def _say(self, text: str, data: dict | None = None) -> Reply:
        return Reply(self.name, text, text, data or {})

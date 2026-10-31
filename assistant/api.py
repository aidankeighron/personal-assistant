"""HTTP API served from M7. Every client (PC voice, phone web app, Discord, OwnTracks,
ntfy approve buttons) talks to this."""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import jarvis_runner, models, tasks
from .collectors.files import ingest_rows
from .host import HostUnavailable
from .llm import LLMUnavailable
from .orchestrator import Orchestrator
from .runtime import Runtime
from .scheduler import Scheduler, task_table

log = logging.getLogger(__name__)
WEB = Path(__file__).parent / "web"


class ChatIn(BaseModel):
    text: str
    conversation: str = "default"
    agent: str | None = None
    source: str = "api"
    stream: bool = False


def create_app(rt: Runtime | None = None, start_scheduler: bool = True) -> FastAPI:
    state: dict[str, Any] = {}

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        runtime = rt or Runtime.create()
        state["rt"] = runtime
        state["orch"] = Orchestrator(runtime)
        jarvis_runner.mark_orphans(runtime)
        if not runtime.settings["server"].get("api_token"):
            log.warning("server.api_token is empty: API is UNAUTHENTICATED. Set it before exposing M7.")
        sched_task = None
        if start_scheduler:
            state["sched"] = Scheduler(runtime)
            sched_task = asyncio.create_task(state["sched"].run())
        yield
        if sched_task:
            state["sched"].stop()
            sched_task.cancel()

    app = FastAPI(title="Personal Assistant (M7)", lifespan=lifespan)

    def get_rt() -> Runtime:
        return state["rt"]

    def auth(request: Request) -> None:
        token = state["rt"].settings["server"].get("api_token", "")
        if not token:
            return
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or \
            request.query_params.get("token", "")
        if not hmac.compare_digest(given, token):
            raise HTTPException(401, "bad token")

    # -- public ---------------------------------------------------------------
    @app.get("/health")
    async def health() -> dict:
        return {"ok": True, "ts": time.time()}

    @app.get("/app", response_class=HTMLResponse)
    async def web_app() -> FileResponse:
        return FileResponse(WEB / "app.html")

    @app.get("/manifest.webmanifest")
    async def manifest() -> JSONResponse:
        return JSONResponse({"name": "Assistant", "short_name": "Rocky", "start_url": "/app",
                             "display": "standalone", "background_color": "#0b0b0d", "theme_color": "#0b0b0d"})

    @app.post("/approvals/{token}/{decision}")  # POST only: link previews must not approve
    async def approval(token: str, decision: str, rt: Runtime = Depends(get_rt)) -> dict:
        if decision not in ("approve", "deny"):
            raise HTTPException(400, "approve or deny")
        return await jarvis_runner.decide(rt, token, decision == "approve")

    # -- authenticated --------------------------------------------------------
    @app.post("/chat", dependencies=[Depends(auth)])
    async def chat(body: ChatIn):
        orch: Orchestrator = state["orch"]
        if not body.stream:
            return await orch.handle(body.text, body.conversation, body.source, body.agent)

        queue: asyncio.Queue = asyncio.Queue()

        async def on_event(ev: dict) -> None:
            await queue.put(ev)

        async def run() -> None:
            try:
                res = await orch.handle(body.text, body.conversation, body.source, body.agent, on_event)
                await queue.put({"type": "reply", **res})
            except Exception as e:  # surface errors to the client instead of hanging
                log.exception("chat failed")
                await queue.put({"type": "error", "error": str(e)})
            await queue.put(None)

        async def gen():
            task = asyncio.create_task(run())
            while True:
                ev = await queue.get()
                if ev is None:
                    break
                yield json.dumps(ev) + "\n"
            await task

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.get("/status", dependencies=[Depends(auth)])
    async def status(rt: Runtime = Depends(get_rt)) -> dict:
        out: dict[str, Any] = {"agents": list(state["orch"].agents)}
        try:
            out["models"] = await rt.llm.models()
            out["pc_llm"] = "online"
        except LLMUnavailable as e:
            out["pc_llm"] = f"offline: {e}"
        try:
            out["pc_host"] = await rt.host.idle()
        except HostUnavailable as e:
            out["pc_host"] = f"offline: {e}"
        out["lease_active"] = jarvis_runner.lease_active(rt)
        out["tasks"] = {r["key"][5:-5]: json.loads(r["value"]) for r in
                        rt.db.query("SELECT key, value FROM kv WHERE key LIKE 'task:%:last'")}
        out["findings"] = rt.db.query("SELECT ts, severity, message FROM findings WHERE resolved=0 "
                                      "ORDER BY ts DESC LIMIT 10")
        out["running"] = rt.db.query("SELECT id, project, status FROM runs WHERE status IN "
                                     "('running','awaiting_approval')")
        return out

    @app.get("/projects", dependencies=[Depends(auth)])
    async def projects(rt: Runtime = Depends(get_rt)) -> list:
        return jarvis_runner.list_projects(rt)

    @app.get("/projects/{name}", dependencies=[Depends(auth)])
    async def project(name: str, rt: Runtime = Depends(get_rt)) -> dict:
        p = jarvis_runner.get_project(rt, name)
        if not p:
            raise HTTPException(404, "no such project")
        runs = rt.db.query("SELECT id, prompt, status, created, finished, result FROM runs WHERE project=? "
                           "ORDER BY id DESC LIMIT 10", (p["name"],))
        return {**p, "runs": runs}

    @app.get("/brief", dependencies=[Depends(auth)])
    async def brief(rt: Runtime = Depends(get_rt)) -> dict:
        return rt.db.kv_get("brief") or {}

    @app.post("/location", dependencies=[Depends(auth)])
    async def location(request: Request, rt: Runtime = Depends(get_rt)):
        res = await tasks.handle_location(rt, await request.json())
        return [] if request.headers.get("x-limit-u") else res  # OwnTracks expects a JSON array

    @app.post("/ingest/{source}", dependencies=[Depends(auth)])
    async def ingest(source: str, request: Request, rt: Runtime = Depends(get_rt)) -> dict:
        body = await request.json()
        rows = body if isinstance(body, list) else [body]
        return {"ingested": ingest_rows(rt, source, rows)}

    @app.post("/tasks/{name}", dependencies=[Depends(auth)])
    async def run_task(name: str, rt: Runtime = Depends(get_rt)) -> dict:
        fn = task_table().get(name)
        if not fn:
            raise HTTPException(404, f"tasks: {sorted(task_table())}")
        asyncio.create_task(fn(rt))
        return {"started": name}

    @app.get("/models", dependencies=[Depends(auth)])
    async def models_status(rt: Runtime = Depends(get_rt)) -> dict:
        """Also used by pc/download_models.py to learn which Ollama models to fetch."""
        out: dict[str, Any] = {"required": models.required_models(rt.settings)}
        try:
            out.update(await models.model_status(rt))
        except LLMUnavailable as e:
            out["error"] = f"PC offline: {e}"
        out["last_ensure"] = rt.db.kv_get("models:status")
        return out

    @app.post("/models/pull", dependencies=[Depends(auth)])
    async def models_pull(rt: Runtime = Depends(get_rt)) -> dict:
        asyncio.create_task(models.ensure_models(rt, force=True))
        return {"started": True}

    @app.post("/reload", dependencies=[Depends(auth)])
    async def reload() -> dict:
        state["orch"].reload()
        return {"agents": list(state["orch"].agents)}

    @app.get("/hud", response_class=HTMLResponse, dependencies=[Depends(auth)])
    async def hud() -> FileResponse:
        return FileResponse(WEB / "hud.html")

    @app.get("/hud/{slug}", response_class=HTMLResponse, dependencies=[Depends(auth)])
    async def hud_custom(slug: str, rt: Runtime = Depends(get_rt)):
        f = rt.settings.data_dir / "hud" / f"{Path(slug).name}.html"
        if not f.exists():
            raise HTTPException(404, "no such screen")
        return HTMLResponse(f.read_text(encoding="utf-8"))

    return app

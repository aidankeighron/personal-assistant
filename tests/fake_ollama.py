"""A tiny HTTP server that speaks enough of Ollama's API to exercise the real client
(OllamaClient over httpx) without a GPU: /api/tags, streamed /api/pull, /api/chat
(with tool calls) and /api/generate (unload)."""

from __future__ import annotations

import json
import socket
import threading
import time

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

KNOWN = {"qwen2.5:7b", "qwen2.5:3b", "llama3.1:8b", "nomic-embed-text:latest"}


def make_app(installed: set[str]) -> FastAPI:
    app = FastAPI()
    app.state.installed = installed
    app.state.pulls = []
    app.state.chats = []

    @app.get("/api/tags")
    async def tags():
        return {"models": [{"name": m} for m in sorted(app.state.installed)]}

    @app.post("/api/pull")
    async def pull(req: Request):
        body = await req.json()
        name = body["model"] if ":" in body["model"] else body["model"] + ":latest"
        app.state.pulls.append(name)

        def gen():
            yield json.dumps({"status": "pulling manifest"}) + "\n"
            if name not in KNOWN:
                yield json.dumps({"error": "pull model manifest: file does not exist"}) + "\n"
                return
            for done in (0, 50, 100):
                yield json.dumps({"status": "pulling abc123", "digest": "sha256:abc123",
                                  "total": 100, "completed": done}) + "\n"
            yield json.dumps({"status": "verifying sha256 digest"}) + "\n"
            app.state.installed.add(name)
            yield json.dumps({"status": "success"}) + "\n"

        return StreamingResponse(gen(), media_type="application/x-ndjson")

    @app.post("/api/chat")
    async def chat(req: Request):
        body = await req.json()
        app.state.chats.append(body)
        if body["model"] not in app.state.installed:
            return JSONResponse({"error": f"model '{body['model']}' not found"}, status_code=404)
        msgs = body["messages"]
        has_tool_result = any(m.get("role") == "tool" for m in msgs)
        if body.get("tools") and not has_tool_result and "time" in msgs[-1]["content"].lower():
            msg = {"role": "assistant", "content": "",
                   "tool_calls": [{"function": {"name": "get_time", "arguments": {}}}]}
        elif has_tool_result:
            msg = {"role": "assistant", "content": "It is " + json.loads(msgs[-1]["content"])["now"]}
        else:
            msg = {"role": "assistant", "content": "Hello friend."}
        return {"model": body["model"], "message": msg, "done": True}

    @app.post("/api/generate")
    async def generate(req: Request):
        return {"done": True}

    return app


class FakeOllama:
    def __init__(self, installed: set[str] | None = None):
        self.app = make_app(set(installed or ()))
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self) -> "FakeOllama":
        self.thread.start()
        for _ in range(200):
            if self.server.started:
                return self
            time.sleep(0.02)
        raise RuntimeError("fake ollama didn't start")

    def __exit__(self, *exc) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)

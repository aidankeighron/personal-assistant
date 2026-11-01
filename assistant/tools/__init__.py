"""Tool registry. Agents list tool names in their YAML; the registry turns those into
Ollama tool schemas and dispatches calls.

Adding a tool:

    @tool("Describe what it does", city={"type": "string", "description": "..."})
    async def get_weather(ctx: ToolContext, city: str = "East Lansing") -> dict: ...

Tools receive a ToolContext and keyword args; they may be sync or async and return
str / dict / list (dicts are JSON-encoded for the model).
"""

from __future__ import annotations

import inspect
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable

log = logging.getLogger(__name__)


@dataclass
class ToolContext:
    rt: Any  # Runtime (typed loosely to avoid an import cycle)
    agent: str
    conversation: str


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict[str, Any]
    required: list[str]
    func: Callable[..., Any]

    def schema(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": self.parameters, "required": self.required},
            },
        }


REGISTRY: dict[str, Tool] = {}


def tool(_description: str, /, _required: list[str] | None = None, _name: str | None = None, **params: dict) -> Callable:
    def deco(fn: Callable) -> Callable:
        tname = _name or fn.__name__
        req = _required
        if req is None:
            sig = inspect.signature(fn)
            req = [p for p, v in sig.parameters.items() if p in params and v.default is inspect.Parameter.empty]
        REGISTRY[tname] = Tool(tname, _description, params, req, fn)
        return fn

    return deco


def schemas(names: list[str]) -> list[dict]:
    load_all()
    out = []
    for n in names:
        if n in REGISTRY:
            out.append(REGISTRY[n].schema())
        else:
            log.warning("agent config references unknown tool %r", n)
    return out


async def call(ctx: ToolContext, name: str, args: dict | str | None, allowed: list[str]) -> str:
    load_all()
    if name not in allowed:
        return json.dumps({"error": f"tool {name!r} is not allowed for {ctx.agent}"})
    t = REGISTRY.get(name)
    if not t:
        return json.dumps({"error": f"unknown tool {name!r}"})
    if isinstance(args, str):
        try:
            args = json.loads(args or "{}")
        except json.JSONDecodeError:
            args = {}
    args = {k: v for k, v in (args or {}).items() if k in t.parameters}
    from ..host import HostUnavailable
    from ..llm import LLMUnavailable
    try:
        res = t.func(ctx, **args)
        if inspect.isawaitable(res):
            res = await res
    except (HostUnavailable, LLMUnavailable, ValueError, FileNotFoundError) as e:  # expected: tell the model
        log.warning("tool %s: %s", name, e)
        return json.dumps({"error": str(e)})
    except Exception as e:  # tools must never crash a turn
        log.exception("tool %s failed", name)
        return json.dumps({"error": f"{type(e).__name__}: {e}"})
    return res if isinstance(res, str) else json.dumps(res, default=str)


_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    from . import data, general, groceries, home, sandbox  # noqa: F401

"""Automatic model management.

M7 is the source of truth for which Ollama models the agents need (settings.models +
each agent's `model:` + settings.extra_models). `ensure_models` compares that with
what the PC's Ollama has and pulls anything missing over Ollama's API, so changing a
model in settings.yaml is all it takes. It runs at startup and every few hours
(schedule task `ensure_models`), and from `python -m assistant models --pull`.

Downloads only use network + disk on the PC (not the GPU), but they are deferred while
a fullscreen game/movie is running so they don't eat your bandwidth mid-race.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from .host import HostUnavailable
from .llm import LLMUnavailable

log = logging.getLogger(__name__)


def normalize(name: str) -> str:
    """Ollama treats 'qwen2.5' and 'qwen2.5:latest' as the same model."""
    name = name.strip()
    return name if ":" in name.split("/")[-1] else f"{name}:latest"


def required_models(settings) -> list[str]:
    names = {settings.model(alias) for alias in settings["models"]}
    for cfg in settings.agents().values():
        if cfg.model:
            names.add(settings.model(cfg.model))
    names |= set(settings.get("extra_models") or [])
    return sorted(n for n in names if n)


async def model_status(rt) -> dict[str, Any]:
    required = required_models(rt.settings)
    installed = await rt.llm.models()
    have = {normalize(m) for m in installed}
    missing = [m for m in required if normalize(m) not in have]
    return {"required": required, "installed": installed, "missing": missing}


async def ensure_models(rt, pull: bool = True, force: bool = False,
                        progress: Callable[[str, dict], Any] | None = None) -> dict[str, Any]:
    """Pull every required-but-missing model. Never raises: returns a result dict."""
    try:
        status = await model_status(rt)
    except LLMUnavailable as e:
        return {"ok": False, "reason": f"PC offline: {e}"}
    result: dict[str, Any] = {"ok": not status["missing"], "required": status["required"],
                              "missing": status["missing"], "pulled": [], "failed": {}}
    if not status["missing"] or not pull:
        rt.db.kv_set("models:status", {**result, "ts": time.time()})
        return result
    if not force:
        try:
            idle = await rt.host.idle()
            if idle.get("fullscreen"):
                result["deferred"] = f"fullscreen app running ({idle.get('foreground', '?')})"
                return result
        except HostUnavailable:
            pass  # host agent down shouldn't block downloads
    for model in status["missing"]:
        log.info("pulling %s onto the PC", model)
        last_pct = -10

        def _p(ev: dict, model=model) -> None:
            nonlocal last_pct
            if progress:
                progress(model, ev)
            total, done = ev.get("total"), ev.get("completed")
            if total and done:
                pct = int(done * 100 / total)
                if pct >= last_pct + 10:
                    last_pct = pct
                    log.info("  %s %s %d%%", model, ev.get("status", ""), pct)
        try:
            await rt.llm.pull(model, _p)
            result["pulled"].append(model)
        except Exception as e:  # keep going with the rest
            log.warning("pull %s failed: %s", model, e)
            result["failed"][model] = str(e)
    result["ok"] = not result["failed"]
    result["missing"] = list(result["failed"])
    rt.db.kv_set("models:status", {**result, "ts": time.time()})
    if result["pulled"]:
        await rt.notifier.send("Models downloaded", ", ".join(result["pulled"]), tags=["inbox_tray"])
    return result

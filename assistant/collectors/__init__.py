"""Data collectors. Each pulls one source into the `events` table.

Enable them in settings.yaml under collectors.enabled. Anything without an API
(LinkedIn export, bank CSV, Half Full export, phone usage, Wispr Flow) can be dropped
into ``<data_dir>/inbox/<source>/`` as CSV/JSON/JSONL, or POSTed to /ingest/<source>.
"""

from __future__ import annotations

import logging
import time
import traceback
from typing import Awaitable, Callable

log = logging.getLogger(__name__)

Collector = Callable[..., Awaitable[int]]
REGISTRY: dict[str, Collector] = {}


def collector(name: str) -> Callable[[Collector], Collector]:
    def deco(fn: Collector) -> Collector:
        REGISTRY[name] = fn
        return fn
    return deco


def _load() -> None:
    from . import activitywatch, files, github, google  # noqa: F401


async def run_collectors(rt, names: list[str] | None = None) -> dict[str, int | str]:
    _load()
    names = names or rt.settings["collectors"].get("enabled", [])
    results: dict[str, int | str] = {}
    for name in names:
        fn = REGISTRY.get(name)
        if not fn:
            results[name] = "unknown collector"
            continue
        try:
            n = await fn(rt, rt.settings["collectors"].get(name, {}) or {})
            rt.db.kv_set(f"collector:{name}:last_ok", time.time())
            results[name] = n
        except Exception as e:  # one broken source must not stop the others
            log.warning("collector %s failed: %s", name, e)
            rt.db.kv_set(f"collector:{name}:last_error", {"ts": time.time(), "error": str(e),
                                                          "trace": traceback.format_exc()[-1500:]})
            results[name] = f"error: {e}"
    return results

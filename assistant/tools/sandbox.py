"""Shell access inside the M7 sandbox container.

The agents' playground: full bash, internet, Python, git. It runs in a Docker
container (`pa-sandbox`) so a bad command can't take out the assistant's own
database or the vault. Set sandbox.runner: local to run directly on M7 instead.
"""

from __future__ import annotations

import asyncio

from . import ToolContext, tool

MAX_OUT = 6000


async def run_in_sandbox(settings, command: str, timeout: int | None = None, workdir: str = "/work") -> dict:
    cfg = settings["sandbox"]
    timeout = timeout or int(cfg.get("timeout_seconds", 120))
    if cfg.get("runner", "docker") == "docker":
        argv = ["docker", "exec", "-w", workdir, cfg.get("container", "pa-sandbox"), "bash", "-lc", command]
    else:
        argv = ["bash", "-lc", command]
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"exit_code": None, "output": f"timed out after {timeout}s"}
    text = out.decode(errors="replace")
    if len(text) > MAX_OUT:
        text = text[:2000] + f"\n...[{len(text) - 4000} chars cut]...\n" + text[-2000:]
    return {"exit_code": proc.returncode, "output": text}


@tool(
    "Run a bash command in your sandbox Linux machine (internet, python, git available). "
    "Use for calculations, scripts, downloads, data wrangling.",
    command={"type": "string"},
)
async def sandbox_shell(ctx: ToolContext, command: str) -> dict:
    return await run_in_sandbox(ctx.rt.settings, command)

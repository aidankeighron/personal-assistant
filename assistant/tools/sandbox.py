"""Shell access for the agents.

runner: docker (default, M7) -- bash inside the `pa-sandbox` container. A bad command can't
        touch the assistant's database or the rest of the machine.
runner: local  -- bash directly on this machine, in <data_dir>/sandbox-work. For testing on a
        single PC (e.g. Windows, using Git for Windows' bash). NOT sandboxed.
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import ToolContext, tool

MAX_OUT = 6000
IS_WINDOWS = sys.platform == "win32"
GIT_BASH = [r"C:\Program Files\Git\bin\bash.exe", r"C:\Program Files (x86)\Git\bin\bash.exe"]


def find_bash() -> str | None:
    """Git Bash first on Windows (System32\\bash.exe is the WSL launcher, which may not be set up)."""
    if IS_WINDOWS:
        for p in GIT_BASH + [os.path.expandvars(r"%LOCALAPPDATA%\Programs\Git\bin\bash.exe")]:
            if Path(p).exists():
                return p
    return shutil.which("bash")


def kill_tree(proc: asyncio.subprocess.Process) -> None:
    """Kill the shell *and* everything it started."""
    try:
        if IS_WINDOWS:
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15)
        else:
            os.killpg(proc.pid, 9)   # started in its own session, so this is the whole group
    except (OSError, subprocess.SubprocessError):
        proc.kill()


def _shorten(text: str) -> str:
    if len(text) > MAX_OUT:
        return text[:2000] + f"\n...[{len(text) - 4000} chars cut]...\n" + text[-2000:]
    return text


async def run_in_sandbox(settings, command: str, timeout: int | None = None, workdir: str = "/work") -> dict:
    cfg = settings["sandbox"]
    timeout = timeout or int(cfg.get("timeout_seconds", 120))
    kwargs: dict = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.STDOUT}
    docker = cfg.get("runner", "docker") == "docker"
    if docker:
        # `timeout` runs *inside* the (Linux) container so a runaway command is really killed,
        # not just the docker client.
        argv = ["docker", "exec", "-w", workdir, cfg.get("container", "pa-sandbox"),
                "timeout", "-k", "5", str(timeout), "bash", "-lc", command]
    else:
        bash = find_bash()
        if not bash:
            return {"exit_code": None, "output": "no bash found. On Windows install Git for Windows, "
                    "or set sandbox.runner: docker (with Docker Desktop)."}
        argv = [bash, "-lc", command]
        work = settings.data_dir / "sandbox-work"
        work.mkdir(parents=True, exist_ok=True)
        kwargs["cwd"] = str(work)
        if not IS_WINDOWS:
            kwargs["start_new_session"] = True   # lets kill_tree take out the whole process group
    proc = await asyncio.create_subprocess_exec(*argv, **kwargs)
    limit = timeout + 15 if docker else timeout
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=limit)
    except asyncio.TimeoutError:
        kill_tree(proc)
        try:
            await asyncio.wait_for(proc.wait(), timeout=10)
        except asyncio.TimeoutError:
            pass
        return {"exit_code": None, "output": f"timed out after {timeout}s"}
    text = out.decode("utf-8", errors="replace")
    if docker and proc.returncode in (124, 137):
        return {"exit_code": None, "output": f"timed out after {timeout}s\n" + text[-2000:]}
    return {"exit_code": proc.returncode, "output": _shorten(text)}


@tool(
    "Run a bash command in your sandbox machine (internet, python, git available). "
    "Use for calculations, scripts, downloads, data wrangling.",
    command={"type": "string"},
)
async def sandbox_shell(ctx: ToolContext, command: str) -> dict:
    return await run_in_sandbox(ctx.rt.settings, command)

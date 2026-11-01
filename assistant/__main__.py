"""CLI: python -m assistant <command>

  serve                 run the API + scheduler (what systemd runs)
  chat                  interactive text chat in the terminal
  say "hey jarvis ..."  one message, print the reply
  nightly               run Mother's nightly pipeline now
  collect [names...]    run collectors now
  audit                 run Skynet audit now
  brief                 rebuild the morning brief now
  report NAME           generate a report now
  project NAME [--git URL] [--path DIR] [--description TEXT]   register a Jarvis project
  backup                snapshot the database now
  models [--pull] [--force]   show which Ollama models the agents need; --pull downloads missing ones onto the PC
  doctor                check connectivity to PC (Ollama + host agent), notifications, docker
  auth-google           one-time Google OAuth (run on a machine with a browser)
  init [--local [--docker]]   create config/settings.yaml + .env (--local: everything on one PC, for testing)
  pair-pc               same machine: copy tokens between .env and pc/config.yaml
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import secrets
import shutil
import sys

from .config import REPO_ROOT


def _rt():
    from .runtime import Runtime
    return Runtime.create()


# Single-machine test mode (e.g. everything on the Windows PC before M7 exists).
# Each (old, new) must match settings.example.yaml exactly; tests/test_local_mode.py guards this.
LOCAL_SETTINGS = [
    ("data_dir: /mnt/vault/assistant ", "data_dir: ./data/assistant   # LOCAL TEST MODE (relative to the repo) "),
    ("  host: 0.0.0.0", "  host: 127.0.0.1                    # 0.0.0.0 to reach it from your phone over Tailscale"),
    ("  wake_pc_for_nightly: true", "  wake_pc_for_nightly: false        # same machine: nothing to wake"),
    ("  projects_dir: /mnt/vault/projects", "  projects_dir: ./data/projects"),
    ("  claude_home: /mnt/vault/assistant/claude-home", "  claude_home: ./data/assistant/claude-home"),
]
LOCAL_RUNNERS = [
    ("  runner: docker                      # docker | local", "  runner: local                       # docker | local (local = Git Bash, NOT sandboxed)"),
    ("  runner: docker                      # docker (recommended) | local", "  runner: local                       # docker (recommended) | local (uses your installed claude)"),
]
LOCAL_ENV = [("ASSISTANT_PUBLIC_URL=http://m7:8000", "ASSISTANT_PUBLIC_URL=http://localhost:8000"),
             ("PC_HOST=desktop", "PC_HOST=localhost")]


def _apply(text: str, pairs: list[tuple[str, str]]) -> str:
    for old, new in pairs:
        if old not in text:
            raise ValueError(f"settings template changed; can't find {old!r}")
        text = text.replace(old, new, 1)
    return text


def local_settings_text(example: str, docker: bool = False) -> str:
    return _apply(example, LOCAL_SETTINGS + ([] if docker else LOCAL_RUNNERS))


def new_env_text(example: str, local: bool = False) -> str:
    text = example.replace("ASSISTANT_API_TOKEN=change-me", f"ASSISTANT_API_TOKEN={secrets.token_urlsafe(24)}")
    text = text.replace("PC_HOST_TOKEN=change-me", f"PC_HOST_TOKEN={secrets.token_urlsafe(24)}")
    text = text.replace("NTFY_TOPIC=", f"NTFY_TOPIC=pa-{secrets.token_hex(6)}")
    return _apply(text, LOCAL_ENV) if local else text


def cmd_init(args) -> None:
    local = getattr(args, "local", False)
    cfg = REPO_ROOT / "config" / "settings.yaml"
    if not cfg.exists():
        example = (REPO_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")
        cfg.write_text(local_settings_text(example, getattr(args, "docker", False)) if local else example,
                       encoding="utf-8")
        print(f"created {cfg}{' (local test mode: data in ./data, PC = localhost)' if local else ''}")
    else:
        print(f"kept existing {cfg}")
    env = REPO_ROOT / ".env"
    if not env.exists():
        env.write_text(new_env_text((REPO_ROOT / ".env.example").read_text(encoding="utf-8"), local), encoding="utf-8")
        print(f"created {env} (tokens generated)")
        if not local:
            print("  copy PC_HOST_TOKEN into pc/config.yaml on the PC (host_agent.token)")
    pc_cfg = REPO_ROOT / "pc" / "config.yaml"
    if local and pc_cfg.exists():
        cmd_pair_pc(args)
    try:
        _rt()
        print("database ready")
    except PermissionError as e:
        print(f"couldn't create the data dir ({e}). Edit data_dir in {cfg} (e.g. ./data for testing) and re-run.")


def _set_env_line(text: str, key: str, value: str) -> str:
    import re
    line = f"{key}={value}"
    if re.search(rf"^{key}=.*$", text, flags=re.M):
        return re.sub(rf"^{key}=.*$", lambda _: line, text, count=1, flags=re.M)
    return text.rstrip("\n") + f"\n{line}\n"


def pair_pc_texts(env_text: str, pc_text: str, server_url: str = "http://localhost:8000") -> tuple[str, str]:
    """Same machine: share tokens between the server's .env and pc/config.yaml. Comments are kept."""
    import re

    import yaml
    pc = yaml.safe_load(pc_text) or {}
    host_token = (pc.get("host_agent") or {}).get("token", "")
    api_token = next((ln.split("=", 1)[1].strip() for ln in env_text.splitlines()
                      if ln.startswith("ASSISTANT_API_TOKEN=")), "")
    if not host_token or host_token == "change-me" or not api_token:
        raise ValueError("need host_agent.token in pc/config.yaml (run pc\\install.ps1) and ASSISTANT_API_TOKEN in .env")
    env_text = _set_env_line(env_text, "PC_HOST_TOKEN", host_token)
    # the `server:` block in pc/config.yaml: url + api_token (first occurrences after `server:`)
    head, sep, rest = pc_text.partition("\nserver:")
    if not sep:
        raise ValueError("pc/config.yaml has no `server:` section")
    rest = re.sub(r"^(\s+url:\s*)\S+", lambda m: m.group(1) + server_url, rest, count=1, flags=re.M)
    rest = re.sub(r"^(\s+api_token:\s*)\S+", lambda m: m.group(1) + api_token, rest, count=1, flags=re.M)
    return env_text, head + sep + rest


def cmd_pair_pc(_args) -> None:
    env, pc_cfg = REPO_ROOT / ".env", REPO_ROOT / "pc" / "config.yaml"
    if not pc_cfg.exists():
        print(f"no {pc_cfg} yet: run pc\\install.ps1 first, then `python -m assistant pair-pc`")
        return
    port = load_settings_quiet()["server"]["port"]
    new_env, new_pc = pair_pc_texts(env.read_text(encoding="utf-8"), pc_cfg.read_text(encoding="utf-8"),
                                    f"http://localhost:{port}")
    env.write_text(new_env, encoding="utf-8")
    pc_cfg.write_text(new_pc, encoding="utf-8")
    print("paired: PC_HOST_TOKEN in .env <- pc/config.yaml host_agent.token; "
          "pc/config.yaml server.url/api_token <- this server. Restart the host agent + voice client.")


def load_settings_quiet():
    from .config import load_settings
    return load_settings()


def cmd_serve(args) -> None:
    import uvicorn

    from .api import create_app
    from .config import load_settings
    s = load_settings()
    uvicorn.run(create_app(), host=args.host or s["server"]["host"], port=args.port or s["server"]["port"],
                log_level="info")


async def _chat_loop() -> None:
    from .orchestrator import Orchestrator
    rt = _rt()
    orch = Orchestrator(rt)
    print("Talk to Rocky / Jarvis / Mother / Skynet (prefix with the name). Ctrl-D to exit.")

    async def show(ev: dict) -> None:
        if ev["type"] == "filler":
            print(f"  [{ev['agent']}] {ev['text']}")
        elif ev["type"] == "tool":
            print(f"  ...{ev['tool']}")

    while True:
        try:
            text = await asyncio.to_thread(input, "\nyou > ")
        except (EOFError, KeyboardInterrupt):
            print()
            return
        res = await orch.handle(text, "cli", "cli", on_event=show)
        print(f"{res['agent']} > {res['text']}   ({res['latency_ms']}ms)")


async def _say(text: str) -> None:
    from .orchestrator import Orchestrator
    res = await Orchestrator(_rt()).handle(text, "cli", "cli")
    print(json.dumps(res, indent=2, default=str))


async def _doctor() -> None:
    from .host import HostUnavailable
    from .llm import LLMUnavailable
    rt = _rt()
    s = rt.settings
    print(f"data_dir      {s.data_dir}")
    try:
        models = await rt.llm.models()
        print(f"ollama        OK  {s['pc']['ollama_url']}  models={models}")
        from .models import model_status
        st = await model_status(rt)
        for m in st["required"]:
            print(f"  model {m:<28} {'MISSING (python -m assistant models --pull)' if m in st['missing'] else 'OK'}")
    except LLMUnavailable as e:
        print(f"ollama        FAIL {e}")
    try:
        print(f"host agent    OK  {await rt.host.idle()}")
    except HostUnavailable as e:
        print(f"host agent    FAIL {e}")
    print(f"notify        {'topic ' + s['notify']['topic'] if rt.notifier.enabled else 'not configured'}")
    from .tools.sandbox import find_bash
    sb, jv = s["sandbox"].get("runner", "docker"), s["jarvis"].get("runner", "docker")
    docker_ok = bool(shutil.which("docker"))
    print(f"docker        {'found' if docker_ok else 'MISSING'}{'' if docker_ok or 'docker' not in (sb, jv) else '  <- needed: a runner is set to docker'}")
    if sb == "local":
        bash = find_bash()
        print(f"sandbox shell local (NOT sandboxed): {bash or 'NO BASH FOUND -> install Git for Windows'}")
    if jv == "local":
        claude = shutil.which("claude")
        print(f"jarvis claude local: {claude or 'NOT FOUND -> npm install -g @anthropic-ai/claude-code, then `claude` to log in'}")
    agents = s.agents()
    print(f"agents        {', '.join(agents)}")


async def _models(pull: bool, force: bool) -> None:
    from .models import ensure_models, model_status
    from .llm import LLMUnavailable
    rt = _rt()
    try:
        st = await model_status(rt)
    except LLMUnavailable as e:
        print(f"PC Ollama unreachable: {e}")
        return
    for m in st["required"]:
        print(f"  {'MISSING' if m in st['missing'] else 'ok     '} {m}")
    if not pull:
        if st["missing"]:
            print("run with --pull to download the missing models onto the PC")
        return
    state: dict = {}

    def show(model: str, ev: dict) -> None:
        total, done = ev.get("total"), ev.get("completed")
        line = f"  {model}: {ev.get('status', '')}"
        if total and done:
            line += f" {done / 2**30:.2f}/{total / 2**30:.2f} GB ({done * 100 // total}%)"
        if line != state.get("last"):
            print(line.ljust(90), end="\r", flush=True)
            state["last"] = line

    res = await ensure_models(rt, pull=True, force=force, progress=show)
    print()
    print(json.dumps(res, indent=2))


def main(argv: list[str] | None = None) -> None:
    for stream in (sys.stdout, sys.stderr):  # never crash printing an emoji to a cp1252 console/pipe on Windows
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    p = argparse.ArgumentParser(prog="assistant", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sub.add_parser("chat")
    sp = sub.add_parser("say")
    sp.add_argument("text", nargs="+")
    sub.add_parser("nightly")
    sp = sub.add_parser("collect")
    sp.add_argument("names", nargs="*")
    sub.add_parser("audit")
    sub.add_parser("brief")
    sp = sub.add_parser("report")
    sp.add_argument("name")
    sp = sub.add_parser("project")
    sp.add_argument("name")
    sp.add_argument("--git")
    sp.add_argument("--path")
    sp.add_argument("--description", default="")
    sub.add_parser("backup")
    sp = sub.add_parser("models")
    sp.add_argument("--pull", action="store_true")
    sp.add_argument("--force", action="store_true", help="pull even if a fullscreen app is running")
    sub.add_parser("doctor")
    sp = sub.add_parser("auth-google")
    sp.add_argument("--client-secret", default="client_secret.json")
    sp.add_argument("--out", default="token.json")
    sp = sub.add_parser("init")
    sp.add_argument("--local", action="store_true",
                    help="single-machine test mode: data in ./data, PC = localhost (e.g. all on Windows)")
    sp.add_argument("--docker", action="store_true", help="with --local: use Docker Desktop runners, not local ones")
    sub.add_parser("pair-pc")
    a = p.parse_args(argv)

    if a.cmd == "init":
        cmd_init(a)
    elif a.cmd == "pair-pc":
        cmd_pair_pc(a)
    elif a.cmd == "serve":
        cmd_serve(a)
    elif a.cmd == "chat":
        asyncio.run(_chat_loop())
    elif a.cmd == "say":
        asyncio.run(_say(" ".join(a.text)))
    elif a.cmd == "nightly":
        from .tasks import nightly
        print(json.dumps(asyncio.run(nightly(_rt())), indent=2, default=str))
    elif a.cmd == "collect":
        from .collectors import run_collectors
        print(json.dumps(asyncio.run(run_collectors(_rt(), a.names or None)), indent=2))
    elif a.cmd == "audit":
        from .agents.skynet import audit
        print(json.dumps(asyncio.run(audit(_rt())), indent=2))
    elif a.cmd == "brief":
        from .tasks import build_brief
        print(json.dumps(asyncio.run(build_brief(_rt())), indent=2, default=str))
    elif a.cmd == "report":
        from .reports import generate
        print(asyncio.run(generate(_rt(), a.name))["markdown"])
    elif a.cmd == "project":
        from .jarvis_runner import create_project
        print(create_project(_rt(), a.name, a.description, git_url=a.git, path=a.path))
    elif a.cmd == "backup":
        from .tasks import backup
        print(backup(_rt()))
    elif a.cmd == "models":
        asyncio.run(_models(a.pull, a.force))
    elif a.cmd == "doctor":
        asyncio.run(_doctor())
    elif a.cmd == "auth-google":
        from pathlib import Path

        from .collectors.google import authorize
        authorize(Path(a.client_secret), Path(a.out))
        print(f"wrote {a.out}; copy it to <data_dir>/google/token.json on M7")


if __name__ == "__main__":
    main(sys.argv[1:])

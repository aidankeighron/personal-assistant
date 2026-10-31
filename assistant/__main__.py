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
  doctor                check connectivity to PC (Ollama + host agent), notifications, docker
  auth-google           one-time Google OAuth (run on a machine with a browser)
  init                  create config/settings.yaml + .env from the examples
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


def cmd_init(_args) -> None:
    cfg = REPO_ROOT / "config" / "settings.yaml"
    if not cfg.exists():
        shutil.copy(REPO_ROOT / "config" / "settings.example.yaml", cfg)
        print(f"created {cfg}")
    env = REPO_ROOT / ".env"
    if not env.exists():
        text = (REPO_ROOT / ".env.example").read_text()
        text = text.replace("ASSISTANT_API_TOKEN=change-me", f"ASSISTANT_API_TOKEN={secrets.token_urlsafe(24)}")
        text = text.replace("PC_HOST_TOKEN=change-me", f"PC_HOST_TOKEN={secrets.token_urlsafe(24)}")
        text = text.replace("NTFY_TOPIC=", f"NTFY_TOPIC=pa-{secrets.token_hex(6)}")
        env.write_text(text)
        print(f"created {env} (tokens generated; copy PC_HOST_TOKEN into pc/config.yaml on the PC)")
    try:
        _rt()
        print("database ready")
    except PermissionError as e:
        print(f"couldn't create the data dir ({e}). Edit data_dir in {cfg} (e.g. ./data for testing) and re-run.")


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
            text = input("\nyou > ")
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
        for alias in ("fast", "router", "heavy"):
            m = s.model(alias)
            print(f"  model {alias:<6} {m:<20} {'OK' if m in models else 'MISSING -> ollama pull ' + m}")
    except LLMUnavailable as e:
        print(f"ollama        FAIL {e}")
    try:
        print(f"host agent    OK  {await rt.host.idle()}")
    except HostUnavailable as e:
        print(f"host agent    FAIL {e}")
    print(f"notify        {'topic ' + s['notify']['topic'] if rt.notifier.enabled else 'not configured'}")
    print(f"docker        {'found' if shutil.which('docker') else 'MISSING'}")
    print(f"claude (local) {'found' if shutil.which('claude') else 'not on PATH (fine if runner=docker)'}")
    agents = s.agents()
    print(f"agents        {', '.join(agents)}")


def main(argv: list[str] | None = None) -> None:
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
    sub.add_parser("doctor")
    sp = sub.add_parser("auth-google")
    sp.add_argument("--client-secret", default="client_secret.json")
    sp.add_argument("--out", default="token.json")
    sub.add_parser("init")
    a = p.parse_args(argv)

    if a.cmd == "init":
        cmd_init(a)
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
    elif a.cmd == "doctor":
        asyncio.run(_doctor())
    elif a.cmd == "auth-google":
        from pathlib import Path

        from .collectors.google import authorize
        authorize(Path(a.client_secret), Path(a.out))
        print(f"wrote {a.out}; copy it to <data_dir>/google/token.json on M7")


if __name__ == "__main__":
    main(sys.argv[1:])

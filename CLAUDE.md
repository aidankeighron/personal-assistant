# CLAUDE.md

This repo is a personal multi-agent assistant (Rocky, Jarvis, Mother, Skynet). Jarvis runs
Claude Code on this repo to extend the assistant itself, so keep this file accurate.

## Layout
- `assistant/`: M7 server package (Python 3.11+, FastAPI, SQLite). Entry: `python -m assistant`.
  - `orchestrator.py` routes every message → `agents/` (rocky, jarvis, mother, skynet, generic llm)
  - `tools/`: `@tool` functions agents can call (listed per agent in `config/agents/*.yaml`)
  - `collectors/`: `@collector` data sources → `events` table
  - `jarvis_runner.py`: Claude Code runs, approvals, status summaries
  - `tasks.py`: nightly pipeline, reminders, location, backup. `scheduler.py`: in-process schedule
  - `reports.py`: YAML-spec reports. `memory.py`: tiered facts. `db.py`: schema
  - `models.py`: which Ollama models are required; auto-pulls missing ones onto the PC
  - `web/`: phone/desktop app + projector HUD (single-file HTML, no build step)
- `pc/`: Windows-only scripts (host agent whitelist, voice client, TTS, `download_models.py`, installer). Standalone: must not import `assistant`.
- `config/`: settings example, agent YAMLs, default report specs.
- `deploy/m7/`, `sandbox/`: server install, systemd, Docker. `deploy/windows/start-server.ps1`: run the
  server on a Windows PC for testing.
- `docs/`: SETUP.md (walkthrough), ARCHITECTURE.md. `docs/design/`: original design notes.
- `README.html`: single-file visual guide (tabs). Keep it in sync with SETUP.md when setup steps change.
- `prototypes/rocky_harness.py`: standalone model latency harness.

## Commands
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q          # fake LLM/PC + tests/fake_ollama.py (real HTTP); no network needed
.venv/bin/python -m assistant chat     # needs config/settings.yaml (python -m assistant init)
```

## Rules
- Run the tests before committing. Add a test for new behaviour (see `tests/conftest.py` fakes).
- Tools must never raise into the agent loop; return `{"error": ...}` instead.
- Anything that touches the PC goes through `host.py` → `pc/host_agent.py` whitelist. Never add a
  generic shell/exec endpoint to the host agent.
- LLM-written SQL must go through `db.readonly_query`.
- Keep M7 light: no heavy deps (no torch, no vector DB servers) in `assistant/`.
- `assistant/` must also run on Windows (single-PC test mode, `init --local`): no POSIX-only calls
  without a fallback, always `encoding="utf-8"` for file I/O, no shell tools on the host (rsync,
  timeout...) except inside the Docker sandbox. CI runs the tests on Windows and Linux.
- Secrets come from `.env` via `${VAR}` in settings; never commit them.

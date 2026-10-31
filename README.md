# Personal Assistant: Rocky · Jarvis · Mother · Skynet

A local, multi-agent personal assistant. The **Windows PC** is the brain (Ollama on the
RTX 3070 Ti, speech on the CPU). The cheap **M7 server** is the body: it runs the agents,
stores all memory on the 5TB vault, collects data overnight, and is the agents' sandbox.

| Agent | Role | How it works |
|---|---|---|
| **Rocky** | Everyday, real-time voice | Fast local LLM + tools: weather, timers, PC display modes and apps, projector, fridge, notes |
| **Jarvis** | Coding | Manages **Claude Code** runs in a sandbox after you approve on your phone; reads you auto-updated status lines; can work on this repo itself |
| **Mother** | Data + reports | SQL over everything collected; nightly morning brief; reports you can reshape by asking |
| **Skynet** | Background audit | Leases, backups, disk, collector health, secret scanning, memory sanity (e.g. "you don't have a 3080") |

Models download themselves: M7 pulls whatever Ollama models the agents are configured for onto
the PC, and `pc/download_models.py` fetches the voices and Whisper.

**Start here → [docs/SETUP.md](docs/SETUP.md)** (step-by-step for the PC, M7 and phone).
How it fits together → [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Repo map
```
assistant/        M7 server (python -m assistant): agents, tools, collectors, scheduler, API, web app
pc/               Windows: host agent (whitelisted PC control), voice client, TTS, install.ps1
config/           settings.example.yaml, agents/*.yaml, reports/*.yaml
deploy/m7/        install.sh, systemd unit, docker-compose, update.sh
sandbox/          Docker image for the agents' shell + Jarvis's Claude Code runs
prototypes/       rocky_harness.py: measure model latency on your GPU
docs/             SETUP, ARCHITECTURE, design/ (original design notes)
tests/            pytest with a fake LLM + fake PC (no hardware needed)
```

## Try it on any machine (no PC/GPU needed)
```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]"
.venv/bin/python -m pytest -q
.venv/bin/python -m assistant init      # creates config/settings.yaml + .env
# set data_dir: ./data in config/settings.yaml, point pc.ollama_url at any Ollama, then:
.venv/bin/python -m assistant chat
```

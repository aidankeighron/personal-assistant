# Architecture

## Split of responsibilities

| Machine | Runs | Why |
|---|---|---|
| **Windows PC** (i9-14900K, RTX 3070 Ti 8 GB, 64 GB) | Ollama (GPU), Whisper STT + Piper TTS (CPU), ActivityWatch, `pc/host_agent.py`, `pc/voice_client.py` | Only the PC can run models. It never runs agent code and exposes only a whitelist. |
| **M7** (cheap box, 6–12 GB RAM, HDD, 5TB vault) | `assistant` service (API, agents, scheduler, collectors), SQLite on the vault, `pa-sandbox` + Jarvis containers | Cheap work: orchestration, I/O, cron, storage. The agents' sandbox. |
| **Phone** | `/app` web client, ntfy, OwnTracks | Remote access over Tailscale. |

## Request flow (voice)

```
mic → voice_client (energy VAD → faster-whisper small.en, CPU)
    → POST m7:8000/chat {stream:true}
        orchestrator: router picks agent ("hey jarvis" / sticky / Rocky default)
                      "remember…/from now on…" → facts (no LLM)
        agent: system prompt + domain-matched facts + history
               ↔ Ollama on PC (tool calls run on M7: weather, timers, host agent, SQL…)
    ← NDJSON: routed → filler → tool… → reply
voice_client speaks filler immediately (masks tool latency), then the reply in that agent's Piper voice
```

## Agents (`assistant/agents/`, configured in `config/agents/*.yaml`)

- **Rocky** (`kind: rocky`): LLM + tools loop, deterministic Eridian grammar filter, instant filler lines.
- **Jarvis** (`kind: jarvis`): *not* a chatbot. A small model classifies the request
  (list / status / build / new / cancel / approve), then Jarvis answers with templates filled
  from project state. Building = `jarvis_runner.request_run()`:
  approval push → lease → `claude -p … --output-format stream-json` in a container on a
  `jarvis/draft-*` branch → log streamed to `<project>/.jarvis/run-N.jsonl` → every 2 min the
  scheduler summarizes recent activity into `projects.status_text` (what Jarvis reads back) →
  final report `<project>/.jarvis/report-N.md` + push. Sessions resume per project.
- **Mother** (`kind: mother`): LLM with data tools (`describe_data`, read-only `query_data`,
  reports). Nightly pipeline in `tasks.nightly()`.
- **Skynet** (`kind: skynet`): rules, not vibes. Leases, approvals, disk, backups,
  collector health, failed runs, secret scan of Jarvis projects, memory audit (verifies hardware
  facts from `nvidia-smi`, quarantines contradictions like "RTX 3080", promotes facts repeated 3+ times).
- **New persona**: drop a YAML in `config/agents/` with `kind: llm`, a persona and a tool list;
  `POST /reload`. No code needed.

## Nightly pipeline (05:00, `tasks.nightly`)

1. Run all collectors (CPU only, M7).
2. Wake the PC (WOL) if Ollama is unreachable.
3. Wait for the GPU gate: night window, or user idle ≥10 min and nothing fullscreen.
4. Build the morning brief → `kv['brief']` (Rocky's `read_morning_brief`, `/hud`, `/brief`).
5. Extract candidate memories from yesterday's messages.
6. Generate the `nightly_reports`.
7. Skynet audit, DB backup, push "brief ready".

## Memory

`facts` table, four tiers: `verified` (telemetry) > `explicit` (you said it) > `candidate`
(extracted; needs repeats) > `quarantined` (never used). Only verified/explicit facts whose domain
matches the request are injected, with a rule forbidding mentioning facts gratuitously.

Everything collected lives in `events` (source, kind, ts, title, body, data JSON) with an FTS5 index.

## Dynamic reports

Specs in `<data_dir>/reports/*.yaml` (seeded from `config/reports/`). A spec is sections
(`sources`, `sql` with `:since`, or `data: fridge|jarvis|findings`) + standing `instructions`.
"For future reports…" → Mother's `update_report` appends an instruction or section; the old version
is kept in `reports/history/`.

## Security boundaries

- PC: firewall allows 11434/8090 from M7 only. The host agent has no shell endpoint, only named profiles and apps.
- M7 API: bearer token on everything except `/health`, `/app` (asks for the token), and
  approval links (their random token *is* the secret, single-use, 6 h expiry).
- Agents' shell (`sandbox_shell`) and Jarvis's Claude Code run in containers that see only their
  work folder (+ Claude login), not the assistant DB or the rest of the vault.
- Claude Code only starts after a phone approval (lease, default 20 min). Jarvis commits to
  `jarvis/draft-*`; merging to main is yours.

## Ports

| Port | Where | What |
|---|---|---|
| 8000 | M7 (tailscale0 only) | assistant API + `/app` + `/hud` |
| 11434 | PC (M7 only) | Ollama |
| 8090 | PC (M7 only) | host agent |
| 5600 | PC (localhost) | ActivityWatch |
| 8080 | M7 (optional) | self-hosted ntfy |

## Extending

| Want | Do |
|---|---|
| New tool | `@tool(...)` function in `assistant/tools/*.py`, add its name to an agent YAML |
| New data source | `@collector("name")` in `assistant/collectors/`, enable in settings, or just use the inbox / `/ingest` |
| New report | ask Mother, or add a YAML to `<data_dir>/reports/` |
| New scheduled job | add to `task_table()` in `scheduler.py` + an entry in `settings.schedule` |
| New PC capability | add a display profile / app in `pc/config.yaml` (or a new endpoint in `host_agent.py`, kept narrow) |
| New agent | YAML in `config/agents/` (`kind: llm`) |

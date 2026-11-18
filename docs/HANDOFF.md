# Handoff: project status for the next agent

**Read this first**, then `CLAUDE.md` (layout + rules) and, for the phone app, `mobile/CLAUDE.md`.
Last updated: 2026-11-18. Everything below is merged to `main`.

The owner is building a personal multi-agent assistant: **Rocky** (fast everyday voice), **Jarvis**
(coding via Claude Code), **Mother** (data, nightly brief, reports), **Skynet** (background audits).
Two machines: a **Windows PC** (i9-14900K, RTX 3070 Ti 8 GB, 64 GB RAM) does inference and voice;
a cheap **M7 server** (6-12 GB RAM, HDD boot drive, 5TB vault drive) runs everything else. The owner
uses **Android only**. M7 is **not set up yet**; the owner is testing everything on the Windows PC
first (`deploy/windows/start-server.ps1`).

---

## 1. What exists

| Area | Where | State |
|---|---|---|
| Server: API, router, 4 agents, 28 tools, scheduler, collectors, reports, memory | `assistant/` | Built; 77 Python tests; CI on Linux + Windows |
| Jarvis: Claude Code runs, phone approval lease, status lines, draft branches | `assistant/jarvis_runner.py` | Built; exercised through real Docker with a stubbed `claude` |
| Automatic model downloads (Ollama, Whisper, Piper) | `assistant/models.py`, `pc/download_models.py` | Built; tested against a fake Ollama HTTP server |
| Windows PC side: host-agent whitelist, voice client, TTS, installer | `pc/` | Built; Win32 parts never run on real Windows hardware |
| Single-PC test mode (server on Windows) | `init --local`, `pair-pc`, `deploy/windows/start-server.ps1` | Built; CI runs server + CLI on real Windows |
| M7 deploy: install script, systemd, Docker sandbox | `deploy/m7/`, `sandbox/` | Built; sandbox image + compose verified in Docker; install.sh never run on a real box |
| Phone/desktop web app + projector HUD | `assistant/web/` | Built; checked in Playwright |
| Android app "PA Tracker" (apps, websites, location every 5 min, charts, raw data, sync) | `mobile/` | Built; 14 Kotlin unit tests; CI builds a signed APK and runs an emulator smoke test; **never run on a real phone** |
| Visual guide | `README.html` | 6 tabs incl. data collection walkthroughs; keep in sync with `docs/SETUP.md` |
| CI | `.github/workflows/tests.yml` | Jobs: `test` (Ubuntu 3.11/3.12, Windows 3.12), `windows-local-mode`, `android`, `android-smoke`; nightly at 05:00 UTC |

The data model: everything collected is a row in `events` (source, kind, ts, title, body, data JSON).
Sources in use: `activitywatch`, `gmail`, `gcal`, `drive`, `github`, `notes`, `location`, `phone_usage`,
`phone_web`, plus any `inbox/<source>` / `/upload/<source>` / `/ingest/<source>` name (e.g. `finance`).

---

## 2. How things were verified (and what was not)

**Really exercised (not just mocks):**
- Python suite: 77 tests on Ubuntu (3.11, 3.12) and real Windows (3.12) in CI.
- Windows: `init --local`, CLI, server start, chat, upload, `/sources` on a real Windows runner.
- Docker: sandbox image builds; Jarvis's exact `docker run` (uid mapping, `--mount`, git identity,
  persisted Claude home, `--init`); `sandbox_shell` timeouts kill the process tree.
- Claude Code `stream-json` format parsed from real `claude -p` runs; prompt via stdin confirmed.
- Piper voice download + synthesis and faster-whisper transcription round trip (Linux).
- Real `pc/host_agent.py` driven from the server (whitelist, tokens, refusals).
- Android: `testReleaseUnitTest` + `assembleRelease` locally and in CI; APK signature/manifest checked;
  emulator (API 34) install + launch + 400 monkey events with no crash.

**Only with fakes:** LLM behaviour (`tests/conftest.py` FakeLLM, `tests/fake_ollama.py`), Google APIs,
GitHub API, ntfy delivery, Wake-on-LAN.

**Never tested (needs the owner's hardware):** a real 7B model's tool use; Win32 idle/fullscreen
detection, display switching, projector window, `pc/install.ps1`; microphone + speakers; `deploy/m7/install.sh`
on a real box; the Android app on a real phone (usage access, accessibility URL reading, background
location, sync over Tailscale).

**Owner's verification checklist** (expected result after each arrow):
1. `deploy\windows\start-server.ps1` → `doctor` shows `ollama OK`, models OK, agents listed; server starts.
2. `pc\install.ps1 -M7Ip 127.0.0.1` (admin), re-run `start-server.ps1` → `doctor` shows `host agent OK`.
3. `pc\.venv\Scripts\python.exe pc\voice_client.py --text`, type "hey rocky what time is it" → spoken answer.
4. "Rocky, movie mode" / "open Factorio" → profile/app runs; "open cmd" → refused with the allowed list.
5. "Jarvis, build me a hello-world CLI" → ntfy Approve push → after approving, "Jarvis, status update" reads progress.
6. "Mother, what data do you have?" → sources listed. "Skynet, run an audit" → findings or all clear.
7. Phone: install from the `mobile-latest` release, Settings → server `http://<pc-tailscale-name>:8000`
   (server `host: 0.0.0.0`), token, Test connection, fix every permission, Start collecting →
   after ~10 min `GET /sources` shows `phone_usage`, `phone_web`, `location`.

---

## 3. Decisions and interpretations (don't silently undo these)

- **Jarvis is not a chatbot**: a small model classifies intent; replies are templates filled from
  project state. Claude Code does the work in a container on `jarvis/draft-*` branches; it starts only
  after phone approval (20-min lease). `.jarvis/` logs are git-excluded; a failed branch switch aborts.
- **Skynet is rules**, not an LLM judge. Memory facts are tiered (verified/explicit/candidate/quarantined)
  and only injected when their topic matches the request.
- **Mother writes SQL** through `db.readonly_query` only. Reports are editable YAML specs in
  `<data_dir>/reports/` (seeded from `config/reports/`).
- **No vector DB** on M7 (weak box): SQLite FTS5 only. Embeddings were deliberately left out.
- **Push notifications use ntfy**, not FCM (FCM was in the original wish list; not implemented).
- **Phone app is not connected to the agents** ("for now", per the owner). Charts + raw data only.
- **"Midnight runs"** was interpreted as the nightly CI run (05:00 UTC = midnight EST, 1 AM during DST)
  that also publishes the APK; **"context repo"** as `mobile/CLAUDE.md` + root `CLAUDE.md` entries so
  Jarvis/Claude Code can work on the app. Confirm with the owner if that reading was wrong.
- The APK is signed with a **committed shared key** (`mobile/app/shared.keystore`, password `android`)
  so updates install over each other. Repo secrets `ANDROID_KEYSTORE_*` override it (see `mobile/README.md`).
- Local test mode is **not sandboxed** (Git Bash + the owner's own `claude`). `-WithDocker` uses containers.

---

## 4. Gotchas for agents working in the cloud container

- **Maven Central rate-limits this container (HTTP 429).** For local Android builds, a Gradle init
  script at `~/.gradle/init.d/central-mirror.gradle` puts Google's mirror
  (`https://maven-central.storage-download.googleapis.com/maven2/`) first. It is *local only*, not in
  the repo; recreate it in a fresh container. CI doesn't need it.
- **Android SDK** was installed to `/opt/android-sdk` (`platforms;android-35`, `build-tools;35.0.0`);
  `mobile/local.properties` (git-ignored) points there. A fresh container must reinstall.
- **Docker**: start the daemon with `dockerd &`. Building `sandbox/` here needs the agent proxy's CA
  added to a *scratch copy* of the Dockerfile (TLS interception); the real Dockerfile needs nothing.
- **Piping install scripts into a shell is blocked** in this environment (e.g. `curl ollama.com/install.sh | sh`);
  use the fake Ollama server instead of installing Ollama.
- **`.gitignore` gotcha** (already bit once): a bare `data/` rule ignored `mobile/.../data/` source files.
  The rule is now `/data/`. Comments in `.gitignore` must be on their own line.
- **CI concurrency cancels in-progress runs** on a new push to the same ref. Wait for a run before pushing
  if you need its result.
- **CI logs**: use the GitHub MCP tools (`actions_list`, `get_job_logs`), not `gh`.
- Running the real `claude` CLI costs the owner's usage; keep such checks tiny.
- `/mnt/vault` may exist as an empty leftover in old containers; tests no longer touch it.

---

## 5. Backlog (roughly in priority order)

1. **Owner hardware verification** (section 2). Fix whatever breaks first; most likely: display
   switch commands and app paths in `pc/config.yaml`, model choice (`prototypes/rocky_harness.py`),
   Wake-on-LAN, the Android accessibility "restricted settings" step.
2. **Phone app on a real device**: confirm usage sessions, address-bar view ids per browser
   (`WebAccessibilityService.BROWSERS`), 5-minute location cadence under Doze, sync over Tailscale.
3. **Places from phone location**: derive enter/leave of named places server-side from `location`
   points so the grocery prompt works without OwnTracks.
4. **Set up M7** with `deploy/m7/install.sh`; move `./data/assistant` to `/mnt/vault/assistant` if keeping test data.
5. **CI housekeeping**: GitHub warns that `actions/checkout@v4`, `setup-python@v5`, `setup-java@v4`,
   `setup-gradle@v4`, `upload/download-artifact@v4` target Node 20; bump to current majors.
6. **Hardening**: rootless Docker on M7, off-box `backup.target`, optional self-hosted ntfy.
7. **Not built yet** from the original wish list: FCM, Discord bot is written but untested
   (`assistant/discord_bot.py`), video input, LinkedIn/Half Full direct collectors (upload works today),
   connecting the phone app to the agents.

---

## 6. Quick commands

```bash
python -m venv .venv && .venv/bin/pip install -e ".[dev]" && .venv/bin/python -m pytest -q   # 77 tests
cd mobile && ./gradlew testReleaseUnitTest assembleRelease                                   # 14 tests + APK
```
Owner-side: `deploy\windows\start-server.ps1` (server on the PC), `pc\install.ps1 -M7Ip 127.0.0.1`,
then the phone app from the `mobile-latest` GitHub release.

## 7. History (commits on main)

| Commit | What |
|---|---|
| `21b567a` | Scaffold: server, PC agent, deploy, docs |
| `2546ebb` | Automatic model downloads; real Docker/Claude/Piper/Whisper checks; hardening |
| `688e8a2` | `README.html` visual guide; data-collection walkthroughs; export uploads |
| `ed09c8e` | Double-check pass: nightly timezone + WOL fixes, safer Jarvis branches |
| `0d68902`..`f212675` | Server runs on Windows (single-PC test mode); CI on Windows |
| `1663819`..`d450f08` | Android app, `/mobile/sync`, nightly CI build + release, emulator smoke test |

"""Single-machine / Windows test mode: config generation, token pairing, and the
platform-specific paths (no os.getuid, Windows paths, claude.cmd, Git Bash, no rsync)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import textwrap
import time

import pytest
import yaml

from assistant import jarvis_runner as jr
from assistant import tasks
from assistant.__main__ import local_settings_text, new_env_text, pair_pc_texts
from assistant.config import REPO_ROOT, Settings
from assistant.db import Database
from assistant.tools import sandbox

EXAMPLE = (REPO_ROOT / "config" / "settings.example.yaml").read_text(encoding="utf-8")


def _settings(text: str) -> Settings:
    from assistant.config import DEFAULTS, _expand, deep_merge
    return Settings(raw=_expand(deep_merge(DEFAULTS, yaml.safe_load(text))), config_dir=REPO_ROOT / "config")


def test_init_local_settings():
    s = _settings(local_settings_text(EXAMPLE))
    assert s.path(s["data_dir"]) == (REPO_ROOT / "data" / "assistant").resolve()   # relative to the repo, any cwd
    assert s.path(s["jarvis"]["projects_dir"]) == (REPO_ROOT / "data" / "projects").resolve()
    assert s["sandbox"]["runner"] == "local" and s["jarvis"]["runner"] == "local"
    assert s["server"]["host"] == "127.0.0.1" and s["gpu_gate"]["wake_pc_for_nightly"] is False
    d = _settings(local_settings_text(EXAMPLE, docker=True))
    assert d["sandbox"]["runner"] == "docker" and d["jarvis"]["runner"] == "docker"


def test_init_local_env():
    env = new_env_text((REPO_ROOT / ".env.example").read_text(encoding="utf-8"), local=True)
    assert "PC_HOST=localhost" in env and "ASSISTANT_PUBLIC_URL=http://localhost:8000" in env
    assert "change-me" not in env


def test_pair_pc_shares_tokens_and_keeps_comments():
    pc = (REPO_ROOT / "pc" / "config.example.yaml").read_text(encoding="utf-8").replace(
        "  token: change-me", "  token: HOSTTOK", 1)
    env = "ASSISTANT_API_TOKEN=APITOK\nPC_HOST=localhost\nPC_HOST_TOKEN=old\n"
    new_env, new_pc = pair_pc_texts(env, pc, "http://localhost:8000")
    assert "PC_HOST_TOKEN=HOSTTOK" in new_env and "PC_HOST_TOKEN=old" not in new_env
    cfg = yaml.safe_load(new_pc)
    assert cfg["server"] == {"url": "http://localhost:8000", "api_token": "APITOK"}
    assert cfg["host_agent"]["token"] == "HOSTTOK" and cfg["activitywatch_url"] == "http://localhost:5600"
    assert "# = ASSISTANT_API_TOKEN in M7's .env" in new_pc        # comments survive
    with pytest.raises(ValueError):
        pair_pc_texts(env, (REPO_ROOT / "pc" / "config.example.yaml").read_text(encoding="utf-8"))  # token unset


def test_readonly_sql_on_path_with_spaces(tmp_path):
    db = Database(tmp_path / "My Documents" / "assistant data" / "a.db")
    db.add_event("x", "y", 1.0, "hello")
    assert db.readonly_query("SELECT title FROM events") == [{"title": "hello"}]


@pytest.mark.parametrize("target,remote", [
    ("backup@desktop:/d/backups", True), ("nas:backups", True),
    ("C:\\backups", False), ("D:/assistant", False), ("\\\\nas\\backups", False),
    ("/mnt/usb/backups", False), ("./backups", False), ("~/backups", False),
])
def test_backup_target_kind(target, remote):
    assert tasks.is_remote_target(target) is remote


def test_backup_to_local_folder_without_rsync(rt, tmp_path):
    (rt.settings.data_dir / "notes").mkdir(parents=True, exist_ok=True)
    (rt.settings.data_dir / "notes" / "today.md").write_text("- hi\n", encoding="utf-8")
    rt.settings.raw["backup"]["target"] = str(tmp_path / "share")
    tasks.backup(rt)
    out = tmp_path / "share"
    assert list(out.glob("assistant-*.db")) and (out / "notes" / "today.md").exists()


def test_docker_command_on_windows(rt, monkeypatch):
    """Docker Desktop on Windows: no os.getuid, C:\\ paths must survive (no -v colon parsing)."""
    monkeypatch.delattr(os, "getuid", raising=False)
    rt.settings.raw["jarvis"]["runner"] = "docker"
    rt.settings.raw["jarvis"]["claude_home"] = str(rt.settings.data_dir / "claude-home")
    cmd = jr.build_command(rt, "C:\\Users\\aidan\\assistant\\data\\projects\\lap", "x", None, 1)
    assert "--user" not in cmd and "-v" not in cmd
    assert "type=bind,source=C:\\Users\\aidan\\assistant\\data\\projects\\lap,target=/work" in cmd


def test_local_runner_finds_claude_cmd(rt, monkeypatch):
    monkeypatch.setattr(jr.shutil, "which", lambda n: r"C:\Users\aidan\AppData\Roaming\npm\claude.cmd")
    rt.settings.raw["jarvis"]["runner"] = "local"
    cmd = jr.build_command(rt, rt.settings.projects_dir, "prompt", None, 1)
    assert cmd[:2] == [r"C:\Users\aidan\AppData\Roaming\npm\claude.cmd", "-p"] and "prompt" not in cmd


async def test_prompt_reaches_claude_intact_via_stdin(rt, tmp_path, monkeypatch):
    """Newlines, quotes, & and %VARS% would be mangled by cmd.exe as an argument; stdin is exact."""
    script = tmp_path / "echo_claude.py"
    script.write_text(textwrap.dedent('''
        import json, sys
        prompt = sys.stdin.read()
        print(json.dumps({"type": "system", "subtype": "init", "session_id": "s"}), flush=True)
        print(json.dumps({"type": "result", "result": prompt, "is_error": False, "session_id": "s"}), flush=True)
    '''), encoding="utf-8")
    monkeypatch.setattr(jr, "build_command", lambda rt, p, prompt, sid, rid: [sys.executable, str(script)])
    rt.settings.raw["jarvis"]["approval_required"] = False
    task = 'Add a "lap" table & keep 100% of\nrows; don\'t touch %PATH% or $HOME'
    res = await jr.request_run(rt, "stdin-test", task)
    for _ in range(200):
        run = rt.db.one("SELECT status, result FROM runs WHERE id=?", (res["run_id"],))
        if run["status"] in ("done", "failed"):
            break
        await asyncio.sleep(0.05)
    assert run["status"] == "done" and run["result"].endswith("TASK:\n" + task)


@pytest.mark.skipif(sys.platform == "win32", reason="uses pgrep")
async def test_local_sandbox_timeout_kills_children(rt):
    rt.settings.raw["sandbox"]["runner"] = "local"
    marker = f"{time.time() % 1000:.3f}"
    res = await sandbox.run_in_sandbox(rt.settings, f"sleep 3{marker} & sleep 3{marker}; echo never", timeout=1)
    assert res["exit_code"] is None and "timed out" in res["output"]
    await asyncio.sleep(0.3)
    left = subprocess.run(["pgrep", "-f", f"sleep 3{marker}"], capture_output=True, text=True).stdout.strip()
    assert left == "", "child processes survived the timeout"


async def test_local_sandbox_runs_and_reports_missing_bash(rt, monkeypatch):
    rt.settings.raw["sandbox"]["runner"] = "local"
    res = await sandbox.run_in_sandbox(rt.settings, "echo hi; pwd")
    assert res["exit_code"] == 0 and res["output"].startswith("hi") and "sandbox-work" in res["output"]
    monkeypatch.setattr(sandbox, "find_bash", lambda: None)
    res = await sandbox.run_in_sandbox(rt.settings, "echo hi")
    assert res["exit_code"] is None and "Git for Windows" in res["output"]

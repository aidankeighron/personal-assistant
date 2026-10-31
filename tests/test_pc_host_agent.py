"""The Windows host agent's whitelist logic (runs on Linux too; Win32 bits return defaults)."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PC = Path(__file__).resolve().parent.parent / "pc"


@pytest.fixture
def agent(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "host_agent: {token: secret}\n"
        "display_modes:\n  movie: {aliases: [bed tv], steps: [['true']]}\n"
        "apps:\n  factorio: {uri: 'steam://rungameid/427520'}\n"
    )
    monkeypatch.setenv("PC_CONFIG", str(cfg))
    monkeypatch.syspath_prepend(str(PC))
    sys.modules.pop("host_agent", None)
    mod = importlib.import_module("host_agent")
    yield TestClient(mod.app)
    sys.modules.pop("host_agent", None)


def test_host_agent_whitelist(agent):
    h = {"Authorization": "Bearer secret"}
    assert agent.get("/idle").status_code == 401
    assert agent.get("/idle", headers=h).json()["fullscreen"] is False
    assert agent.post("/display", json={"mode": "bed tv"}, headers=h).json()["mode"] == "movie"
    assert agent.post("/display", json={"mode": "nuke"}, headers=h).status_code == 404
    assert agent.post("/launch", json={"app": "Factorio"}, headers=h).json() == {"launched": "factorio"}
    assert agent.post("/launch", json={"app": "cmd.exe"}, headers=h).status_code == 404
    assert agent.post("/launch", json={"app": "  "}, headers=h).status_code == 404
    assert agent.get("/apps", headers=h).json() == {"apps": ["factorio"], "display_modes": ["movie"]}

"""PC scripts against a live M7 server (real uvicorn) and a fake local Ollama:
download_models.py asks M7 for the model list and pulls; voice_client streams a reply."""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from assistant.api import create_app
from assistant.llm import OllamaClient
from fake_ollama import FakeOllama

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pc"))
import download_models as dm  # noqa: E402
import voice_client as vc  # noqa: E402


@pytest.fixture
def live_m7(rt):
    with FakeOllama({"qwen2.5:7b", "qwen2.5:3b"}) as ollama:
        rt.llm = OllamaClient(ollama.url)
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_app(rt, start_scheduler=False), host="127.0.0.1",
                                               port=port, log_level="error"))
        t = threading.Thread(target=server.run, daemon=True)
        t.start()
        while not server.started:
            time.sleep(0.02)
        yield {"url": f"http://127.0.0.1:{port}", "token": "test-token", "rt": rt}
        server.should_exit = True
        t.join(timeout=5)


def test_piper_url():
    assert dm.piper_url("en_US-ryan-high", ".onnx") == \
        "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/ryan/high/en_US-ryan-high.onnx"
    assert dm.piper_url("en_US-libritts_r-medium", ".onnx.json").endswith(
        "/en/en_US/libritts_r/medium/en_US-libritts_r-medium.onnx.json")


def test_download_models_gets_list_from_m7_and_pulls(live_m7, tmp_path):
    live_m7["rt"].settings.raw["extra_models"] = ["llama3.1:8b"]
    cfg = {"server": {"url": live_m7["url"], "api_token": live_m7["token"]}}
    want, source = dm.required_ollama_models(cfg)
    assert source == "M7" and "llama3.1:8b" in want
    with FakeOllama({"qwen2.5:7b"}) as local:   # the PC's own Ollama
        res = dm.ensure_ollama(cfg, base=local.url)
        assert set(res["pulled"]) == {"qwen2.5:3b", "llama3.1:8b"} and not res["failed"]
        assert dm.ensure_ollama(cfg, base=local.url)["pulled"] == []   # idempotent


def test_download_models_falls_back_to_config():
    want, source = dm.required_ollama_models({"server": {"url": "http://127.0.0.1:9", "api_token": "x"},
                                              "ollama_models": ["phi3:mini"]})
    assert (want, source) == (["phi3:mini"], "config.yaml")


def test_voice_client_streams_reply(live_m7, capsys):
    c = vc.Client({"server": {"url": live_m7["url"], "api_token": live_m7["token"]}})
    reply = c.send("Hey Rocky, what time is it?", speak=False)
    assert reply["agent"] == "rocky" and reply["text"].startswith("It is")
    out = capsys.readouterr().out
    assert "...get_time" in out


@pytest.mark.parametrize("text,woke", [
    ("Hey Rocky, timer for ten minutes", True), ("jarvis status update", True),
    ("okay mother what's my screen time", True), ("I was talking to my mom", False),
    ("the rocky mountains are big", False),
])
def test_wake_words(text, woke):
    assert bool(vc.WAKE_RE.match(text)) == woke

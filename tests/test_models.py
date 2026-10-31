"""Automatic model downloads + the real Ollama HTTP client, against a fake Ollama server."""

from __future__ import annotations

import pytest

from assistant.llm import LLMUnavailable, OllamaClient
from assistant.models import ensure_models, normalize, required_models
from assistant.orchestrator import Orchestrator
from fake_ollama import FakeOllama


def test_required_models_cover_aliases_agents_and_extras(rt):
    rt.settings.raw["extra_models"] = ["llama3.1:8b"]
    req = required_models(rt.settings)
    assert {"qwen2.5:7b", "qwen2.5:3b", "llama3.1:8b"} <= set(req)
    assert normalize("nomic-embed-text") == "nomic-embed-text:latest"
    assert normalize("hf.co/user/model:Q4_K_M") == "hf.co/user/model:Q4_K_M"


async def test_ensure_models_pulls_missing(rt):
    with FakeOllama({"qwen2.5:7b"}) as fake:
        rt.llm = OllamaClient(fake.url)
        rt.settings.raw["extra_models"] = ["nomic-embed-text"]   # untagged -> :latest
        seen = []
        res = await ensure_models(rt, progress=lambda m, ev: seen.append((m, ev.get("status"))))
        assert res["ok"], res
        assert set(res["pulled"]) == {"qwen2.5:3b", "nomic-embed-text"}
        assert ("qwen2.5:3b", "success") in seen
        # second run: nothing to do
        res2 = await ensure_models(rt)
        assert res2["ok"] and not res2["missing"] and not res2.get("pulled")
        assert rt.notifier.sent[-1]["title"] == "Models downloaded"


async def test_ensure_models_reports_bad_names_and_keeps_going(rt):
    with FakeOllama(set()) as fake:
        rt.llm = OllamaClient(fake.url)
        rt.settings.raw["extra_models"] = ["does-not-exist:1b"]
        res = await ensure_models(rt)
        assert not res["ok"]
        assert "does-not-exist:1b" in res["failed"]
        assert "file does not exist" in res["failed"]["does-not-exist:1b"]
        assert {"qwen2.5:7b", "qwen2.5:3b"} <= set(res["pulled"])


async def test_ensure_models_defers_while_gaming(rt):
    rt.host.idle_info = {"idle_seconds": 0, "fullscreen": True, "foreground": "Assetto Corsa"}
    with FakeOllama(set()) as fake:
        rt.llm = OllamaClient(fake.url)
        res = await ensure_models(rt)
        assert "deferred" in res and not fake.app.state.pulls
        res = await ensure_models(rt, force=True)
        assert res["ok"]


async def test_ensure_models_pc_offline(rt):
    rt.llm = OllamaClient("http://127.0.0.1:9")
    res = await ensure_models(rt)
    assert res == {"ok": False, "reason": res["reason"]} and "offline" in res["reason"]


async def test_real_client_tool_loop_over_http(rt):
    """Rocky's full tool-calling loop through the real OllamaClient."""
    with FakeOllama({"qwen2.5:7b", "qwen2.5:3b"}) as fake:
        rt.llm = OllamaClient(fake.url)
        res = await Orchestrator(rt).handle("hey rocky what time is it", "http")
        assert res["agent"] == "rocky"
        assert res["text"].startswith("It is ")
        assert res["data"]["tools"] == ["get_time"]
        first = fake.app.state.chats[0]
        assert first["keep_alive"] == "2m" and any(t["function"]["name"] == "get_time" for t in first["tools"])


async def test_missing_model_gives_clear_error(rt):
    with FakeOllama(set()) as fake:
        client = OllamaClient(fake.url)
        with pytest.raises(LLMUnavailable, match="ollama pull qwen2.5:7b"):
            await client.chat("qwen2.5:7b", [{"role": "user", "content": "hi"}])

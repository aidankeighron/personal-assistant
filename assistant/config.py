"""Settings + agent/report config loading.

Everything lives in YAML under ``config/`` so agents (and you) can edit behaviour
without touching code. ``${VAR}`` and ``${VAR:-default}`` are expanded from the
environment (and from a ``.env`` file next to the settings file).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_ENV_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def _expand(value: Any) -> Any:
    if isinstance(value, str):
        return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), value)
    if isinstance(value, dict):
        return {k: _expand(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_expand(v) for v in value]
    return value


def deep_merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = v
    return out


DEFAULTS: dict[str, Any] = {
    "data_dir": str(REPO_ROOT / "data"),
    "timezone": "America/Detroit",
    "server": {"host": "0.0.0.0", "port": 8000, "api_token": "", "public_url": "http://localhost:8000"},
    "pc": {
        "ollama_url": "http://localhost:11434",
        "host_agent_url": "http://localhost:8090",
        "host_agent_token": "",
        "mac_address": "",
        "broadcast": "255.255.255.255",
    },
    "models": {
        "fast": "qwen2.5:7b",
        "router": "qwen2.5:3b",
        "heavy": "qwen2.5:7b",
    },
    "gpu_gate": {"idle_seconds": 600, "night_window": "04:30-06:30", "wake_pc_for_nightly": True},
    "notify": {"backend": "ntfy", "ntfy_url": "https://ntfy.sh", "topic": "", "token": ""},
    "weather": {"default_city": "East Lansing"},
    "sandbox": {"runner": "docker", "container": "pa-sandbox", "timeout_seconds": 120},
    "jarvis": {
        "projects_dir": "",
        "runner": "docker",  # docker | local
        "docker_image": "pa-sandbox:latest",
        "approval_required": True,
        "lease_minutes": 20,
        "claude_args": ["--output-format", "stream-json", "--verbose", "--dangerously-skip-permissions"],
        "status_every_seconds": 120,
        "branch_prefix": "jarvis/draft-",
    },
    "groceries": {"store_keywords": ["kroger", "meijer", "aldi", "costco", "target", "walmart", "trader joe", "grocery"]},
    "collectors": {"enabled": ["activitywatch", "inbox", "notes"]},
    "schedule": [
        {"name": "collect", "every": "30m", "task": "collect"},
        {"name": "nightly", "daily": "05:00", "task": "nightly"},
        {"name": "skynet_audit", "every": "60m", "task": "skynet_audit"},
        {"name": "perishables", "daily": "18:00", "task": "perishables_reminder"},
        {"name": "jarvis_status", "every": "2m", "task": "jarvis_status"},
        {"name": "ensure_models", "every": "6h", "task": "ensure_models", "run_at_start": True},
    ],
    "extra_models": [],
    "backup": {"target": "", "keep": 14},
}


@dataclass
class AgentConfig:
    name: str
    display_name: str
    kind: str
    model: str = "fast"
    persona: str = ""
    tools: list[str] = field(default_factory=list)
    voice: str = ""
    options: dict[str, Any] = field(default_factory=dict)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class Settings:
    raw: dict[str, Any]
    config_dir: Path

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def path(self, value: str | os.PathLike) -> Path:
        """Settings paths: ~ expanded; relative paths (./data) are relative to the repo."""
        p = Path(value).expanduser()
        return p if p.is_absolute() else (REPO_ROOT / p).resolve()

    @property
    def data_dir(self) -> Path:
        p = self.path(self.raw["data_dir"])
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        return self.data_dir / "assistant.db"

    @property
    def projects_dir(self) -> Path:
        p = self.path(self.raw["jarvis"].get("projects_dir") or self.data_dir / "projects")
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def inbox_dir(self) -> Path:
        p = self.data_dir / "inbox"
        p.mkdir(parents=True, exist_ok=True)
        return p

    def model(self, alias: str) -> str:
        return self.raw["models"].get(alias, alias)

    def agents(self) -> dict[str, AgentConfig]:
        out: dict[str, AgentConfig] = {}
        for f in sorted((self.config_dir / "agents").glob("*.yaml")):
            d = _expand(yaml.safe_load(f.read_text(encoding="utf-8")) or {})
            name = d.get("name") or f.stem
            out[name] = AgentConfig(
                name=name,
                display_name=d.get("display_name", name.title()),
                kind=d.get("kind", name),
                model=d.get("model", "fast"),
                persona=d.get("persona", ""),
                tools=d.get("tools", []),
                voice=d.get("voice", ""),
                options=d.get("options", {}),
                raw=d,
            )
        return out

    @property
    def reports_dir(self) -> Path:
        return self.config_dir / "reports"


def load_settings(path: str | os.PathLike | None = None) -> Settings:
    """Load settings.yaml (or $ASSISTANT_CONFIG), merged over DEFAULTS."""
    path = Path(path or os.environ.get("ASSISTANT_CONFIG") or REPO_ROOT / "config" / "settings.yaml")
    config_dir = path.parent if path.parent.name == "config" or (path.parent / "agents").exists() else REPO_ROOT / "config"
    _load_dotenv(path.parent / ".env")
    _load_dotenv(REPO_ROOT / ".env")
    user = {}
    if path.exists():
        user = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    raw = _expand(deep_merge(DEFAULTS, user))
    return Settings(raw=raw, config_dir=config_dir)

"""Download every model the PC needs, automatically and idempotently.

  - Piper voices listed in config.yaml -> tts.voices (from huggingface.co/rhasspy/piper-voices)
  - the faster-whisper model in voice.whisper_model (cached by huggingface_hub)
  - Ollama models: asks M7 which models the agents need (GET /models), falls back to
    config.yaml -> ollama_models, then pulls missing ones into the local Ollama

install.ps1 runs this; voice_client.py calls ensure_voices() at startup; M7 also pulls
Ollama models on its own every few hours. Safe to re-run any time:

    python download_models.py                 # everything
    python download_models.py --only voices   # voices | whisper | ollama
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
import yaml

HERE = Path(__file__).parent
PIPER_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
DEFAULT_OLLAMA = ["qwen2.5:7b", "qwen2.5:3b"]
OLLAMA_LOCAL = "http://localhost:11434"


def load_cfg() -> dict:
    p = HERE / "config.yaml"
    if not p.exists():
        p = HERE / "config.example.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) or {}


# ---------------------------------------------------------------------------
# Piper voices
# ---------------------------------------------------------------------------
def piper_url(stem: str, ext: str) -> str:
    """'en_US-ryan-high' -> .../en/en_US/ryan/high/en_US-ryan-high.onnx"""
    lang, rest = stem.split("-", 1)
    name, quality = rest.rsplit("-", 1)
    family = lang.split("_")[0]
    return f"{PIPER_BASE}/{family}/{lang}/{name}/{quality}/{stem}{ext}"


def _download(url: str, dest: Path, label: str) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with httpx.stream("GET", url, follow_redirects=True, timeout=httpx.Timeout(30, read=120)) as r:
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done, shown = 0, -1
        with tmp.open("wb") as f:
            for chunk in r.iter_bytes(1 << 16):
                f.write(chunk)
                done += len(chunk)
                pct = done * 100 // total if total else -1
                if pct != shown and pct % 5 == 0:
                    shown = pct
                    print(f"\r  {label}: {pct}% of {total / 2**20:.0f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def voice_paths(cfg: dict) -> list[Path]:
    out = []
    for v in (cfg.get("tts", {}).get("voices") or {}).values():
        if isinstance(v, dict) and v.get("model"):
            p = Path(v["model"])
            out.append(p if p.is_absolute() else HERE / p)
    return out


def ensure_voices(cfg: dict | None = None, quiet: bool = False) -> list[str]:
    cfg = cfg or load_cfg()
    fetched = []
    for onnx in voice_paths(cfg):
        stem = onnx.name.removesuffix(".onnx")
        for ext, path in ((".onnx.json", onnx.with_name(onnx.name + ".json")), (".onnx", onnx)):
            if path.exists() and path.stat().st_size > 0:
                continue
            try:
                url = piper_url(stem, ext)
            except ValueError:
                print(f"  can't derive a download URL for voice {stem!r}; put the files in {onnx.parent} manually")
                break
            _download(url, path, path.name)
            if ext == ".onnx.json":
                json.loads(path.read_text(encoding="utf-8"))  # sanity: got JSON, not an error page
            fetched.append(path.name)
    if not quiet:
        print(f"voices: {'downloaded ' + ', '.join(fetched) if fetched else 'all present'}")
    return fetched


# ---------------------------------------------------------------------------
# Whisper
# ---------------------------------------------------------------------------
def ensure_whisper(cfg: dict | None = None) -> str:
    cfg = cfg or load_cfg()
    name = cfg.get("voice", {}).get("whisper_model", "small.en")
    try:
        from faster_whisper import download_model
        path = download_model(name)
    except ImportError:
        from faster_whisper import WhisperModel  # older versions: constructing downloads it
        WhisperModel(name, device="cpu", compute_type="int8")
        path = name
    print(f"whisper: {name} ready ({path})")
    return str(path)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------
def required_ollama_models(cfg: dict) -> tuple[list[str], str]:
    s = cfg.get("server", {})
    if s.get("url") and s.get("api_token") and s.get("api_token") != "change-me":
        try:
            r = httpx.get(f"{s['url'].rstrip('/')}/models", headers={"Authorization": f"Bearer {s['api_token']}"},
                          timeout=8)
            r.raise_for_status()
            return list(r.json()["required"]), "M7"
        except (httpx.HTTPError, KeyError, ValueError) as e:
            print(f"  (couldn't ask M7 for the model list: {e}; using config.yaml)")
    return list(cfg.get("ollama_models") or DEFAULT_OLLAMA), "config.yaml"


def _norm(n: str) -> str:
    return n if ":" in n.split("/")[-1] else f"{n}:latest"


def ensure_ollama(cfg: dict | None = None, base: str = OLLAMA_LOCAL) -> dict:
    cfg = cfg or load_cfg()
    want, source = required_ollama_models(cfg)
    try:
        have = {_norm(m["name"]) for m in httpx.get(f"{base}/api/tags", timeout=5).json().get("models", [])}
    except httpx.HTTPError as e:
        print(f"ollama: not running at {base} ({e}). Start Ollama and re-run.")
        return {"error": str(e)}
    missing = [m for m in want if _norm(m) not in have]
    print(f"ollama: need {want} (from {source}); missing {missing or 'none'}")
    failed = {}
    for m in missing:
        try:
            with httpx.stream("POST", f"{base}/api/pull", json={"model": m, "stream": True},
                              timeout=httpx.Timeout(30, read=600)) as r:
                last, shown = {}, -1
                for line in r.iter_lines():
                    if not line.strip():
                        continue
                    ev = json.loads(line)
                    if ev.get("error"):
                        raise RuntimeError(ev["error"])
                    last = ev
                    if ev.get("total") and ev.get("completed"):
                        pct = ev["completed"] * 100 // ev["total"]
                        if pct != shown:
                            shown = pct
                            print(f"\r  {m}: {pct}% of {ev['total'] / 2**30:.1f} GB", end="", flush=True)
                print()
                if last.get("status") != "success":
                    raise RuntimeError(f"ended with {last}")
        except Exception as e:
            print(f"  {m}: FAILED {e}")
            failed[m] = str(e)
    return {"wanted": want, "pulled": [m for m in missing if m not in failed], "failed": failed}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", choices=["voices", "whisper", "ollama"])
    a = ap.parse_args(argv)
    cfg = load_cfg()
    ok = True
    for step, fn in (("voices", ensure_voices), ("whisper", ensure_whisper), ("ollama", ensure_ollama)):
        if a.only and a.only != step:
            continue
        try:
            res = fn(cfg)
            if isinstance(res, dict) and (res.get("failed") or res.get("error")):
                ok = False
        except Exception as e:  # report and keep going
            print(f"{step}: FAILED {e}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

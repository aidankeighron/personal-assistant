"""Windows host agent: the ONLY way M7 can affect your PC.

A small, token-protected HTTP server (port 8090) exposing a whitelist:
  GET  /idle           seconds since last input + fullscreen detection (GPU gate)
  GET  /stats          CPU / RAM / GPU (nvidia-smi)
  GET  /apps           what can be launched + display modes
  POST /display        run a configured display profile (movie / racing / desk / projector)
  POST /launch         launch a whitelisted app or game
  POST /close          close a whitelisted app
  POST /projector      open a URL fullscreen on the projector display (or close it)
  POST /speak          say something through the PC speakers (alarms, timers)
  GET  /activitywatch  relay ActivityWatch events (AW stays bound to localhost)

There is deliberately no "run arbitrary command" endpoint. Add capabilities by adding
entries to pc/config.yaml, not by widening this API.

Run:  python host_agent.py   (install.ps1 registers it to start at logon)
"""

from __future__ import annotations

import ctypes
import hmac
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import httpx
import uvicorn
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from pydantic import BaseModel

HERE = Path(__file__).parent
CFG_PATH = Path(os.environ.get("PC_CONFIG", HERE / "config.yaml"))
IS_WIN = sys.platform.startswith("win")


def load_cfg() -> dict:
    if not CFG_PATH.exists():
        raise SystemExit(f"missing {CFG_PATH}; copy config.example.yaml to config.yaml and edit it")
    return yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}


CFG = load_cfg()
app = FastAPI(title="PC host agent")
_projector_proc: subprocess.Popen | None = None


def auth(request: Request) -> None:
    token = CFG.get("host_agent", {}).get("token", "")
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(given, token):
        raise HTTPException(401, "bad token")


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------
class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long), ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_ulong), ("rcMonitor", RECT), ("rcWork", RECT), ("dwFlags", ctypes.c_ulong)]


def idle_seconds() -> float:
    if not IS_WIN:
        return 0.0
    lii = LASTINPUTINFO()
    lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
    return (ctypes.windll.kernel32.GetTickCount() - lii.dwTime) / 1000.0


def foreground() -> tuple[str, bool]:
    """(window title, is_fullscreen) for the foreground window."""
    if not IS_WIN:
        return "", False
    u = ctypes.windll.user32
    hwnd = u.GetForegroundWindow()
    if not hwnd:
        return "", False
    buf = ctypes.create_unicode_buffer(512)
    u.GetWindowTextW(hwnd, buf, 512)
    title = buf.value
    if title in ("", "Program Manager"):  # desktop
        return title, False
    r = RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    mon = u.MonitorFromWindow(hwnd, 2)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    u.GetMonitorInfoW(mon, ctypes.byref(mi))
    m = mi.rcMonitor
    full = r.left <= m.left and r.top <= m.top and r.right >= m.right and r.bottom >= m.bottom
    return title, bool(full)


def gpu_stats() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    try:
        out = subprocess.run(
            [exe, "--query-gpu=name,memory.used,memory.total,utilization.gpu,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5).stdout.strip()
        name, used, total, util, temp = [x.strip() for x in out.splitlines()[0].split(",")]
        return {"name": name, "vram_used_mb": int(used), "vram_total_mb": int(total),
                "util_pct": int(util), "temp_c": int(temp)}
    except Exception:
        return {}


def run_steps(steps: list) -> list[dict]:
    """Each step: list argv, a string (run via shell=False split), or {uri: ...}."""
    results = []
    for step in steps:
        if isinstance(step, dict) and step.get("uri"):
            if IS_WIN:
                os.startfile(step["uri"])  # type: ignore[attr-defined]
            results.append({"uri": step["uri"]})
            continue
        if isinstance(step, dict) and step.get("sleep"):
            time.sleep(float(step["sleep"]))
            continue
        argv = [str(a) for a in step] if isinstance(step, list) else str(step).split()
        p = subprocess.run(argv, capture_output=True, text=True, timeout=60)
        results.append({"cmd": argv[0], "code": p.returncode, "err": p.stderr[-300:]})
    return results


def find(entries: dict, name: str) -> tuple[str, Any] | None:
    key = name.lower().strip()
    if not key:
        return None
    for k, v in entries.items():
        aliases = [k.lower()] + [a.lower() for a in (v.get("aliases", []) if isinstance(v, dict) else [])]
        if key in aliases:
            return k, v
    for k, v in entries.items():  # fuzzy contains
        if key in k.lower() or k.lower() in key:
            return k, v
    return None


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------
class ModeIn(BaseModel):
    mode: str


class AppIn(BaseModel):
    app: str


class UrlIn(BaseModel):
    url: str | None = None


class SpeakIn(BaseModel):
    text: str
    agent: str = "rocky"


@app.get("/health")
def health() -> dict:
    return {"ok": True, "platform": sys.platform}


@app.get("/idle", dependencies=[Depends(auth)])
def idle() -> dict:
    title, full = foreground()
    ignore = [x.lower() for x in CFG.get("fullscreen_ignore", [])]
    if any(i in title.lower() for i in ignore):
        full = False
    return {"idle_seconds": round(idle_seconds(), 1), "fullscreen": full, "foreground": title}


@app.get("/stats", dependencies=[Depends(auth)])
def stats() -> dict:
    out: dict[str, Any] = {"gpu": gpu_stats()}
    try:
        import psutil
        vm = psutil.virtual_memory()
        out.update(cpu_pct=psutil.cpu_percent(interval=0.3), ram_used_gb=round(vm.used / 2**30, 1),
                   ram_total_gb=round(vm.total / 2**30, 1),
                   uptime_h=round((time.time() - psutil.boot_time()) / 3600, 1))
    except ImportError:
        pass
    return out


@app.get("/apps", dependencies=[Depends(auth)])
def apps() -> dict:
    return {"apps": sorted(CFG.get("apps", {})), "display_modes": sorted(CFG.get("display_modes", {}))}


@app.post("/display", dependencies=[Depends(auth)])
def display(body: ModeIn) -> dict:
    hit = find(CFG.get("display_modes", {}), body.mode)
    if not hit:
        raise HTTPException(404, f"unknown mode; have {sorted(CFG.get('display_modes', {}))}")
    name, spec = hit
    steps = spec.get("steps", []) if isinstance(spec, dict) else spec
    return {"mode": name, "results": run_steps(steps)}


@app.post("/launch", dependencies=[Depends(auth)])
def launch(body: AppIn) -> dict:
    hit = find(CFG.get("apps", {}), body.app)
    if not hit:
        raise HTTPException(404, f"not whitelisted; have {sorted(CFG.get('apps', {}))}")
    name, spec = hit
    if spec.get("uri"):
        if IS_WIN:
            os.startfile(spec["uri"])  # type: ignore[attr-defined]
    else:
        argv = spec["cmd"] if isinstance(spec["cmd"], list) else [spec["cmd"]]
        subprocess.Popen(argv, cwd=spec.get("cwd"), creationflags=0x00000008 if IS_WIN else 0)  # DETACHED
    return {"launched": name}


@app.post("/close", dependencies=[Depends(auth)])
def close(body: AppIn) -> dict:
    hit = find(CFG.get("apps", {}), body.app)
    if not hit or not hit[1].get("process"):
        raise HTTPException(404, "app not whitelisted or has no `process` name configured")
    name, spec = hit
    p = subprocess.run(["taskkill", "/IM", spec["process"]] if IS_WIN else ["pkill", "-f", spec["process"]],
                       capture_output=True, text=True)
    return {"closed": name, "code": p.returncode}


@app.post("/projector", dependencies=[Depends(auth)])
def projector(body: UrlIn) -> dict:
    global _projector_proc
    if _projector_proc and _projector_proc.poll() is None:
        _projector_proc.terminate()
        _projector_proc = None
    if not body.url:
        return {"projector": "off"}
    pcfg = CFG.get("projector", {})
    argv = [a.replace("{url}", body.url) for a in pcfg.get("browser_cmd", [])]
    if not argv:
        raise HTTPException(400, "projector.browser_cmd not configured")
    if pcfg.get("display_mode"):
        hit = find(CFG.get("display_modes", {}), pcfg["display_mode"])
        if hit:
            run_steps(hit[1].get("steps", []) if isinstance(hit[1], dict) else hit[1])
    _projector_proc = subprocess.Popen(argv)
    return {"projector": "on"}


_tts = None


@app.post("/speak", dependencies=[Depends(auth)])
def speak(body: SpeakIn) -> dict:
    global _tts
    from tts import TTS
    if _tts is None:
        _tts = TTS(CFG.get("tts", {}))
    threading.Thread(target=_tts.speak, args=(body.text, body.agent), daemon=True).start()
    return {"speaking": True}


@app.get("/activitywatch", dependencies=[Depends(auth)])
def activitywatch(since: str) -> dict:
    base = CFG.get("activitywatch_url", "http://localhost:5600").rstrip("/")
    out = []
    with httpx.Client(timeout=20) as c:
        buckets = c.get(f"{base}/api/0/buckets").json()
        for bid, b in buckets.items():
            t = b.get("type", "")
            kind = {"currentwindow": "window", "afkstatus": "afk", "web.tab.current": "web"}.get(t)
            if not kind:
                continue
            evs = c.get(f"{base}/api/0/buckets/{bid}/events", params={"start": since, "limit": 5000}).json()
            for e in evs:
                out.append({"bucket": bid, "kind": kind, "id": e.get("id"), "timestamp": e["timestamp"],
                            "duration": e.get("duration", 0), "data": e.get("data", {})})
    return {"events": out}


if __name__ == "__main__":
    h = CFG.get("host_agent", {})
    uvicorn.run(app, host=h.get("bind", "0.0.0.0"), port=int(h.get("port", 8090)), log_level="info")


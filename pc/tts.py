"""Text-to-speech for the PC (CPU only, leaves the GPU alone).

Backends:
  piper  - local neural voices (pip install piper-tts, download .onnx voices into pc/voices/)
  sapi   - built-in Windows voices via pyttsx3 (zero setup fallback)
"""

from __future__ import annotations

import io
import re
import subprocess
import sys
import tempfile
import threading
import wave
from pathlib import Path

HERE = Path(__file__).parent
_lock = threading.Lock()


def clean(text: str) -> str:
    text = re.sub(r"[♪♫*#`_>]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _play_wav_bytes(data: bytes) -> None:
    import numpy as np
    import sounddevice as sd

    with wave.open(io.BytesIO(data)) as w:
        frames = w.readframes(w.getnframes())
        audio = np.frombuffer(frames, dtype=np.int16)
        if w.getnchannels() > 1:
            audio = audio.reshape(-1, w.getnchannels())
        sd.play(audio, w.getframerate())
        sd.wait()


def chord(kind: str = "rocky", seconds: float = 0.35) -> None:
    """Little Eridian musical chord before Rocky talks."""
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError:
        return
    sr = 22050
    t = np.linspace(0, seconds, int(sr * seconds), False)
    freqs = {"rocky": [523.25, 659.25, 783.99], "skynet": [110, 116.5]}.get(kind, [440])
    wave_ = sum(np.sin(2 * np.pi * f * t) for f in freqs) / len(freqs)
    env = np.minimum(1, np.minimum(t / 0.03, (seconds - t) / 0.12))
    sd.play((wave_ * env * 0.25).astype(np.float32), sr)
    sd.wait()


class TTS:
    def __init__(self, cfg: dict):
        self.cfg = cfg or {}
        self.backend = self.cfg.get("backend", "piper")
        self.voices = self.cfg.get("voices", {})
        self._sapi = None

    def speak(self, text: str, agent: str = "rocky") -> None:
        text = clean(text)
        if not text:
            return
        voice = self.voices.get(agent) or self.voices.get("default") or {}
        with _lock:
            if voice.get("chord"):
                chord(agent)
            try:
                if self.backend == "piper" and voice.get("model"):
                    self._piper(text, voice)
                    return
            except Exception as e:  # fall back to SAPI rather than going silent
                print(f"[tts] piper failed ({e}); falling back to SAPI", file=sys.stderr)
            self._say_sapi(text, voice)

    def _piper(self, text: str, voice: dict) -> None:
        model = Path(voice["model"])
        if not model.is_absolute():
            model = HERE / model
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "out.wav"
            cmd = [sys.executable, "-m", "piper", "-m", str(model), "-f", str(out)]
            if voice.get("length_scale"):
                cmd += ["--length-scale", str(voice["length_scale"])]
            if voice.get("speaker") is not None:
                cmd += ["--speaker", str(voice["speaker"])]
            subprocess.run(cmd, input=text.encode("utf-8"), check=True, capture_output=True, timeout=60)
            _play_wav_bytes(out.read_bytes())

    def _say_sapi(self, text: str, voice: dict) -> None:
        try:
            import pyttsx3
        except ImportError:
            print(f"[tts] (no TTS installed) {text}")
            return
        if self._sapi is None:
            self._sapi = pyttsx3.init()
        e = self._sapi
        e.setProperty("rate", int(voice.get("sapi_rate", 185)))
        if voice.get("sapi_voice") is not None:
            voices = e.getProperty("voices")
            idx = int(voice["sapi_voice"])
            if 0 <= idx < len(voices):
                e.setProperty("voice", voices[idx].id)
        e.say(text)
        e.runAndWait()

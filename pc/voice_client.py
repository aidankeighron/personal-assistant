"""Desktop voice client: mic -> Whisper (CPU) -> M7 -> Piper voice.

Modes (pc/config.yaml -> voice.mode):
  wake  always listening; an utterance counts only if it starts with an agent name
        ("Hey Rocky ...", "Jarvis, status update"). Follow-ups within a few seconds
        of a reply don't need the name.
  ptt   press Enter in this console to talk (most private; zero false triggers)

Everything runs on the CPU (faster-whisper int8 on the i9) so the 3070 Ti stays free
for the LLM and your games.

Run:  python voice_client.py   [--ptt]  [--text]   (--text = type instead of talk; test TTS)
"""

from __future__ import annotations

import argparse
import json
import queue
import re
import sys
import time
from pathlib import Path

import httpx
import yaml

from tts import TTS

HERE = Path(__file__).parent
NAMES = {
    "rocky": ["rocky", "rockie", "rocki", "roxy", "raki"],
    "jarvis": ["jarvis", "jarvas", "jervis", "travis"],
    "mother": ["mother", "muthur", "mothers"],
    "skynet": ["skynet", "sky net", "skinet"],
}
WAKE_RE = re.compile(r"^\s*(?:(?:hey|hi|ok|okay|yo)[\s,]+)?(" +
                     "|".join(re.escape(n) for ns in NAMES.values() for n in ns) + r")\b", re.I)
SAMPLE_RATE = 16000
FRAME_MS = 30


def load_cfg() -> dict:
    p = HERE / "config.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


class Listener:
    """Energy-based utterance segmentation. Cheap, no extra models."""

    def __init__(self, cfg: dict):
        import sounddevice as sd  # noqa: F401  (fail early if missing)
        self.threshold = float(cfg.get("energy_threshold", 0.012))
        self.silence_ms = int(cfg.get("silence_ms", 800))
        self.max_seconds = float(cfg.get("max_utterance_seconds", 15))
        self.device = cfg.get("input_device")
        self.q: queue.Queue = queue.Queue()

    def _cb(self, indata, frames, t, status) -> None:
        self.q.put(indata.copy())

    def utterances(self):
        import numpy as np
        import sounddevice as sd
        frame = int(SAMPLE_RATE * FRAME_MS / 1000)
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32", blocksize=frame,
                            device=self.device, callback=self._cb):
            buf: list = []
            pre: list = []
            speaking = False
            silent_ms = 0
            while True:
                chunk = self.q.get()[:, 0]
                rms = float(np.sqrt(np.mean(chunk ** 2)))
                if not speaking:
                    pre = (pre + [chunk])[-10:]  # 300ms pre-roll so first word isn't clipped
                    if rms > self.threshold:
                        speaking, buf, silent_ms = True, list(pre), 0
                    continue
                buf.append(chunk)
                silent_ms = silent_ms + FRAME_MS if rms < self.threshold else 0
                dur = len(buf) * FRAME_MS / 1000
                if silent_ms >= self.silence_ms or dur >= self.max_seconds:
                    speaking = False
                    if dur > 0.5:
                        yield np.concatenate(buf)
                    with self.q.mutex:
                        self.q.queue.clear()

    def record_until_enter(self):
        import numpy as np
        import sounddevice as sd
        frames: list = []
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                            device=self.device, callback=lambda d, *_: frames.append(d.copy())):
            input("  recording... press Enter to stop ")
        return np.concatenate(frames)[:, 0] if frames else None


class STT:
    def __init__(self, cfg: dict):
        from faster_whisper import WhisperModel
        self.model = WhisperModel(cfg.get("whisper_model", "small.en"), device="cpu",
                                  compute_type="int8", cpu_threads=int(cfg.get("cpu_threads", 6)))

    def __call__(self, audio) -> str:
        segs, _ = self.model.transcribe(audio, language="en", beam_size=1, vad_filter=True,
                                        initial_prompt="Rocky, Jarvis, Mother, Skynet.")
        return " ".join(s.text for s in segs).strip()


class Client:
    def __init__(self, cfg: dict):
        s = cfg.get("server", {})
        self.url = s.get("url", "http://m7:8000").rstrip("/")
        self.token = s.get("api_token", "")
        self.tts = TTS(cfg.get("tts", {}))
        self.conversation = cfg.get("voice", {}).get("conversation", "desktop-voice")

    def send(self, text: str, speak: bool = True) -> dict | None:
        reply = None
        try:
            with httpx.Client(timeout=180) as c:
                with c.stream("POST", f"{self.url}/chat",
                              headers={"Authorization": f"Bearer {self.token}"},
                              json={"text": text, "conversation": self.conversation,
                                    "source": "voice", "stream": True}) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line.strip():
                            continue
                        ev = json.loads(line)
                        if ev["type"] == "filler":
                            print(f"  [{ev['agent']}] {ev['text']}")
                            if speak:
                                self.tts.speak(ev["text"], ev["agent"])
                        elif ev["type"] == "tool":
                            print(f"  ...{ev['tool']}")
                        elif ev["type"] == "reply":
                            reply = ev
                            print(f"{ev['agent']} > {ev['text']}")
                            if speak and ev.get("speak"):
                                self.tts.speak(ev["speak"], ev.get("voice") or ev["agent"])
                        elif ev["type"] == "error":
                            print(f"  error: {ev['error']}")
        except httpx.HTTPError as e:
            print(f"  can't reach M7 at {self.url}: {e}")
            if speak:
                self.tts.speak("I can't reach the server.", "rocky")
        return reply


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ptt", action="store_true", help="push-to-talk (Enter)")
    ap.add_argument("--text", action="store_true", help="type instead of talking")
    ap.add_argument("--mute", action="store_true", help="don't speak replies")
    a = ap.parse_args()
    cfg = load_cfg()
    vcfg = cfg.get("voice", {})
    if not a.mute and cfg.get("tts", {}).get("backend", "piper") == "piper":
        try:  # new voice added to config.yaml? fetch it now instead of falling back to SAPI
            from download_models import ensure_voices
            ensure_voices(cfg, quiet=True)
        except Exception as e:
            print(f"  (voice download skipped: {e})")
    client = Client(cfg)

    if a.text:
        while True:
            try:
                t = input("\nyou > ")
            except (EOFError, KeyboardInterrupt):
                return
            client.send(t, speak=not a.mute)

    print("loading whisper...")
    stt = STT(vcfg)
    listener = Listener(vcfg)
    mode = "ptt" if a.ptt else vcfg.get("mode", "wake")
    follow_s = float(vcfg.get("follow_up_seconds", 8))
    last_reply = 0.0
    print(f"ready ({mode} mode). Say 'Hey Rocky ...'" if mode == "wake" else "ready. Press Enter to talk.")

    if mode == "ptt":
        while True:
            input("\n[Enter] to talk ")
            audio = listener.record_until_enter()
            if audio is None:
                continue
            text = stt(audio)
            print(f"you > {text}")
            if text:
                client.send(text, speak=not a.mute)

    for audio in listener.utterances():
        t0 = time.time()
        text = stt(audio)
        if not text:
            continue
        woke = bool(WAKE_RE.match(text))
        if not woke and time.time() - last_reply > follow_s:
            continue  # background speech; ignore
        print(f"you > {text}   (stt {time.time() - t0:.1f}s)")
        if client.send(text, speak=not a.mute):
            last_reply = time.time()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)

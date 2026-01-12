from typing import AsyncGenerator
from pipecat.frames.frames import Frame, TTSAudioRawFrame, TTSStartedFrame, TTSStoppedFrame
from pipecat.services.tts_service import TTSService
import sys, subprocess, asyncio

class LocalPiperTTSService(TTSService):
    def __init__(self, *, piper_path: str, voice_path: str, device: str="cpu", sample_rate: int=22050, **kwargs):
        super().__init__(sample_rate=sample_rate, **kwargs)
        self._piper_path = piper_path
        self._voice_path = voice_path
        self._device = device
        self._sample_rate = sample_rate

    async def run_tts(self, text: str) -> AsyncGenerator[Frame, None]:
        yield TTSStartedFrame()

        cmd = [self._piper_path, "--model", self._voice_path, "--output_raw"]
        
        if self._device == "cuda":
            cmd.append("--use_cuda")

        process = await asyncio.create_subprocess_exec(*cmd, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=sys.stderr)
        out, _ = await process.communicate(input=text.encode("utf-8"))
        chunk_size = 4096 
        for i in range(0, len(out), chunk_size):
            chunk = out[i : i + chunk_size]
            if chunk:
                yield TTSAudioRawFrame(audio=chunk, sample_rate=self._sample_rate, num_channels=1)

        yield TTSStoppedFrame()
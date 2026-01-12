from pipecat.services.ai_services import TTSService
from pipecat.frames.frames import AudioRawFrame
import subprocess, asyncio

PIPER = "./tools/piper"
VOICE = "./tools/piper"

class LocalPiperTTSService(TTSService):
    def __init__(self, device="cpu", **kwargs):
        super().__init__(**kwargs)
        self._device = device

    async def run_tts(self, text: str):
        process = await asyncio.create_subprocess_exec(PIPER, "--model", VOICE, "--output-raw",
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)

        stdout, _ = await process.communicate(input=text.encode('utf-8'))
        yield AudioRawFrame(audio=stdout, sample_rate=22050, num_channels=1)
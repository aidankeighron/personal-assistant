import asyncio
import sys
import time
import subprocess
import urllib.request
import urllib.error
from loguru import logger

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext, OpenAILLMContextFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame, StartFrame
from tts import LocalPiperTTSService

HARDCODED_INPUT_ENABLED = False
HARDCODED_INPUT_TEXT = "How are you doing today?"

class SimpleContextAggregator(FrameProcessor):
    def __init__(self, context: OpenAILLMContext):
        super().__init__()
        self._context = context
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                print(f"You: {text}")
                self._context.add_message({"role": "user", "content": text})
                await self.push_frame(OpenAILLMContextFrame(self._context), direction)
        elif isinstance(frame, StartFrame) and HARDCODED_INPUT_ENABLED:
             # User requested hardcoded input so we hijack the start frame behavior slightly
             # But we MUST push the original StartFrame so downstream can initialize
             await self.push_frame(frame, direction)
             
             # Give the system a moment to initialize before sending
             await asyncio.sleep(1.0)
             text = HARDCODED_INPUT_TEXT
             print(f"You: {text}")
             self._context.add_message({"role": "user", "content": text})
             await self.push_frame(OpenAILLMContextFrame(self._context), direction)
        else:
            await self.push_frame(frame, direction)


class AssistantCollector(FrameProcessor):
    def __init__(self, context: OpenAILLMContext):
        super().__init__()
        self._context = context
        self._current_response = ""
        self._started = False
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        frame_name = type(frame).__name__
        
        if "LLMFullResponseStartFrame" in frame_name:
            self._started = True
            print("Jarvis: ", end="", flush=True)
        
        if isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            if self._started:
                self._current_response += frame.text
                print(frame.text, end="", flush=True)
        
        if "LLMFullResponseEndFrame" in frame_name:
            if self._current_response:
                print()
                self._context.add_message({"role": "assistant", "content": self._current_response})
                self._current_response = ""
            self._started = False
        
        await self.push_frame(frame, direction)

async def main():
    print("Loading voice assistant...")
    
    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.1, stop_secs=0.4, confidence=0.6, min_volume=0.03))
    
    transport = LocalAudioTransport(
        params=LocalAudioTransportParams(
            audio_in_enabled=not HARDCODED_INPUT_ENABLED,
            audio_out_enabled=True,
            audio_in_sample_rate=16000, 
            audio_out_sample_rate=16000, 
            vad_analyzer=vad, 
            audio_in_index=1, 
            audio_out_index=7
        )
    )
    
    stt = WhisperSTTService(model=Model.DISTIL_MEDIUM_EN, device="cpu", compute_type="int8")

    context = OpenAILLMContext(messages=[{
        "role": "system", 
        "content": "You are a helpful voice assistant named Jarvis. Keep answers concise."
    }])
    
    llm = OLLamaLLMService(model="hermes3:8b-llama3.1-q4_K_M", base_url="http://localhost:11434/v1")
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/piper/en_US-bryce-medium.onnx", volume=0.3)

    pipeline = Pipeline([
        transport.input(), 
        stt, 
        SimpleContextAggregator(context),
        llm,
        AssistantCollector(context),
        tts, 
        transport.output()
    ])
    
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("Voice Assistant Running... (Ctrl+C to exit)\n")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

def ensure_ollama_running():
    url = "http://localhost:11434/"
    try:
        urllib.request.urlopen(url)
        print("Ollama is already running.")
        return
    except (urllib.error.URLError, ConnectionRefusedError):
        print("Ollama is not running. Starting it...")
        try:
            # shell=True to effectively find 'ollama' in PATH
            subprocess.Popen(["ollama", "serve"], shell=True)
        except FileNotFoundError:
            print("Error: 'ollama' command not found. Please ensure Ollama is installed and in your PATH.")
            return

        print("Waiting for Ollama to become ready...", end="", flush=True)
        retries = 20
        while retries > 0:
            try:
                urllib.request.urlopen(url)
                print("\nOllama is ready!")
                return
            except (urllib.error.URLError, ConnectionRefusedError):
                time.sleep(1)
                print(".", end="", flush=True)
                retries -= 1
        
        print("\nWarning: Timed out waiting for Ollama to start. It may not be working correctly.")

if __name__ == "__main__":
    ensure_ollama_running()
    asyncio.run(main())
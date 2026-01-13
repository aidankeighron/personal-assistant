import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import TextFrame, TranscriptionFrame
from tts import LocalPiperTTSService

class TerminalLogger(FrameProcessor):
    def __init__(self, label: str):
        super().__init__()
        self._label = label

    async def process_frame(self, frame, direction):
        if isinstance(frame, TextFrame):
            print(f"[{self._label}]: {frame.text}")
        elif isinstance(frame, TranscriptionFrame):
            print(f"[{self._label}]: {frame.text}")
        await super().process_frame(frame, direction)

async def main():
    # Detect Voice
    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.1, stop_secs=0.4, confidence=0.6, min_volume=0.03))
    # Mic Input | Speaker Output
    transport = LocalAudioTransport(
        params=LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000, 
            audio_out_sample_rate=16000, 
            vad_analyzer=vad, 
            audio_in_index=1, 
            audio_out_index=7
        )
    )
    # Speech -> Text
    stt = WhisperSTTService(model=Model.DISTIL_MEDIUM_EN, device="cpu", compute_type="int8")

    # LLM with context handling
    messages = [{
        "role": "system", 
        "content": "You are a helpful voice assistant named Jarvis. Keep answers concise and witty."
    }]
    context = OpenAILLMContext(messages=messages)
    
    llm = OLLamaLLMService(model="hermes3:8b-llama3.1-q4_K_M", base_url="http://localhost:11434/v1")
    context_aggregator = llm.create_context_aggregator(context=context)
    
    # Text -> Audio
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/piper/en_US-bryce-medium.onnx")

    pipeline = Pipeline([
        transport.input(), 
        stt, 
        TerminalLogger("USER"),
        context_aggregator.user(),
        llm, 
        TerminalLogger("JARVIS"),
        tts, 
        context_aggregator.assistant(),
        transport.output()
    ])
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("Voice Assistant Running... (Ctrl+C to exit)")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
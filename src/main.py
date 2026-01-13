import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext, OpenAILLMContextFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame
from tts import LocalPiperTTSService

class SimpleContextAggregator(FrameProcessor):
    """Simple context aggregator that triggers LLM immediately when transcription arrives."""
    def __init__(self, context: OpenAILLMContext):
        super().__init__()
        self._context = context
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        # MUST call super first for proper frame handling
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                print(f"[USER]: {text}")
                self._context.add_message({"role": "user", "content": text})
                print(f"[DEBUG] Sending to LLM...")
                # Push context frame to trigger LLM
                await self.push_frame(OpenAILLMContextFrame(self._context), direction)
        else:
            # Forward all other frames
            await self.push_frame(frame, direction)

class AssistantCollector(FrameProcessor):
    """Collects assistant responses."""
    def __init__(self, context: OpenAILLMContext):
        super().__init__()
        self._context = context
        self._current_response = ""
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        frame_name = type(frame).__name__
        
        # Debug: show all frames from LLM
        if "LLM" in frame_name:
            print(f"[DEBUG] From LLM: {frame_name}")
        
        if isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            self._current_response += frame.text
            print(f"[JARVIS]: {frame.text}", end="", flush=True)
        
        if "LLMFullResponseEndFrame" in frame_name and self._current_response:
            print()
            self._context.add_message({"role": "assistant", "content": self._current_response})
            self._current_response = ""
        
        # Forward all frames
        await self.push_frame(frame, direction)

async def main():
    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.1, stop_secs=0.4, confidence=0.6, min_volume=0.03))
    
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
    
    stt = WhisperSTTService(model=Model.DISTIL_MEDIUM_EN, device="cpu", compute_type="int8")

    context = OpenAILLMContext(messages=[{
        "role": "system", 
        "content": "You are a helpful voice assistant named Jarvis. Keep answers concise and witty."
    }])
    
    llm = OLLamaLLMService(model="hermes3:8b-llama3.1-q4_K_M", base_url="http://localhost:11434/v1")
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/piper/en_US-bryce-medium.onnx")

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

if __name__ == "__main__":
    asyncio.run(main())
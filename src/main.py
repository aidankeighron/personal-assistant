import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.processors.aggregators.llm_response import LLMUserResponseAggregator
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from tts import LocalPiperTTSService

async def main():
    # Detect Voice
    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.2, stop_secs=0.8, confidence=0.5, min_volume=0.3))

    # Mic Input | Speaker Output
    transport = LocalAudioTransport(params=LocalAudioTransportParams(audio_in_sample_rate=16000, audio_out_sample_rate=22050, vad_analyzer=vad))
    
    # Speech -> Text
    stt = WhisperSTTService(model=Model.DISTIL_MEDIUM_EN, device="cpu", compute_type="int8")
    # Accumulate User Text
    context = LLMUserResponseAggregator()
    # TODO MCP
    # Text -> Tokens
    llm = OLLamaLLMService(model="hermes3:8b-q4_k_m", url="http://localhost:11434")
    # Tokens -> Audio
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/piper/en_US-bryce-medium.onnx")

    pipeline = Pipeline([transport.input(), stt, context, llm, tts, transport.output()])
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("Voice Assistant Running... (Ctrl+C to exit)")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
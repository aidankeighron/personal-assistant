import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner

from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.processors.aggregators.llm_response import LLMUserResponseAggregator
from pipecat.vad.silero import SileroVADAnalyzer
from piper_service import LocalPiperTTSService

async def main():
    # Mic Input | Speaker Output
    # Increase buffer size if choppy
    transport = LocalAudioTransport(params=LocalAudioTransportParams(sample_rate=16000, output_sample_rate=22050, buffer_size=1024))
    # Detect Voice
    vad = SileroVADAnalyzer()
    # Speech -> Text
    stt = WhisperSTTService(model=Model.DISTIL_MEDIUM_EN, device="cpu", compute_type="int8")
    # Accumulate User Text
    context = LLMUserResponseAggregator()
    # TODO MCP
    # Text -> Tokens
    llm = OLLamaLLMService(model="hermes3:8b-q4_k_m", url="http://localhost:11434")
    # Tokens -> Audio
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/piper/en_US-bryce-medium.onnx", device="cpu")

    pipeline = Pipeline([transport.input(), vad, stt, context, llm, tts, transport.output()])
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
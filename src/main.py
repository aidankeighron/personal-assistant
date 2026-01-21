from dotenv import load_dotenv
load_dotenv()
import asyncio

from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.observers.loggers.metrics_log_observer import MetricsLogObserver
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.llm_service import LLMContext
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.pipeline import Pipeline

from aggregators import UserAggregator, BotAggregator
from ollama import ensure_ollama_running, ensure_model_downloaded
from tts import LocalPiperTTSService
from loguru import logger
import sys
from functions import functions

logger.remove()
logger.add(sys.stderr, level="DEBUG", filter={"": "INFO", "pipecat.observers.loggers.metrics_log_observer": "DEBUG"})

VERBOSE = True
HARDCODE_INPUT = True
HARDCODED_INPUT_TEXT = "What is the current temperature Jarvis?"
MODEL_NAME = "qwen3:4b-instruct-2507-q4_K_M"

async def main():
    # SST
    # TODO https://docs.pipecat.ai/server/utilities/user-turn-strategies
    # TODO https://docs.pipecat.ai/server/utilities/smart-turn/smart-turn-overview
    vad = SileroVADAnalyzer(params=VADParams(
        start_secs=0.1,
        stop_secs=0.3,
        # confidence=0.6,
        # min_volume=0.03
    ))
    # TODO https://docs.pipecat.ai/guides/features/krisp-viva
    transport = LocalAudioTransport(params=LocalAudioTransportParams(
            audio_in_enabled=not HARDCODE_INPUT,
            audio_out_enabled=True,
            audio_in_sample_rate=16000, 
            audio_out_sample_rate=16000, 
            vad_analyzer=vad, 
            audio_in_index=1, 
            audio_out_index=7
    ))
    stt = WhisperSTTService(model=Model.SMALL, device="cpu", compute_type="int8")

    # LLM
    llm = OLLamaLLMService(model=MODEL_NAME, base_url="http://localhost:11434/v1")
    llm.register_function("search_internet", functions.execute_web_search, cancel_on_interruption=True)

    # Context
    tools = ToolsSchema(standard_tools=[functions.search_internet])
    system_prompt = open("./tools/system.txt").read()
    context = LLMContext(messages=[{
        "role": "system", 
        "content": system_prompt
    }], tools=tools)

    # TTS
    tts = LocalPiperTTSService(
        piper_path="./tools/piper/piper.exe", 
        voice_path="./tools/voices/jarvis-medium.onnx", 
        volume=0.3
    )

    pipeline = Pipeline([
        transport.input(), 
        stt,
        UserAggregator(context, hardcoded_text=HARDCODED_INPUT_TEXT if HARDCODE_INPUT else None),
        # TODO https://docs.pipecat.ai/guides/learn/function-calling
        llm,
        BotAggregator(context),
        tts, 
        transport.output(),
    ])
    task = PipelineTask(pipeline, params=PipelineParams(
        enable_metrics=VERBOSE,
        enable_usage_metrics=VERBOSE,
    ), observers=[MetricsLogObserver()])
    runner = PipelineRunner()

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

if __name__ == "__main__":
    ensure_ollama_running()
    ensure_model_downloaded(MODEL_NAME)
    asyncio.run(main())
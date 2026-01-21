from dotenv import load_dotenv
load_dotenv()
import asyncio

from pipecat.processors.aggregators.llm_response_universal import LLMContextAggregatorPair, LLMUserAggregatorParams
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.turn.smart_turn.local_smart_turn_v3 import LocalSmartTurnAnalyzerV3
from pipecat.turns.user_stop import TurnAnalyzerUserTurnStopStrategy
from pipecat.turns.user_turn_strategies import UserTurnStrategies
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.pipeline.task import PipelineTask, PipelineParams
from pipecat.adapters.schemas.tools_schema import ToolsSchema
from pipecat.services.ollama.llm import OLLamaLLMService
from pipecat.services.llm_service import LLMContext
from pipecat.pipeline.runner import PipelineRunner
from pipecat.pipeline.pipeline import Pipeline

from processors import WakeWordGate, ConsoleLogger, HardcodedInputInjector
from ollama import ensure_ollama_running, ensure_model_downloaded
from tts import LocalPiperTTSService
from loguru import logger
from functions import functions
from observer import MetricsLogger
import logging

logger.remove()
logging.getLogger("ollama").setLevel(logging.WARNING)
logging.getLogger("pipecat").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

VERBOSE = True
HARDCODE_INPUT = True
HARDCODED_INPUT_TEXT = "Jarvis What is the current weather, use the search_internet function"
MODEL_NAME = "qwen3:4b-instruct-2507-q4_K_M"

async def main():
    # SST
    vad = SileroVADAnalyzer(params=VADParams(
        start_secs=0.1,
        stop_secs=0.2,
    ))
    # TODO https://docs.pipecat.ai/guides/features/krisp-viva
    transport = LocalAudioTransport(params=LocalAudioTransportParams(
            audio_in_enabled=not HARDCODE_INPUT,
            audio_out_enabled=True,
            audio_in_sample_rate=16000, 
            audio_out_sample_rate=16000, 
            vad_analyzer=vad, 
            audio_in_index=1, 
            audio_out_index=7,
            allow_interruptions=False,
    ))
    stt = WhisperSTTService(model=Model.SMALL, device="cpu", compute_type="int8")

    # LLM
    llm = OLLamaLLMService(model=MODEL_NAME, base_url="http://localhost:11434/v1")
    llm.register_function("search_internet", functions.execute_web_search, cancel_on_interruption=True)
    llm.register_function("get_resource_usage", functions.monitor_resources, cancel_on_interruption=True)

    # Context
    tools = ToolsSchema(standard_tools=[functions.search_internet, functions.get_resource_usage])
    system_prompt = open("./tools/system.txt").read()
    function_prompt = open("./tools/functions.txt").read()
    full_system_prompt = f"{system_prompt}\n\n{function_prompt}"
    context = LLMContext(messages=[{
        "role": "system", 
        "content": full_system_prompt
    }], tools=tools)

    # TTS
    tts = LocalPiperTTSService(
        piper_path="./tools/piper/piper.exe", 
        voice_path="./tools/voices/jarvis-medium.onnx", 
        volume=0.3
    )

    # Smart Turn Aggregators
    # user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
    #     context,
    #     user_params=LLMUserAggregatorParams(
    #         user_turn_strategies=UserTurnStrategies(
    #             stop=[TurnAnalyzerUserTurnStopStrategy(
    #                 turn_analyzer=LocalSmartTurnAnalyzerV3()
    #             )]
    #         ),
    #     ),
    # )
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)
    
    # Custom Processors
    wake_word_gate = WakeWordGate(context=context)
    console_logger = ConsoleLogger()

    pipeline_steps = [transport.input()]
    if HARDCODE_INPUT:
        pipeline_steps.append(HardcodedInputInjector(HARDCODED_INPUT_TEXT))
    pipeline_steps.extend([
        stt,
        user_aggregator,
        wake_word_gate,
        llm,
        console_logger,
        tts, 
        assistant_aggregator,
        transport.output(),
    ])

    pipeline = Pipeline(pipeline_steps)
    
    task = PipelineTask(pipeline, params=PipelineParams(
        enable_metrics=VERBOSE,
        enable_usage_metrics=VERBOSE,
    ), observers=[MetricsLogger()])
    runner = PipelineRunner()

    print("Voice Assistant Running... Say 'Jarvis' to interact.")

    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()

if __name__ == "__main__":
    ensure_ollama_running()
    ensure_model_downloaded(MODEL_NAME)
    asyncio.run(main())
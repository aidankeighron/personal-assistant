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

from processors import WakeWordGate, ConsoleLogger, HardcodedInputInjector, MessageInjector
from ollama import ensure_ollama_running, ensure_model_downloaded, unload_model
from tts import LocalPiperTTSService
from loguru import logger
from functions import functions, basic, sandbox, files, google_ops, supabase_ops, alarm, website_blocker, scheduler
from observer import MetricsLogger, setup_logging
from config import get_config
import logging

logger.remove()
setup_logging()

# TODO text mode
# TODO command alias
# TODO connect to PostgresSQL
# TODO connect to HalfFull
# TODO get website usage data

VERBOSE = True
HARDCODE_INPUT = False
HARDCODED_INPUT_TEXT = "Jarvis What is the current weather, use the search_internet function"
MODEL_NAME = "qwen3:4b-instruct-2507-q4_K_M"

async def main():
    config = get_config()

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
    stt = WhisperSTTService(model=Model.SMALL, device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE_TYPE)

    # LLM
    llm = OLLamaLLMService(model=MODEL_NAME, base_url="http://localhost:11434/v1")
    llm.register_function("search_internet", functions.execute_web_search, cancel_on_interruption=True)
    llm.register_function("get_resource_usage", functions.monitor_resources, cancel_on_interruption=True)
    llm.register_function("get_current_time", basic.execute_get_current_time, cancel_on_interruption=True)
    llm.register_function("get_current_location", basic.execute_get_current_location, cancel_on_interruption=True)
    llm.register_function("get_current_date", basic.execute_get_current_date, cancel_on_interruption=True)
    llm.register_function("run_python_code", sandbox.execute_run_python_code, cancel_on_interruption=True)
    llm.register_function("read_file", files.execute_read_file, cancel_on_interruption=True)
    llm.register_function("write_file", files.execute_write_file, cancel_on_interruption=True)
    llm.register_function("append_to_memory", files.execute_append_to_memory, cancel_on_interruption=True)
    llm.register_function("list_files", files.execute_list_files, cancel_on_interruption=True)
    llm.register_function("get_recent_emails", google_ops.execute_get_recent_emails, cancel_on_interruption=True)
    llm.register_function("get_calendar_events", google_ops.execute_get_calendar_events, cancel_on_interruption=True)
    llm.register_function("get_habits", supabase_ops.execute_get_habits, cancel_on_interruption=True)
    llm.register_function("get_website_usage", supabase_ops.execute_get_website_usage, cancel_on_interruption=True)
    llm.register_function("schedule_alarm", alarm.execute_schedule_alarm, cancel_on_interruption=False)
    llm.register_function("block_websites", website_blocker.execute_block_websites, cancel_on_interruption=False)
    # llm.register_function("schedule_prompt", scheduler.execute_schedule_prompt, cancel_on_interruption=False)

    # Context
    tools = ToolsSchema(standard_tools=[
        functions.search_internet, 
        functions.get_resource_usage,
        basic.get_current_time,
        basic.get_current_location,
        basic.get_current_date,
        sandbox.run_python_code,
        files.read_file,
        files.write_file,
        files.append_to_memory,
        files.list_files,
        google_ops.get_recent_emails,
        google_ops.get_calendar_events,
        supabase_ops.get_habits_schema,
        supabase_ops.get_website_usage_schema,
        alarm.schedule_alarm_schema,
        website_blocker.block_websites_schema,
        # scheduler.schedule_prompt_schema,
    ])
    system_prompt = open("./tools/system.txt").read()
    # function_prompt = open("./tools/functions.txt").read()
    memory_content = open("./tools/memory.txt").read()
    
    full_system_prompt = f"{system_prompt}\n\nMEMORY:\n{memory_content}"
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
    if HARDCODE_INPUT:
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)
    else:
        user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
            context,
            user_params=LLMUserAggregatorParams(
                user_turn_strategies=UserTurnStrategies(
                    stop=[TurnAnalyzerUserTurnStopStrategy(
                        turn_analyzer=LocalSmartTurnAnalyzerV3()
                    )]
                ),
            ),
        )
    
    # Custom Processors
    wake_word_gate = WakeWordGate(context=context)
    message_injector = MessageInjector(context=context)
    scheduler.set_injector(message_injector)
    
    console_logger = ConsoleLogger()

    pipeline_steps = [transport.input()]
    if HARDCODE_INPUT:
        pipeline_steps.append(HardcodedInputInjector(HARDCODED_INPUT_TEXT))
    pipeline_steps.extend([
        stt,
        user_aggregator,
        wake_word_gate,
        # message_injector,
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
    ), observers=[MetricsLogger()], idle_timeout_secs=60*60)

    @task.event_handler("on_idle_timeout")
    async def on_idle_handler():
        print("WARNING: Pipeline finishing due to idle timeout.")
        logging.warning("Pipeline finishing due to idle timeout.")

    runner = PipelineRunner()

    print("Voice Assistant Running... Say 'Jarvis' to interact.")
    logging.info("Voice Assistant Running... Say 'Jarvis' to interact.")

    try:
        await runner.run(task)
        logging.info("Pipeline runner finished normally.")
    except KeyboardInterrupt:
        await task.cancel()
    except Exception as e:
        logger.exception(f"Unexpected error in main loop: {e}")
        await task.cancel()

if __name__ == "__main__":
    ensure_ollama_running()
    ensure_model_downloaded(MODEL_NAME)
    try:
        asyncio.run(main())
    finally:
        unload_model(MODEL_NAME)
        print("System shutdown complete.")
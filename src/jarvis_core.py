import asyncio
import logging
import sys
from loguru import logger
from dotenv import load_dotenv

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
from pipecat.frames.frames import TextFrame, TranscriptionFrame, EndFrame, StartFrame, UserStartedSpeakingFrame, UserStoppedSpeakingFrame
from pipecat.transports.base_transport import BaseTransport, TransportParams

from processors import WakeWordGate, ConsoleLogger, HardcodedInputInjector
from ollama import ensure_ollama_running, ensure_model_downloaded, unload_model
from tts import LocalPiperTTSService
from functions import functions, basic, sandbox, files, google_ops
from observer import MetricsLogger, setup_logging
from config import get_config

load_dotenv()

MODEL_NAME = "qwen3:4b-instruct-2507-q4_K_M"

class StdinTransport(BaseTransport):
    """Custom transport for reading from stdin in a non-blocking way (via thread)."""
    def __init__(self):
        super().__init__(params=TransportParams(audio_in_enabled=False, audio_out_enabled=False))
        self._stopped = False

    async def start(self, frame_handler):
        await super().start(frame_handler)
        asyncio.create_task(self._input_loop())

    async def _input_loop(self):
        print("Text Mode Ready. Type your message and press Enter.")
        while not self._stopped:
            try:
                # Run blocking input() in a separate thread
                text = await asyncio.to_thread(input, "User: ")
                if not text.strip():
                    continue
                
                # Signal start/stop for aggregators (simulates VAD)
                await self.push_frame(UserStartedSpeakingFrame())
                await self.push_frame(TranscriptionFrame(text=text, user_id="user", timestamp=0))
                await self.push_frame(UserStoppedSpeakingFrame())
                
            except EOFError:
                break
            except Exception as e:
                logging.error(f"Input error: {e}")
    
    async def stop(self):
        self._stopped = True
        await super().stop()

def setup_common_llm(context_msgs=None):
    """Sets up the LLM, Tools, and Context common to both modes."""
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
    ])
    
    system_prompt = open("./tools/system.txt").read()
    memory_content = open("./tools/memory.txt").read()
    
    full_system_prompt = f"{system_prompt}\n\nMEMORY:\n{memory_content}"
    
    messages = [{"role": "system", "content": full_system_prompt}]
    if context_msgs:
        messages.extend(context_msgs)

    context = LLMContext(messages=messages, tools=tools)
    return llm, context

async def run_voice_mode():
    """Original Voice Mode Logic"""
    logger.remove()
    setup_logging() # Default file logging
    
    config = get_config()
    
    # Initialize deps
    ensure_ollama_running()
    ensure_model_downloaded(MODEL_NAME)
    
    # Audio Services
    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.1, stop_secs=0.2))
    transport = LocalAudioTransport(params=LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000, 
            audio_out_sample_rate=16000, 
            vad_analyzer=vad, 
            audio_in_index=1, 
            audio_out_index=7,
            allow_interruptions=False,
    ))
    stt = WhisperSTTService(model=Model.SMALL, device=config.WHISPER_DEVICE, compute_type=config.WHISPER_COMPUTE_TYPE)
    tts = LocalPiperTTSService(piper_path="./tools/piper/piper.exe", voice_path="./tools/voices/jarvis-medium.onnx", volume=0.3)
    
    # Core LLM
    llm, context = setup_common_llm()
    
    # Smart Turn
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(
        context,
        user_params=LLMUserAggregatorParams(
            user_turn_strategies=UserTurnStrategies(
                stop=[TurnAnalyzerUserTurnStopStrategy(turn_analyzer=LocalSmartTurnAnalyzerV3())]
            ),
        ),
    )
    
    # Processors
    wake_word_gate = WakeWordGate(context=context)
    console_logger = ConsoleLogger()
    
    pipeline_steps = [
        transport.input(),
        stt,
        user_aggregator,
        wake_word_gate,
        llm,
        console_logger,
        tts, 
        assistant_aggregator,
        transport.output(),
    ]
    
    pipeline = Pipeline(pipeline_steps)
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=True, enable_usage_metrics=True), observers=[MetricsLogger()], idle_timeout_secs=60*60)
    
    print("Voice Assistant Running... Say 'Jarvis' to interact.")
    logging.info("Voice Assistant Running... Say 'Jarvis' to interact.")
    
    runner = PipelineRunner()
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()
    except Exception as e:
        logger.exception(f"Error: {e}")
    finally:
        unload_model(MODEL_NAME)
        print("System shutdown complete.")

async def run_text_mode():
    """New Text Mode Logic"""
    logger.remove()
    
    # Configure logging to be strictly file-based or silent for INFO, 
    # ensuring no extra prints to console.
    log_dir = "logs"
    import os
    if not os.path.exists(log_dir): os.makedirs(log_dir)
    
    # Force logging to file only, no console handler
    logging.basicConfig(
        filename=f'logs/text_mode_{import_datetime_setup()}.txt',
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        force=True
    )
    
    # Initialize deps
    ensure_ollama_running()
    ensure_model_downloaded(MODEL_NAME)
    
    print("Initializing Text Mode...")

    # Core LLM
    llm, context = setup_common_llm()
    
    # Transport (Stdin)
    transport = StdinTransport()
    
    # Aggregators (Simple, no smart turn needed for explicit text input)
    user_aggregator, assistant_aggregator = LLMContextAggregatorPair(context)
    
    # Processors
    # No wake word gate needed
    console_logger = ConsoleLogger() # Prints response
    
    pipeline_steps = [
        transport.input(),
        user_aggregator,
        # wake_word_gate, # Disabled for direct text interaction
        llm,
        console_logger,
        assistant_aggregator,
        # transport.output(), # ConsoleLogger handles output
    ]
    
    pipeline = Pipeline(pipeline_steps)
    task = PipelineTask(pipeline, params=PipelineParams(enable_metrics=False), idle_timeout_secs=60*60)
    
    runner = PipelineRunner()
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        await task.cancel()
    finally:
        unload_model(MODEL_NAME)
        print("System shutdown complete.")

def import_datetime_setup():
    from datetime import datetime
    return datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

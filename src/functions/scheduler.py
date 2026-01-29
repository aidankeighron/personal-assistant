import asyncio
import logging
from pipecat.services.llm_service import FunctionCallParams
from pipecat.adapters.schemas.function_schema import FunctionSchema

# Global injector instance
_injector = None

def set_injector(injector):
    global _injector
    _injector = injector

async def _wait_and_inject(delay_seconds: int, prompt: str):
    logging.info(f"Adding prompt to schedule in {delay_seconds} seconds: {prompt}")
    await asyncio.sleep(delay_seconds)
    if _injector:
        logging.info(f"Injecting scheduled prompt: {prompt}")
        _injector.schedule(prompt)
    else:
        logging.error("Injector not set. Cannot schedule prompt.")

async def execute_schedule_prompt(params: FunctionCallParams):
    prompt = params.arguments.get("prompt")
    delay = params.arguments.get("delay_seconds")
    
    if isinstance(delay, str):
        try:
            delay = int(delay)
        except ValueError:
            delay = 60 # Default to 1 minute
            
    # Add prefix if not present to ensure it's treated as a command
    # but MessageInjector injects as user role, so LLM sees "User: prompt"
    # The system prompt ensures it acts as Jarvis.
    
    asyncio.create_task(_wait_and_inject(delay, prompt))
    
    await params.result_callback(f"Scheduled prompt '{prompt}' in {delay} seconds.")

schedule_prompt_schema = FunctionSchema(
    name="schedule_prompt",
    description="Schedule a prompt to be sent to yourself in the future. Useful for reminders or periodic checks. The prompt will be processed as if the user said it.",
    properties={
        "prompt": {
            "type": "string",
            "description": "The text prompt to send to yourself.",
        },
        "delay_seconds": {
            "type": "integer",
            "description": "The delay in seconds before sending the prompt.",
        }
    },
    required=["prompt", "delay_seconds"]
)

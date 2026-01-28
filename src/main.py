import asyncio
import sys
from jarvis_core import run_voice_mode, run_text_mode

if __name__ == "__main__":
    # Simple dispatcher logic
    if len(sys.argv) > 1 and sys.argv[1].lower() == "text":
        asyncio.run(run_text_mode())
    else:
        # Default to voice or explicit 'voice' arg
        asyncio.run(run_voice_mode())
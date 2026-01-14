import asyncio

from pipecat.processors.aggregators.openai_llm_context import OpenAILLMContext, OpenAILLMContextFrame
from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame, StartFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection

class UserAggregator(FrameProcessor):
    def __init__(self, context: OpenAILLMContext, hardcoded_text=None):
        super().__init__()
        self._context = context
        self._hardcoded_text = hardcoded_text
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
            if text:
                print(f"You: {text}")
                self._context.add_message({"role": "user", "content": text})
                await self.push_frame(OpenAILLMContextFrame(self._context), direction)
        elif isinstance(frame, StartFrame) and self._hardcoded_text:
            await self.push_frame(frame, direction)
             
            # Give the system a moment to initialize before sending
            await asyncio.sleep(1.0)
            text = self._hardcoded_text
            print(f"You: {text}")
            self._context.add_message({"role": "user", "content": text})
            await self.push_frame(OpenAILLMContextFrame(self._context), direction)
        else:
            await self.push_frame(frame, direction)

class BotAggregator(FrameProcessor):
    def __init__(self, context: OpenAILLMContext):
        super().__init__()
        self._context = context
        self._current_response = ""
        self._started = False
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        frame_name = type(frame).__name__
        
        if "LLMFullResponseStartFrame" in frame_name:
            self._started = True
            print("Jarvis: ", end="", flush=True)
        if isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            if self._started:
                self._current_response += frame.text
                print(frame.text, end="", flush=True)
        if "LLMFullResponseEndFrame" in frame_name:
            if self._current_response:
                print()
                self._context.add_message({"role": "assistant", "content": self._current_response})
                self._current_response = ""
            self._started = False
        
        await self.push_frame(frame, direction)
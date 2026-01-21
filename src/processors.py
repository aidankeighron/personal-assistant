import asyncio
from pipecat.frames.frames import Frame, LLMContextFrame, TextFrame, TranscriptionFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame, StartFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.services.llm_service import LLMContext
from fuzzywuzzy import process, fuzz
import logging

class WakeWordGate(FrameProcessor):
    def __init__(self, context: LLMContext, wake_word: str="jarvis", threshold: int=91, min_length: int=4):
        super().__init__()
        self._context = context
        self._wake_word = wake_word
        self._threshold = threshold
        self._min_length = min_length

    def _should_respond(self, text: str) -> bool:
        filtered_words = [w.lower() for w in text.split() if len(w) > self._min_length]
        if not filtered_words:
            return False
        _, score = process.extractOne(self._wake_word, filtered_words, scorer=fuzz.ratio)
        return score >= self._threshold

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            # If last message was user
            if self._context.messages and self._context.messages[-1]["role"] == "user":
                last_user_message = self._context.messages[-1]["content"]
                if self._should_respond(last_user_message):
                    print(f"Wake word detected: {last_user_message}")
                else:
                    print(f"Ignored (no wake word): {last_user_message}")
                    return
        
        await self.push_frame(frame, direction)

class ConsoleLogger(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._started = False
        self._current_response = ""

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._started = True
            print("Jarvis: ", end="", flush=True)
        elif isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            if self._started:
                self._current_response += frame.text
                print(frame.text, end="", flush=True)
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._current_response:
                print()
                self._current_response = ""
            self._started = False

class HardcodedInputInjector(FrameProcessor):
    def __init__(self, text: str):
        super().__init__()
        self._text = text

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)
        if isinstance(frame, StartFrame):
            await asyncio.sleep(1.0)
            logging.info(f"Injecting hardcoded input: {self._text}")
            await self.push_frame(TranscriptionFrame(text=self._text, user_id="user", timestamp=0), direction)

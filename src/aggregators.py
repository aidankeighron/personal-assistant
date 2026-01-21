import asyncio

from pipecat.frames.frames import Frame, TextFrame, TranscriptionFrame, StartFrame, LLMContextFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.services.llm_service import LLMContext

from fuzzywuzzy import process, fuzz
from dataclasses import dataclass

@dataclass
class WordDetectionParams:
    target: str = "jarvis"
    threshold: int = 91
    min_length: int = 4

class UserAggregator(FrameProcessor):
    def __init__(self, context: LLMContext, hardcoded_text=None, word_detection_params: WordDetectionParams=WordDetectionParams):
        super().__init__()
        self._context = context
        self._hardcoded_text = hardcoded_text
        self._word_detection_params = word_detection_params

    def should_respond(self, text: str):
        filtered_words = [w.lower() for w in text.split() if len(w) > self._word_detection_params.min_length]
        _, score = process.extractOne(self._word_detection_params.target, filtered_words, scorer=fuzz.ratio)
        # TODO better
        return score >= self._word_detection_params.threshold
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        text = ""
        if isinstance(frame, TranscriptionFrame):
            text = frame.text.strip()
        elif isinstance(frame, StartFrame) and self._hardcoded_text:
            await self.push_frame(frame, direction)
             
            # Give the system a moment to initialize before sending
            await asyncio.sleep(1.0)
            text = self._hardcoded_text
        
        if text:
            print(f"You: {text}")
            self._context.add_message({"role": "user", "content": text})
        
        if text and self.should_respond(text):
            await self.push_frame(LLMContextFrame(self._context), direction)
        else:
            await self.push_frame(frame, direction)

class BotAggregator(FrameProcessor):
    def __init__(self, context: LLMContext):
        super().__init__()
        self._context = context
        self._current_response = ""
        self._started = False
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, LLMFullResponseStartFrame):
            self._started = True
            print("Jarvis: ", end="", flush=True)
        if isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            if self._started:
                self._current_response += frame.text
                print(frame.text, end="", flush=True)
        if isinstance(frame, LLMFullResponseEndFrame):
            if self._current_response:
                print()
                self._context.add_message({"role": "assistant", "content": self._current_response})
                self._current_response = ""
            self._started = False
        
        await self.push_frame(frame, direction)
import asyncio
from pipecat.frames.frames import Frame, LLMContextFrame, TextFrame, TranscriptionFrame, LLMFullResponseStartFrame, LLMFullResponseEndFrame, StartFrame, FunctionCallInProgressFrame, LLMMessagesAppendFrame
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.services.llm_service import LLMContext
from fuzzywuzzy import process, fuzz
import logging


class SystemInstructionRefresher(FrameProcessor):
    def __init__(self, instructional_anchor: str):
        super().__init__()
        self.anchor = instructional_anchor

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

            refresher_message = {
                "role": "system",
                "content": f"SYSTEM REMINDER: {self.anchor}"
            }
            await self.push_frame(LLMMessagesAppendFrame(messages=[refresher_message], run_llm=False), direction)
        
        await self.push_frame(frame, direction)

class WakeWordGate(FrameProcessor):
    def __init__(self, context: LLMContext, wake_word: str="jarvis", threshold: int=91, min_length: int=4, transcript_file: str=None):
        super().__init__()
        self._context = context
        self._wake_word = wake_word
        self._threshold = threshold
        self._min_length = min_length
        self._transcript_file = transcript_file

    def _should_respond(self, text: str) -> bool:
        filtered_words = [w.lower() for w in text.split() if len(w) > self._min_length]
        if not filtered_words:
            return False
        match, score = process.extractOne(self._wake_word, filtered_words, scorer=fuzz.ratio)
        logging.info(f"Word extracting: {match}:{score} {text}")
        return score >= self._threshold

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, LLMContextFrame):
            # If last message was user
            if self._context.messages and self._context.messages[-1]["role"] == "user":
                last_user_message = self._context.messages[-1]["content"]
                if self._should_respond(last_user_message):
                    print(f"User: {last_user_message}")
                    logging.info(f"User: {last_user_message}")
                    if self._transcript_file:
                        try:
                            with open(self._transcript_file, "a", encoding="utf-8") as f:
                                f.write(f"User: {last_user_message}\n")
                        except Exception as e:
                            logging.error(f"Failed to log to transcript: {e}")
                else:
                    print(last_user_message)
                    logging.info(f"Audio: {last_user_message}")
                    return
        
        await self.push_frame(frame, direction)

class ConsoleLogger(FrameProcessor):
    def __init__(self, transcript_file: str=None):
        super().__init__()
        self._started = False
        self._current_response = ""
        self._label_printed = False
        self._transcript_file = transcript_file

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        await self.push_frame(frame, direction)

        if isinstance(frame, LLMFullResponseStartFrame):
            self._started = True
        elif isinstance(frame, TextFrame) and not isinstance(frame, TranscriptionFrame):
            if self._started:
                # Only print the label if we haven't yet for this response, and we have actual text
                if not self._label_printed and frame.text.strip():
                     print("Jarvis: ", end="", flush=True)
                     self._label_printed = True
                self._current_response += frame.text
                print(frame.text, end="", flush=True)
        elif isinstance(frame, FunctionCallInProgressFrame):
            logging.info(f"Jarvis is calling function {frame.function_name} with arguments {frame.arguments}")
        elif isinstance(frame, LLMFullResponseEndFrame):
            if self._current_response:
                print()
                logging.info(f"Jarvis: {self._current_response}")
                if self._transcript_file:
                    try:
                        with open(self._transcript_file, "a", encoding="utf-8") as f:
                            f.write(f"Jarvis: {self._current_response}\n")
                    except Exception as e:
                        logging.error(f"Failed to log to transcript: {e}")
                self._current_response = ""
            self._started = False
            self._label_printed = False

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

class MessageInjector(FrameProcessor):
    def __init__(self, context: LLMContext):
        super().__init__()
        self._context = context
        self._queue = asyncio.Queue()

    def schedule(self, text: str):
        self._queue.put_nowait(text)

    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        # Check if we have any pending messages to inject
        try:
            while not self._queue.empty():
                text = self._queue.get_nowait()
                logging.info(f"Injecting scheduled message: {text}")
                print(f"User (Scheduled): {text}")
                
                # Create a user message
                user_message = {"role": "user", "content": text}
                self._context.messages.append(user_message)
                
                # Push LLMContextFrame to trigger the LLM
                await self.push_frame(LLMContextFrame(messages=self._context.messages), direction)
        except Exception as e:
            logging.error(f"Error injecting message: {e}")

        # Pass the original frame through
        await self.push_frame(frame, direction)

import asyncio
import numpy as np
from faster_whisper import WhisperModel

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame, AudioRawFrame, TranscriptionFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame, StartFrame
)
from pipecat.utils.time import time_now_iso8601

class FastWhisperSTT(FrameProcessor):
    def __init__(self):
        super().__init__()
        self._model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        
        self._sample_rate = 16000
        self._audio_buffer = bytearray()
        self._user_speaking = False
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, StartFrame):
            self._sample_rate = frame.audio_in_sample_rate or 16000
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, AudioRawFrame):
            if self._user_speaking:
                self._audio_buffer += frame.audio
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            self._audio_buffer.clear()
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            
            if len(self._audio_buffer) > 0:
                text = await self._transcribe(bytes(self._audio_buffer))
                if text:
                    print(f"[YOU]: {text}")
                    await self.push_frame(
                        TranscriptionFrame(text, "", time_now_iso8601()),
                        direction
                    )
            
            self._audio_buffer.clear()
            await self.push_frame(frame, direction)
        
        else:
            await self.push_frame(frame, direction)
    
    async def _transcribe(self, audio_bytes: bytes) -> str:
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        segments, _ = await asyncio.to_thread(self._model.transcribe, audio_np, language="en", beam_size=1, best_of=1,
            temperature=0.0, condition_on_previous_text=False, vad_filter=True)
        
        text = "".join(segment.text for segment in segments)
        return text.strip()


async def main():
    AUDIO_IN_INDEX = 1

    vad = SileroVADAnalyzer(params=VADParams(start_secs=0.1, stop_secs=0.5, confidence=0.6, min_volume=0.01))
    
    transport = LocalAudioTransport(
        params=LocalAudioTransportParams(
            audio_in_enabled=True,
            audio_out_enabled=False,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            vad_analyzer=vad,
            audio_in_index=AUDIO_IN_INDEX,
        )
    )
    
    stt = FastWhisperSTT()
    
    pipeline = Pipeline([
        transport.input(),
        stt,
    ])
    
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("\nGoodbye!")
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
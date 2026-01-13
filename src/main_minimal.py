"""
Minimal working Pipecat setup with custom Whisper STT.
Bypasses Pipecat's WhisperSTTService which appears to have issues.
"""
import asyncio
import io
import wave
import numpy as np
from faster_whisper import WhisperModel

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import (
    Frame, AudioRawFrame, TextFrame, TranscriptionFrame,
    UserStartedSpeakingFrame, UserStoppedSpeakingFrame, StartFrame
)
from pipecat.utils.time import time_now_iso8601

class CustomWhisperSTT(FrameProcessor):
    """Custom Whisper STT that actually works."""
    
    def __init__(self, model_name: str = "distil-medium.en"):
        super().__init__()
        print("Loading Whisper model...")
        self._model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("Whisper loaded!")
        
        self._sample_rate = 16000
        self._audio_buffer = bytearray()
        self._user_speaking = False
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)
        
        if isinstance(frame, StartFrame):
            self._sample_rate = frame.audio_in_sample_rate or 16000
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, AudioRawFrame):
            # Buffer audio while user is speaking
            if self._user_speaking:
                self._audio_buffer += frame.audio
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, UserStartedSpeakingFrame):
            self._user_speaking = True
            self._audio_buffer.clear()  # Start fresh
            print("[STT] Started listening...")
            await self.push_frame(frame, direction)
        
        elif isinstance(frame, UserStoppedSpeakingFrame):
            self._user_speaking = False
            print(f"[STT] Stopped listening. Buffer size: {len(self._audio_buffer)} bytes")
            
            if len(self._audio_buffer) > 0:
                # Transcribe the buffered audio
                text = await self._transcribe(bytes(self._audio_buffer))
                if text:
                    print(f"\n{'='*50}")
                    print(f"TRANSCRIPTION: {text}")
                    print(f"{'='*50}\n")
                    await self.push_frame(
                        TranscriptionFrame(text, "", time_now_iso8601()),
                        direction
                    )
            
            self._audio_buffer.clear()
            await self.push_frame(frame, direction)
        
        else:
            await self.push_frame(frame, direction)
    
    async def _transcribe(self, audio_bytes: bytes) -> str:
        """Transcribe audio bytes using Whisper."""
        # Convert bytes to float32 numpy array
        audio_np = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        
        print(f"[STT] Transcribing {len(audio_np)} samples ({len(audio_np)/self._sample_rate:.2f}s)...")
        
        # Run transcription in thread pool to avoid blocking
        segments, info = await asyncio.to_thread(
            self._model.transcribe,
            audio_np,
            language="en",
            beam_size=5
        )
        
        # Collect all text
        text = ""
        for segment in segments:
            if segment.no_speech_prob < 0.4:
                text += segment.text
        
        return text.strip()


async def main():
    print("=" * 50)
    print("PIPECAT WITH CUSTOM WHISPER STT")
    print("=" * 50)
    
    AUDIO_IN_INDEX = 1
    print(f"Using audio input index: {AUDIO_IN_INDEX}\n")
    
    vad = SileroVADAnalyzer(params=VADParams(
        start_secs=0.2,
        stop_secs=0.8,
        confidence=0.5,
        min_volume=0.01
    ))
    
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
    
    stt = CustomWhisperSTT()
    
    pipeline = Pipeline([
        transport.input(),
        stt,
    ])
    
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("\n" + "=" * 50)
    print("LISTENING... Speak clearly, then pause.")
    print("=" * 50 + "\n")
    
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())

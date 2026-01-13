import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.frame_processor import FrameProcessor
from pipecat.frames.frames import Frame, AudioRawFrame, TranscriptionFrame, InterimTranscriptionFrame

class DebugLogger(FrameProcessor):
    """Logs audio and transcription frames."""
    
    def __init__(self, label: str):
        super().__init__()
        self._label = label
        self._audio_frame_count = 0
    
    async def process_frame(self, frame: Frame, direction):
        # Log transcriptions
        if isinstance(frame, TranscriptionFrame):
            print(f"\n[{self._label}] TRANSCRIPTION: {frame.text}")
        elif isinstance(frame, InterimTranscriptionFrame):
            print(f"[{self._label}] (interim): {frame.text}", end="\r")
        elif isinstance(frame, AudioRawFrame):
            self._audio_frame_count += 1
            if self._audio_frame_count % 100 == 0:
                print(f"[{self._label}] Audio frames: {self._audio_frame_count}", end="\r")
        
        # IMPORTANT: Always call parent to properly handle frames
        await super().process_frame(frame, direction)

class VADEventLogger(FrameProcessor):
    """Logs VAD events."""
    
    async def process_frame(self, frame: Frame, direction):
        frame_name = type(frame).__name__
        if "UserStarted" in frame_name or "UserStopped" in frame_name:
            print(f"\n[VAD] >>> {frame_name} <<<")
        
        await super().process_frame(frame, direction)

async def main():
    print("=" * 50)
    print("MINIMAL PIPECAT AUDIO DEBUG")
    print("=" * 50)
    
    AUDIO_IN_INDEX = 1  # Logitech PRO X
    print(f"Using audio input index: {AUDIO_IN_INDEX}\n")
    
    vad = SileroVADAnalyzer(params=VADParams(
        start_secs=0.1,
        stop_secs=0.5,
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
            vad_audio_passthrough=True,
            audio_in_index=AUDIO_IN_INDEX,
        )
    )
    
    print("Loading Whisper model...")
    stt = WhisperSTTService(
        model=Model.DISTIL_MEDIUM_EN,
        device="cpu",
        compute_type="int8"
    )
    print("Whisper loaded!\n")
    
    pipeline = Pipeline([
        transport.input(),
        DebugLogger("AUDIO"),
        VADEventLogger(),
        stt,
        DebugLogger("STT"),
    ])
    
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("=" * 50)
    print("LISTENING... Speak into your microphone!")
    print("=" * 50 + "\n")
    
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("\nShutting down...")
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())

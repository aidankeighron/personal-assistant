import asyncio

from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.task import PipelineTask
from pipecat.pipeline.runner import PipelineRunner
from pipecat.transports.local.audio import LocalAudioTransport, LocalAudioTransportParams
from pipecat.services.whisper.stt import WhisperSTTService, Model
from pipecat.audio.vad.silero import SileroVADAnalyzer, VADParams
from pipecat.processors.frame_processor import FrameProcessor, FrameDirection
from pipecat.frames.frames import Frame, TranscriptionFrame

class TranscriptionPrinter(FrameProcessor):
    """Simple processor to print transcriptions."""
    
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        if isinstance(frame, TranscriptionFrame):
            print(f"[YOU]: {frame.text}")
        await super().process_frame(frame, direction)

async def main():
    AUDIO_IN_INDEX = 1

    vad = SileroVADAnalyzer(params=VADParams(
        start_secs=0.1, 
        stop_secs=0.5, 
        confidence=0.6, 
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
    
    stt = WhisperSTTService(
        model=Model.TINY,
        device="cpu",
        compute_type="int8"
    )
    
    pipeline = Pipeline([
        transport.input(),
        stt,
        TranscriptionPrinter(),
    ])
    
    task = PipelineTask(pipeline)
    runner = PipelineRunner()
    
    print("Listening... (Ctrl+C to exit)\n")
    
    try:
        await runner.run(task)
    except KeyboardInterrupt:
        print("\nGoodbye!")
        await task.cancel()

if __name__ == "__main__":
    asyncio.run(main())
from pipecat.processors.frame_processor import FrameDirection, FrameProcessor
from pipecat.frames.frames import MetricsFrame, Frame
from datetime import datetime
from pathlib import Path
import logging, os

logging.basicConfig(
    filename=f'./logs/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.txt', 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s', 
    filemode='w'
)

# Delete old logs
files = sorted(Path("./logs").glob("*.txt"), key=os.path.getmtime)
if len(files) > 10:
    for file in files[:-10]:
        try:
            os.remove(file)
        except:
            ...

class MetricsLogger(FrameProcessor):
    async def process_frame(self, frame: Frame, direction: FrameDirection):
        await super().process_frame(frame, direction)

        if isinstance(frame, MetricsFrame):
            for d in frame.data:
                logging.info(f"MetricsFrame: {frame}, value: {d.value}")

        await self.push_frame(frame, direction)
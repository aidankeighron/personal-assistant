from pipecat.observers.base_observer import BaseObserver, FramePushed, FrameProcessed
from pipecat.frames.frames import MetricsFrame
from datetime import datetime
from pipecat.metrics.metrics import LLMUsageMetricsData, ProcessingMetricsData, TTFBMetricsData, TTSUsageMetricsData
from pathlib import Path
from collections import deque
import logging, os

def setup_logging():
    logging.basicConfig(
        filename=f'./logs/{datetime.now().strftime("%Y-%m-%d_%H-%M-%S")}.txt', 
        level=logging.INFO, 
        format='%(asctime)s - %(levelname)s - %(message)s', 
        filemode='w'
    )

    # Delete old logs
    files = sorted(Path("logs").glob("*.txt"), key=os.path.getmtime)
    total_files = 5
    if len(files) > total_files:
        for f in files[:-total_files]:
            try:
                os.remove(f)
            except Exception:
                ...

    logging.getLogger("ollama").setLevel(logging.WARNING)
    logging.getLogger("pipecat").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)

class MetricsLogger(BaseObserver):
    def __init__(self):
        super().__init__()
        self._seen_frames = deque(maxlen=100)

    async def on_push_frame(self, data: FramePushed):
        if isinstance(data.frame, MetricsFrame):
            if id(data.frame) in self._seen_frames:
                return
            self._seen_frames.append(id(data.frame))
            for d in data.frame.data:
                if isinstance(d, TTFBMetricsData):
                    logging.info(f"Metric: {type(d).__name__}, time to first byte: {d.value}")
                elif isinstance(d, ProcessingMetricsData):
                    logging.info(f"Metric: {type(d).__name__}, processing: {d.value}")
                elif isinstance(d, LLMUsageMetricsData):
                    logging.info(f"Metric: {type(d).__name__}, tokens: {d.value.prompt_tokens}, characters: {d.value.completion_tokens}")
                elif isinstance(d, TTSUsageMetricsData):
                    logging.info(f"Metric: {type(d).__name__}, characters: {d.value}")
                else:
                    logging.info(f"Metric: {type(d).__name__}, value {d.value}")
    
    async def on_process_frame(self, data: FrameProcessed):
        # Your frame processing observation logic here
        pass
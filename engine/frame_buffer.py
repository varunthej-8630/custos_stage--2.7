# engine/frame_buffer.py — Rolling Pre-Tamper & Incident Circular Frame Buffer
import time
import threading
import collections
from typing import List, Optional, Tuple, Any
import numpy as np

from engine.logger import app_logger

class BufferedFrame:
    __slots__ = ('frame', 'timestamp', 'camera_id')
    def __init__(self, frame: np.ndarray, timestamp: float, camera_id: int = 0):
        self.frame = frame
        self.timestamp = timestamp
        self.camera_id = camera_id

class CircularFrameBuffer:
    """
    Thread-safe bounded in-memory circular frame buffer holding approximately
    10–15 seconds of raw camera frames from the primary ingestion pipeline.
    """
    def __init__(self, max_seconds: float = 15.0, target_fps: int = 30):
        self.max_seconds = max_seconds
        # Calculate bounded capacity (e.g. 15s @ 30 FPS = 450 frames + buffer margin)
        self.max_capacity = max(100, int(max_seconds * max(15, target_fps) * 1.25))
        self.buffer = collections.deque(maxlen=self.max_capacity)
        self.lock = threading.Lock()
        self.camera_id = 0

    def append(self, frame: np.ndarray, timestamp: Optional[float] = None, camera_id: int = 0):
        """
        Appends an ingested camera frame with its timestamp.
        """
        if frame is None or frame.size == 0:
            return

        ts = timestamp or time.time()
        self.camera_id = camera_id
        # Fast copy to isolate memory from frame reuse
        buf_frame = BufferedFrame(frame.copy(), ts, camera_id)
        
        with self.lock:
            self.buffer.append(buf_frame)

    def get_last_seconds(self, seconds: float = 15.0) -> List[np.ndarray]:
        """
        Retrieves in chronological order all frames captured within the last N seconds.
        """
        now = time.time()
        cutoff = now - float(seconds)
        
        with self.lock:
            # Buffer is in chronological insertion order
            result = [bf.frame for bf in self.buffer if bf.timestamp >= cutoff]
            if not result and len(self.buffer) > 0:
                # Fallback: if clock skew or test simulation, return the latest N frames
                est_count = min(len(self.buffer), int(seconds * 25))
                result = [bf.frame for bf in list(self.buffer)[-est_count:]]
            return result

    def get_buffered_duration(self) -> float:
        """Returns the actual time span currently covered in the circular buffer."""
        with self.lock:
            if len(self.buffer) < 2:
                return 0.0
            return max(0.0, self.buffer[-1].timestamp - self.buffer[0].timestamp)

    def size(self) -> int:
        with self.lock:
            return len(self.buffer)

    def clear(self):
        with self.lock:
            self.buffer.clear()

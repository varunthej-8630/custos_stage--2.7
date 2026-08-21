import time
import threading
import psutil
from engine.logger import app_logger

class HealthMonitor:
    """
    Real-time system & pipeline diagnostic collector.
    Throttles Socket.IO telemetry emissions to 1 Hz (once per second).
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.capture_fps = 0.0
        self.analytics_fps = 0.0
        self.inference_latency_ms = 0.0
        self.dropped_frames = 0
        self.queue_depths = {}
        self.last_emit_time = 0.0

    def record_metrics(self, capture_fps=None, analytics_fps=None, latency_ms=None, dropped=None, queues=None):
        with self.lock:
            if capture_fps is not None: self.capture_fps = round(capture_fps, 1)
            if analytics_fps is not None: self.analytics_fps = round(analytics_fps, 1)
            if latency_ms is not None: self.inference_latency_ms = round(latency_ms, 2)
            if dropped is not None: self.dropped_frames += dropped
            if queues is not None: self.queue_depths = dict(queues)

    def get_status(self):
        with self.lock:
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=None)
            return {
                'capture_fps': self.capture_fps,
                'analytics_fps': self.analytics_fps,
                'inference_latency_ms': self.inference_latency_ms,
                'cpu_usage_pct': round(cpu, 1),
                'ram_usage_gb': round((mem.total - mem.available) / (1024**3), 2),
                'dropped_frames': self.dropped_frames,
                'queue_depths': self.queue_depths,
                'status': 'HEALTHY' if self.capture_fps >= 15 else 'DEGRADED'
            }

    def should_emit(self):
        now = time.time()
        with self.lock:
            if now - self.last_emit_time >= 1.0: # 1 Hz throttling
                self.last_emit_time = now
                return True
            return False

class CameraHealthMonitor:
    """
    Dedicated monitor for tracking camera connection health, reconnection attempts,
    and frame acquisition intervals.
    """
    def __init__(self, camera_id=0):
        self.camera_id = camera_id
        self.lock = threading.Lock()
        self.connected = True
        self.disconnect_count = 0
        self.reconnect_attempts = 0
        self.last_frame_time = time.time()
        self.disconnect_start_time = None
        self.total_recovery_duration = 0.0

    def record_frame(self):
        with self.lock:
            now = time.time()
            if not self.connected:
                self.connected = True
                if self.disconnect_start_time:
                    rec_dur = now - self.disconnect_start_time
                    self.total_recovery_duration += rec_dur
                    app_logger.info(f"Camera {self.camera_id}: Recovered after {rec_dur:.2f}s")
                self.disconnect_start_time = None
            self.last_frame_time = now

    def record_disconnect(self):
        with self.lock:
            now = time.time()
            if self.connected:
                self.connected = False
                self.disconnect_count += 1
                self.disconnect_start_time = now
                app_logger.warning(f"Camera {self.camera_id}: Feed disconnected (Count: {self.disconnect_count})")
            self.reconnect_attempts += 1

    def get_status(self):
        with self.lock:
            now = time.time()
            time_since_last_frame = round(now - self.last_frame_time, 2)
            return {
                'camera_id': self.camera_id,
                'connected': self.connected,
                'disconnect_count': self.disconnect_count,
                'reconnect_attempts': self.reconnect_attempts,
                'time_since_last_frame_sec': time_since_last_frame,
                'total_recovery_duration_sec': round(self.total_recovery_duration, 2),
                'status': 'ONLINE' if self.connected and time_since_last_frame < 3.0 else 'OFFLINE'
            }

system_health = HealthMonitor()

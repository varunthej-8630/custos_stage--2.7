# engine/media_recorder.py — Real Camera Evidence Capture & Verification
import os
import cv2
import time
import threading
import collections
from datetime import datetime
from typing import Optional, Tuple, List, Dict, Any
import numpy as np

from config import settings as config
from engine.logger import app_logger

class MediaVerificationResult:
    def __init__(
        self,
        valid: bool,
        file_path: str,
        file_name: str,
        file_size: int = 0,
        frame_count: int = 0,
        fps: float = 0.0,
        width: int = 0,
        height: int = 0,
        duration_sec: float = 0.0,
        error: Optional[str] = None
    ):
        self.valid = valid
        self.file_path = file_path
        self.file_name = file_name
        self.file_size = file_size
        self.frame_count = frame_count
        self.fps = fps
        self.width = width
        self.height = height
        self.duration_sec = duration_sec
        self.error = error

    def to_dict(self) -> Dict[str, Any]:
        return {
            'valid': self.valid,
            'file_path': self.file_path,
            'file_name': self.file_name,
            'file_size': self.file_size,
            'frame_count': self.frame_count,
            'fps': self.fps,
            'width': self.width,
            'height': self.height,
            'duration_sec': self.duration_sec,
            'error': self.error
        }

class IncidentMediaRecorder:
    """
    Thread-safe real camera frame capture, circular pre-event buffer preservation,
    snapshot creation, and MP4 video encoding with post-write validation.
    """
    def __init__(self, snapshot_dir: Optional[str] = None):
        self.snapshot_dir = snapshot_dir or getattr(config, 'SNAPSHOT_DIR', 'data/snapshots')
        os.makedirs(self.snapshot_dir, exist_ok=True)
        self.active_sessions: Dict[str, Dict[str, Any]] = {}
        self.lock = threading.Lock()

    def capture_snapshot(self, frame: np.ndarray, incident_id: Any, prefix: str = 'incident') -> MediaVerificationResult:
        """
        Immediately writes the actual camera frame to disk and verifies it can be read back.
        """
        if frame is None or frame.size == 0:
            app_logger.error(f"[MEDIA RECORDER] Empty frame passed for snapshot (Incident: {incident_id})")
            return MediaVerificationResult(False, '', '', 0, error='Empty frame buffer')

        app_logger.info(f"[SNAPSHOT_CAPTURE_STARTED] incident_id={incident_id}")
        ts = time.strftime('%Y%m%d_%H%M%S')
        file_name = f"{prefix}_{incident_id}_{ts}.jpg"
        full_path = os.path.join(self.snapshot_dir, file_name)

        try:
            # Write high quality JPEG
            success = cv2.imwrite(full_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if not success:
                app_logger.error(f"[SNAPSHOT_FAILED] cv2.imwrite returned False for {full_path}")
                return MediaVerificationResult(False, full_path, file_name, 0, error='cv2.imwrite failed')

            app_logger.info(f"[SNAPSHOT_CAPTURED] incident_id={incident_id} path={file_name}")

            # Verification: file exists, size > 0, decodable by OpenCV with valid dimensions
            if not os.path.exists(full_path):
                app_logger.error(f"[SNAPSHOT_FAILED] incident_id={incident_id} File does not exist after write")
                return MediaVerificationResult(False, full_path, file_name, 0, error='File does not exist after write')

            file_size = os.path.getsize(full_path)
            if file_size <= 0:
                app_logger.error(f"[SNAPSHOT_FAILED] incident_id={incident_id} File size is 0 bytes")
                return MediaVerificationResult(False, full_path, file_name, 0, error='File size is 0 bytes')

            test_img = cv2.imread(full_path)
            if test_img is None or test_img.shape[0] <= 0 or test_img.shape[1] <= 0:
                app_logger.error(f"[SNAPSHOT_FAILED] incident_id={incident_id} Decoded image is invalid or corrupted")
                return MediaVerificationResult(False, full_path, file_name, file_size, error='Decoded image is invalid or corrupted')

            h, w = test_img.shape[:2]
            app_logger.info(f"[SNAPSHOT_VALIDATED] incident_id={incident_id} path={file_name} size={file_size} dims={w}x{h}")
            if prefix == 'tamper':
                app_logger.info(f"[TAMPER_SNAPSHOT_CAPTURED] incident_id={incident_id} path={file_name} size={file_size}")
            return MediaVerificationResult(True, full_path, file_name, file_size, width=w, height=h)

        except Exception as e:
            app_logger.error(f"[SNAPSHOT_FAILED] Exception writing snapshot: {e}")
            return MediaVerificationResult(False, full_path, file_name, 0, error=str(e))


    def start_video_session(self, session_key: str, incident_id: Any, pre_event_frames: Optional[List[np.ndarray]] = None):
        """
        Starts a video recording session initializing with pre-event frames.
        """
        with self.lock:
            buffer = collections.deque(maxlen=900) # Up to ~30-45 seconds of frames at 20-30 FPS
            if pre_event_frames:
                for f in pre_event_frames:
                    if f is not None and f.size > 0:
                        buffer.append(f.copy())

            self.active_sessions[session_key] = {
                'incident_id': incident_id,
                'buffer': buffer,
                'start_time': time.time(),
                'status': 'CAPTURING'
            }
            preroll_count = len(buffer)
            app_logger.info(f"[VIDEO_STARTED] Session {session_key} (Incident: {incident_id}) initialized with {preroll_count} pre-event frames")
            if session_key.startswith('tamper:'):
                est_dur = round(preroll_count / 25.0, 1)
                app_logger.info(f"[TAMPER_PREROLL_CAPTURED] frames={preroll_count} duration={est_dur}s")
                app_logger.info(f"[TAMPER_RECORDING_STARTED] incident_id={incident_id}")

    def start_tamper_recording(self, incident_id: Any, camera_id: int, pre_event_frames: Optional[List[np.ndarray]] = None) -> str:
        """Dedicated convenience method for Tamper recording initialization."""
        session_key = f"tamper:{camera_id}:TAMPER"
        self.start_video_session(session_key, incident_id, pre_event_frames)
        return session_key

    def append_frame(self, session_key: str, frame: np.ndarray):
        """Appends live incident frame to active recording session."""
        with self.lock:
            session = self.active_sessions.get(session_key)
            if session and session['status'] == 'CAPTURING' and frame is not None and frame.size > 0:
                session['buffer'].append(frame.copy())

    def append_tamper_frame(self, session_key: str, frame: np.ndarray):
        """Dedicated convenience method for appending tamper frames."""
        self.append_frame(session_key, frame)

    def validate_video(self, file_path: str) -> MediaVerificationResult:
        """
        Validates the physical MP4 container on disk.
        """
        if not os.path.exists(file_path):
            return MediaVerificationResult(False, file_path, os.path.basename(file_path), 0, error='MP4 file does not exist')

        file_size = os.path.getsize(file_path)
        if file_size <= 0:
            return MediaVerificationResult(False, file_path, os.path.basename(file_path), 0, error='MP4 file size is 0 bytes')

        test_cap = cv2.VideoCapture(file_path)
        if not test_cap.isOpened():
            return MediaVerificationResult(False, file_path, os.path.basename(file_path), file_size, error='Encoded MP4 container cannot be opened')

        ret, frame0 = test_cap.read()
        frame_count = int(test_cap.get(cv2.CAP_PROP_FRAME_COUNT))
        fps = float(test_cap.get(cv2.CAP_PROP_FPS) or 20.0)
        w = int(test_cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(test_cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        test_cap.release()

        if not ret or frame0 is None or frame_count <= 0 or w <= 0 or h <= 0:
            return MediaVerificationResult(False, file_path, os.path.basename(file_path), file_size, error='MP4 container has 0 decodable frames')


        duration = round(frame_count / max(1.0, fps), 2)
        return MediaVerificationResult(
            True,
            file_path,
            os.path.basename(file_path),
            file_size=file_size,
            frame_count=frame_count,
            fps=fps,
            width=w,
            height=h,
            duration_sec=duration
        )

    def finalize_video(self, session_key: str, fps: int = 20, prefix: str = 'incident') -> MediaVerificationResult:
        """
        Encodes buffered frames to an MP4 video file and verifies readability.
        """
        with self.lock:
            session = self.active_sessions.pop(session_key, None)

        if not session:
            return MediaVerificationResult(False, '', '', 0, error=f'No active session {session_key}')

        buffer = list(session['buffer'])
        incident_id = session['incident_id']

        if not buffer:
            app_logger.error(f"[VIDEO_FAILED] No frames recorded in buffer for session {session_key}")
            return MediaVerificationResult(False, '', '', 0, error='No frames recorded')

        ts = time.strftime('%Y%m%d_%H%M%S')
        file_name = f"{prefix}_{incident_id}_{ts}.mp4"
        full_path = os.path.join(self.snapshot_dir, file_name)

        h, w = buffer[0].shape[:2]

        try:
            writer = None
            # Test codecs in controlled order: mp4v (universally compatible), then avc1 / H264
            for codec in ['mp4v', 'avc1', 'H264']:
                try:
                    fourcc = cv2.VideoWriter_fourcc(*codec)
                    w_test = cv2.VideoWriter(full_path, fourcc, float(fps), (w, h))
                    if w_test.isOpened():
                        writer = w_test
                        break
                except Exception:
                    continue

            if writer is None or not writer.isOpened():
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                writer = cv2.VideoWriter(full_path, fourcc, float(fps), (w, h))

            if not writer.isOpened():
                app_logger.error(f"[VIDEO_FAILED] Could not initialize OpenCV VideoWriter for {full_path}")
                return MediaVerificationResult(False, full_path, file_name, 0, error='VideoWriter open failed')

            for f in buffer:
                if f.shape[:2] != (h, w):
                    f = cv2.resize(f, (w, h))
                writer.write(f)

            writer.release()

            # Post-write validation
            val_res = self.validate_video(full_path)
            if not val_res.valid:
                app_logger.error(f"[VIDEO_FAILED] Video validation failed: {val_res.error}")
                return val_res

            duration = round(len(buffer) / float(fps), 1)
            app_logger.info(f"[VIDEO_FINALIZED] Incident {incident_id} -> {file_name} ({val_res.file_size} bytes, {len(buffer)} frames, {w}x{h} @ {fps}fps, {duration}s)")
            if prefix == 'tamper':
                app_logger.info(f"[TAMPER_RECORDING_FINALIZED] frames={len(buffer)} duration={duration}s")
                app_logger.info(f"[TAMPER_VIDEO_VALIDATED] path={file_name} size={val_res.file_size} frames={len(buffer)}")

            return val_res

        except Exception as e:
            app_logger.error(f"[VIDEO_FAILED] Exception finalizing video: {e}")
            return MediaVerificationResult(False, full_path, file_name, 0, error=str(e))

    def finalize_tamper_recording(self, session_key: str, fps: int = 20) -> MediaVerificationResult:
        """Dedicated convenience method for finalizing tamper recordings."""
        return self.finalize_video(session_key, fps=fps, prefix='tamper')

media_recorder = IncidentMediaRecorder()

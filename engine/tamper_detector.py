# engine/tamper_detector.py — Temporal Tamper Detection Engine
import cv2
import time
import os
from typing import Tuple, List, Optional
import numpy as np

from engine.logger import app_logger

class TamperDetector:
    """
    Advanced Tamper Detection Engine with Temporal Confirmation.
    
    Detects 7 Physical & Optical Conditions:
      1. Camera Obstruction (Blur via Laplacian Variance)
      2. Lens Covering / Extreme Darkness (Mean pixel intensity threshold)
      3. Camera Shift / Movement (Frame Delta against reference)
      4. Camera Disconnection (Signal Lost)
      5. Frame Freezing (Identical frames count)
      6. Sudden Brightness Changes (Intensity jump)
      7. Sudden Darkness (Intensity drop)
      
    Temporal Invariants:
      - Requires TAMPER_CONFIRM_SECONDS (0.8s) of sustained abnormal state before CONFIRMATION.
      - Requires TAMPER_RECOVERY_SECONDS (3.0s) of continuous healthy state before RESOLUTION.
    """
    def __init__(
        self,
        camera_id: int = 0,
        confirm_seconds: float = 0.8,
        recovery_seconds: float = 3.0
    ):
        self.camera_id = camera_id
        self.confirm_seconds = confirm_seconds
        self.recovery_seconds = recovery_seconds
        
        self.reference_frame = None
        self.last_frame = None
        self.last_mean_val = None
        self.frozen_count = 0
        
        # State Machine: NORMAL -> POSSIBLE -> CONFIRMED -> RECOVERING -> RESOLVED
        self.is_confirmed = False
        self.tamper_candidate_start: Optional[float] = None
        self.recovery_candidate_start: Optional[float] = None
        self.active_reasons: List[str] = []
        self.tamper_start_time = 0.0
        
        # Thresholds
        self.blur_threshold = 40.0 # Laplacian variance
        self.darkness_threshold = 20.0 # Mean pixel intensity
        self.brightness_threshold = 230.0 # High intensity cap

    def set_reference(self, frame: np.ndarray):
        if frame is not None and frame.size > 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            self.reference_frame = cv2.GaussianBlur(gray, (21, 21), 0)

    def analyze_frame_raw(self, frame: np.ndarray) -> Tuple[bool, List[str]]:
        """
        Analyzes a single frame against the 7 optical conditions.
        """
        if frame is None or getattr(frame, 'size', 0) == 0:
            return True, ["VIDEO SIGNAL LOST / CAMERA DISCONNECTED"]

        reasons = []
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        mean_val = float(np.mean(gray))

        # 1. Darkness / Lens Covering
        if mean_val < self.darkness_threshold:
            reasons.append("SUDDEN DARKNESS / LENS COVERED")

        # 2. Sudden Brightness Change
        if mean_val > self.brightness_threshold:
            reasons.append("SUDDEN BRIGHTNESS CHANGE")
        elif (self.last_mean_val is not None and 
              self.last_mean_val >= self.darkness_threshold and 
              (mean_val - self.last_mean_val) > 120.0):
            reasons.append("SUDDEN BRIGHTNESS CHANGE")

        # 3. Blur / Lens Obstruction (Laplacian Variance)
        laplacian_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        if laplacian_var < self.blur_threshold:
            reasons.append("CAMERA BLUR / LENS OBSTRUCTION")

        # 4. Camera Shift / Movement check
        if self.reference_frame is not None:
            blur_gray = cv2.GaussianBlur(gray, (21, 21), 0)
            frame_delta = cv2.absdiff(self.reference_frame, blur_gray)
            thresh = cv2.threshold(frame_delta, 25, 255, cv2.THRESH_BINARY)[1]
            non_zero_ratio = (cv2.countNonZero(thresh) / float(gray.size)) * 100.0
            if non_zero_ratio > 85.0: # 85% sudden scene change
                reasons.append("CAMERA SHIFT / DISPLACEMENT")

        # 5. Frame Freezing check
        if self.last_frame is not None:
            diff = np.abs(gray.astype(np.float32) - self.last_frame.astype(np.float32))
            if np.mean(diff) < 0.1:
                self.frozen_count += 1
            else:
                self.frozen_count = 0

            if self.frozen_count >= 15:
                reasons.append("FRAME FREEZING DETECTED")

        self.last_frame = gray.copy()
        self.last_mean_val = mean_val

        is_abnormal = len(reasons) > 0
        return is_abnormal, reasons

    def analyze_frame(self, frame: np.ndarray, timestamp: Optional[float] = None) -> Tuple[bool, List[str]]:
        """
        Direct frame analysis for the 7 tamper conditions.
        """
        return self.analyze_frame_raw(frame)

    def update(self, frame: np.ndarray, pretamper_buffer: Optional[List[np.ndarray]] = None, timestamp: Optional[float] = None) -> Tuple[bool, List[str]]:
        """
        Executes temporal confirmation over streaming pipeline frames.
        Returns (is_confirmed: bool, reasons: list[str])
        """
        now = timestamp or time.time()
        is_abnormal, reasons = self.analyze_frame_raw(frame)

        if is_abnormal:
            self.active_reasons = reasons
            if not self.is_confirmed:
                if self.tamper_candidate_start is None:
                    self.tamper_candidate_start = now
                    app_logger.info(f"[TAMPER_POSSIBLE] camera={self.camera_id} reason={', '.join(reasons)}")
                elif (now - self.tamper_candidate_start) >= self.confirm_seconds:
                    self.is_confirmed = True
                    self.tamper_start_time = now
                    self.recovery_candidate_start = None
                    app_logger.warning(f"[TAMPER_CONFIRMED] camera={self.camera_id} reason={', '.join(reasons)} (Sustained {round(now - self.tamper_candidate_start, 2)}s)")
            else:
                # Still confirmed tamper, reset any pending recovery
                self.recovery_candidate_start = None
        else:
            # Healthy normal frame
            if not self.is_confirmed:
                # Brief glitch / abnormal flicker reset
                self.tamper_candidate_start = None
            else:
                # Tamper was active, now observing normal frames
                if self.recovery_candidate_start is None:
                    self.recovery_candidate_start = now
                    app_logger.info(f"[TAMPER_RECOVERY_DETECTED] camera={self.camera_id} (Starting {self.recovery_seconds}s confirmation)")
                elif (now - self.recovery_candidate_start) >= self.recovery_seconds:
                    self.is_confirmed = False
                    self.tamper_candidate_start = None
                    self.recovery_candidate_start = None
                    app_logger.info(f"[TAMPER_RECOVERED] camera={self.camera_id} Normal feed fully restored")

        return self.is_confirmed, self.active_reasons if self.is_confirmed else []

    def reset(self):
        self.is_confirmed = False
        self.tamper_candidate_start = None
        self.recovery_candidate_start = None
        self.active_reasons = []

tamper_detector = TamperDetector(camera_id=0, confirm_seconds=0.8, recovery_seconds=3.0)

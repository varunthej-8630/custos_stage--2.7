import numpy as np
import cv2
from engine.tamper_detector import TamperDetector

def test_tamper_detector_darkness():
    detector = TamperDetector(camera_id=0)
    # Create black frame (0 intensity)
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    is_tampered, reasons = detector.analyze_frame(black_frame)
    assert is_tampered is True
    assert any("DARKNESS" in r for r in reasons)

def test_tamper_detector_clear_frame():
    detector = TamperDetector(camera_id=0)
    # Create normal noisy frame with texture
    clear_frame = np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8)
    is_tampered, reasons = detector.analyze_frame(clear_frame)
    assert is_tampered is False
    assert len(reasons) == 0

def test_tamper_detector_update_flow():
    detector = TamperDetector(camera_id=0, confirm_seconds=0.1, recovery_seconds=0.2)
    black_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    # First frame is POSSIBLE
    tampered, reasons = detector.update(black_frame, timestamp=100.0)
    assert tampered is False
    # Second frame after confirm_seconds is CONFIRMED
    tampered, reasons = detector.update(black_frame, timestamp=100.2)
    assert tampered is True
    assert len(reasons) > 0

    clear_frame = np.random.randint(100, 200, (480, 640, 3), dtype=np.uint8)
    # First normal frame starts recovery
    tampered, reasons = detector.update(clear_frame, timestamp=100.3)
    assert tampered is True
    # Frame after recovery_seconds is RESOLVED
    tampered, reasons = detector.update(clear_frame, timestamp=100.6)
    assert tampered is False

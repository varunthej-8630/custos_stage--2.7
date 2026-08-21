# tests/test_vision_perception.py — Perception Engine Tests
import numpy as np
import pytest
from engine.perception_engine import PerceptionEngine
from config import settings as config

@pytest.fixture
def perception():
    return PerceptionEngine()

def test_perception_initialization(perception):
    assert perception is not None
    info = perception.get_model_info()
    assert 'YOLOv8' in info['model_name']
    assert info['confidence_threshold'] == config.CONFIDENCE

def test_perception_invalid_and_empty_frames(perception):
    # None frame
    assert perception.detect(None) == []
    # Empty frame
    assert perception.detect(np.array([])) == []
    # Non-image type
    assert perception.detect("not_a_frame") == []

def test_perception_inference_black_frame(perception):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    dets = perception.detect(frame)
    assert isinstance(dets, list)
    assert len(dets) == 0  # Black frame has 0 detections
    info = perception.get_model_info()
    assert info['latency_ms'] > 0.0

def test_perception_schema_and_class_filtering(perception):
    # Create synthetic frame with non-empty gradient
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 120
    dets = perception.detect(frame, classes=[config.CLASS_PERSON])
    assert isinstance(dets, list)
    for d in dets:
        assert 'class_id' in d
        assert 'class_name' in d
        assert 'confidence' in d
        assert 'bbox' in d
        assert len(d['bbox']) == 4
        assert d['class_id'] == config.CLASS_PERSON

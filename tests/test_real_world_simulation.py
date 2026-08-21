# tests/test_real_world_simulation.py — 15 Real-World Synthetic Operational Scenarios
import numpy as np
import time
import pytest
from engine.ai_engine import ai_engine
from config import settings as config

@pytest.fixture
def clean_ai():
    return ai_engine

def test_scenario_01_empty_room(clean_ai):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=1,
        zones=[[100, 100, 300, 300]],
        zone_types=['HIGH'],
        monitoring=True,
        tamper=False
    )
    assert score == 0.0
    assert len(tracks) == 0
    assert alert is False

def test_scenario_02_single_standing_person_outside_zone(clean_ai):
    dets = [{
        'bbox': [10, 10, 80, 180],
        'confidence': 0.89,
        'class_id': config.CLASS_PERSON,
        'class_name': 'person'
    }]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=2,
        zones=[[200, 200, 400, 400]],
        zone_types=['HIGH'],
        monitoring=True,
        detections=dets
    )
    assert len(tracks) == 1
    assert tracks[0]['current_zone'] is None
    assert score == 0.0
    assert alert is False

def test_scenario_03_walking_person_entering_watch_zone(clean_ai):
    dets = [{
        'bbox': [220, 220, 300, 380],
        'confidence': 0.91,
        'class_id': config.CLASS_PERSON,
        'class_name': 'person'
    }]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=4,
        zones=[[200, 200, 400, 400]],
        zone_types=['WATCH'],
        monitoring=True,
        detections=dets
    )
    assert len(tracks) == 1
    assert tracks[0]['current_zone'] == 0
    # Entry within grace period does not immediately alert
    assert alert is False

def test_scenario_04_person_breaching_high_security_zone(clean_ai):
    dets = [{
        'bbox': [220, 220, 300, 380],
        'confidence': 0.95,
        'class_id': config.CLASS_PERSON,
        'class_name': 'person'
    }]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=6,
        zones=[[200, 200, 400, 400]],
        zone_types=['HIGH'],
        monitoring=True,
        detections=dets
    )
    assert len(tracks) == 1
    assert tracks[0]['current_zone'] == 0
    assert score >= 60.0
    assert any("HIGH zone breach" in r for r in reasons)

def test_scenario_05_person_leaving_high_zone(clean_ai):
    # Move person outside
    dets = [{
        'bbox': [10, 10, 80, 180],
        'confidence': 0.90,
        'class_id': config.CLASS_PERSON,
        'class_name': 'person'
    }]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=8,
        zones=[[200, 200, 400, 400]],
        zone_types=['HIGH'],
        monitoring=True,
        detections=dets
    )
    assert len(tracks) == 1
    assert tracks[0]['current_zone'] is None

def test_scenario_06_camera_tamper_event(clean_ai):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=10,
        zones=[[100, 100, 300, 300]],
        zone_types=['HIGH'],
        monitoring=True,
        tamper=True
    )
    assert score == 100.0
    assert alert is True
    assert "CAMERA TAMPER DETECTED" in reasons

def test_scenario_07_multi_person_scene(clean_ai):
    dets = [
        {'bbox': [50, 50, 100, 180], 'confidence': 0.88, 'class_id': config.CLASS_PERSON, 'class_name': 'person'},
        {'bbox': [250, 250, 320, 380], 'confidence': 0.92, 'class_id': config.CLASS_PERSON, 'class_name': 'person'}
    ]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=12,
        zones=[[200, 200, 400, 400]],
        zone_types=['HIGH'],
        monitoring=True,
        detections=dets
    )
    assert len(tracks) == 2
    # Person 2 inside, Person 1 outside
    in_zones = [t['current_zone'] for t in tracks]
    assert 0 in in_zones

def test_scenario_08_crouch_does_not_generate_fake_alarm(clean_ai):
    # Reset risk engine score
    clean_ai.risk_engine.score = 0.0
    # Verify crouch heuristic is DISABLED and does not raise production alert outside zone
    dets = [{
        'bbox': [10, 10, 80, 100], # Squat aspect ratio
        'confidence': 0.90,
        'class_id': config.CLASS_PERSON,
        'class_name': 'person'
    }]
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    score, reasons, alert, tracks = clean_ai.process_frame(
        frame=frame,
        frame_count=14,
        zones=[[300, 300, 500, 500]],
        zone_types=['HIGH'],
        monitoring=True,
        detections=dets
    )
    assert score == 0.0
    assert not any("CROUCH" in r for r in reasons)

def test_scenario_09_telemetry_inspection(clean_ai):
    telemetry = clean_ai.get_telemetry()
    assert 'model_name' in telemetry
    assert 'inference_latency_ms' in telemetry
    assert 'analyzers' in telemetry
    assert any(a['behavior'] == 'crouching' and a['status'] == 'DISABLED' for a in telemetry['analyzers'])
    assert any(a['behavior'] == 'zone_entry' and a['status'] == 'VALIDATED' for a in telemetry['analyzers'])

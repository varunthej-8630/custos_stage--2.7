import time
import numpy as np
from engine.decision_engine import DecisionEngine
from engine.risk_engine import RiskEngine
from engine.tracker import PersonTracker
from engine.ai_engine import ai_engine
from config import settings as config

def test_ai_engine_initialization():
    assert ai_engine is not None
    assert hasattr(ai_engine, 'process_frame')

def test_ai_engine_frame_processing():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    score, events, alert, tracks = ai_engine.process_frame(
        frame=frame,
        frame_count=1,
        zones=[[10, 10, 300, 300]],
        zone_types=['HIGH'],
        monitoring=True
    )
    assert isinstance(score, float)
    assert isinstance(events, list)
    assert isinstance(alert, bool)
    assert isinstance(tracks, list)

def test_decision_engine_zone_overlap():
    de = DecisionEngine()
    zone = [100, 100, 300, 300] # x1, y1, x2, y2

    # 1. Feet inside zone
    person1 = {'foot_x': 150, 'foot_y': 200, 'box': [140, 100, 160, 200]}
    assert de.is_person_in_zone(person1, zone) is True

    # 2. Bounding box center inside zone
    person2 = {'foot_x': 50, 'foot_y': 50, 'box': [180, 180, 220, 220]}
    assert de.is_person_in_zone(person2, zone) is True

    # 3. Person completely outside zone
    person3 = {'foot_x': 10, 'foot_y': 10, 'box': [5, 5, 20, 20]}
    assert de.is_person_in_zone(person3, zone) is False

def test_decision_engine_tamper():
    de = DecisionEngine()
    score, events, alert = de.process([], [[10, 10, 50, 50]], ['HIGH'], tamper=True)
    assert score == 100.0
    assert 'CAMERA TAMPERED!' in events
    assert alert is True

def test_risk_engine_decay_and_hysteresis():
    re = RiskEngine()
    assert re.score == 0.0

    # Simulate TAMPER
    score = re.update([], {}, tamper=True)
    assert score == 100.0
    assert re.should_alert() is False

    re._above_threshold_since = time.time() - 3.0
    assert re.should_alert() is True

def test_person_tracker_updates():
    tracker = PersonTracker()
    detections = [{
        'class_id': config.CLASS_PERSON,
        'label': 'person',
        'box': [100, 100, 150, 250],
        'confidence': 0.85
    }]

    tracks = tracker.update(detections)
    assert len(tracks) == 1
    assert tracks[0]['track_id'] == 1
    assert tracks[0]['foot_x'] == 125
    assert tracks[0]['foot_y'] == 250

import time
import pytest
from engine.health_monitor import HealthMonitor, CameraHealthMonitor
from engine.person_memory import PersonMemory, PersonMemoryManager
from engine.situation_engine import SituationEngine
from engine.identity_layer import IdentityLayer

def test_health_monitor():
    hm = HealthMonitor()
    hm.record_metrics(capture_fps=30.0, analytics_fps=28.5, latency_ms=18.2, dropped=1, queues={'CaptureQueue': 1})
    status = hm.get_status()
    assert status['capture_fps'] == 30.0
    assert status['analytics_fps'] == 28.5
    assert status['inference_latency_ms'] == 18.2
    assert status['dropped_frames'] == 1
    assert status['status'] == 'HEALTHY'

    # Throttling check
    assert hm.should_emit() is True
    assert hm.should_emit() is False # Within 1s window

def test_camera_health_monitor():
    chm = CameraHealthMonitor(camera_id=0)
    chm.record_frame()
    status = chm.get_status()
    assert status['connected'] is True
    assert status['status'] == 'ONLINE'

    chm.record_disconnect()
    status_off = chm.get_status()
    assert status_off['connected'] is False
    assert status_off['disconnect_count'] == 1
    assert status_off['status'] == 'OFFLINE'

def test_person_memory():
    mgr = PersonMemoryManager()
    mem = mgr.get_or_create(17)
    mem.update_position(100, 100, 100, 200)
    mem.update_zone(0) # Entered Zone 0
    time.sleep(0.05)
    mem.update_position(105, 105, 105, 205)

    data = mem.to_dict()
    assert data['person_id'] == 'Person-17'
    assert data['track_id'] == 17
    assert 0 in data['visited_zones']
    assert data['identity']['status'] == 'TRACKED_SUBJECT'


def test_situation_engine():
    se = SituationEngine()
    b1 = se.evaluate(10.0, set(), 1)
    assert b1['risk_level'] == 'Normal'
    assert 'Area clear' in b1['summary']

    # Repeated call with same state should return cached briefing
    b2 = se.evaluate(10.0, set(), 1)
    assert b2 is b1

    # State change
    b3 = se.evaluate(85.0, {'HIGH ZONE BREACH'}, 1)
    assert b3['risk_level'] == 'Critical'
    assert 'HIGH RISK' in b3['summary']

def test_identity_layer():
    assert IdentityLayer.classify_risk_rating(85.0) == 'CRITICAL'
    assert IdentityLayer.classify_risk_rating(10.0) == 'NORMAL'
    
    id_info = IdentityLayer.classify_identity(17)
    assert id_info['identity_status'] == 'TRACKED_SUBJECT'
    assert id_info['label'] == 'Track-17'

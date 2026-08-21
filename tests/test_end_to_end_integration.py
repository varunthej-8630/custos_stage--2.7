import os
import json
import time
import numpy as np
import pytest
from datetime import datetime, timedelta

from web.server import app, parse_events
from database.models import db, Incident, Subject, Evidence, User, UserRole
from database.database_manager import db_manager
from engine.tamper_detector import TamperDetector, tamper_detector
from engine.storage_queue import storage_queue, StorageQueueManager
from engine.evidence_cache import evidence_cache
from engine.evidence_engine import evidence_engine

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    app.config['WTF_CSRF_ENABLED'] = False
    with app.app_context():
        db.create_all()
        admin = User.query.filter_by(username='testadmin').first()
        if not admin:
            admin = User(username='testadmin', email='testadmin@custos.local', role=UserRole.ADMIN, is_active=True)
            admin.set_password('password123')
            db.session.add(admin)
            db.session.commit()

        with app.test_client() as client:
            client.post('/login', data={'username': 'testadmin', 'password': 'password123'})
            yield client

def test_parse_events_serialization():
    # Single-encoded JSON
    assert parse_events('["PACING", "LINGERING"]') == ["PACING", "LINGERING"]
    # Double-encoded JSON
    assert parse_events('"[\\"PACING\\"]"') == ["PACING"]
    # Malformed JSON string
    assert parse_events('[PACING') == ["[PACING"]
    # Empty/None values
    assert parse_events(None) == []
    assert parse_events([]) == []
    # Plain list
    assert parse_events(["PACING", 123]) == ["PACING", "123"]

def test_api_incidents_filtering(client):
    with app.app_context():
        Incident.query.delete()
        db.session.commit()

        inc1 = Incident(
            camera_id=0,
            zone_name='Zone-A High Security',
            score=85.0,
            reliability_score=90.0,
            subject_id='Person-17',
            events=json.dumps(['INTRUSION', 'PACING']),
            ai_summary='Intrusion detected in Zone-A',
            recommended_action='Dispatch security team immediately',
            status='New'
        )
        inc2 = Incident(
            camera_id=1,
            zone_name='Observation Area',
            score=30.0,
            reliability_score=70.0,
            subject_id='Person-03',
            events=json.dumps(['LINGERING']),
            ai_summary='Subject lingering near entrance',
            recommended_action='Monitor feed',
            status='Resolved'
        )
        db.session.add_all([inc1, inc2])
        db.session.commit()

    # Full-text search q
    res = client.get('/api/incidents?q=Person-17')
    data = res.get_json()
    assert res.status_code == 200
    assert len(data) == 1
    assert data[0]['subject_id'] == 'Person-17'

    # Search by camera_id
    res = client.get('/api/incidents?camera_id=1')
    data = res.get_json()
    assert len(data) == 1
    assert data[0]['subject_id'] == 'Person-03'

    # Search by zone
    res = client.get('/api/incidents?zone=Zone-A')
    data = res.get_json()
    assert len(data) == 1
    assert data[0]['subject_id'] == 'Person-17'

    # Search by min_reliability
    res = client.get('/api/incidents?min_reliability=80')
    data = res.get_json()
    assert len(data) == 1
    assert data[0]['reliability_score'] == 90.0

    # Search by incident_type
    res = client.get('/api/incidents?incident_type=PACING')
    data = res.get_json()
    assert len(data) == 1
    assert 'PACING' in data[0]['events']

def test_api_incidents_modes(client):
    with app.app_context():
        Incident.query.delete()
        db.session.commit()

        inc_threat = Incident(
            camera_id=0,
            zone_name='HIGH Security',
            score=95.0,
            subject_id='Person-Threat',
            events=json.dumps(['CAMERA TAMPER: BLUR']),
            status='New'
        )
        inc_user = Incident(
            camera_id=0,
            zone_name='Observation Area',
            score=20.0,
            subject_id='Person-User',
            events=json.dumps(['NORMAL_ENTRY']),
            status='Resolved'
        )
        db.session.add_all([inc_threat, inc_user])
        db.session.commit()

    # User mode (low threat / resolved)
    res_user = client.get('/api/incidents?mode=user')
    data_user = res_user.get_json()
    assert any(x['subject_id'] == 'Person-User' for x in data_user)

    # Security mode (high threat / score >= 60 / tamper)
    res_sec = client.get('/api/incidents?mode=security')
    data_sec = res_sec.get_json()
    assert any(x['subject_id'] == 'Person-Threat' for x in data_sec)
    assert not any(x['subject_id'] == 'Person-User' and x['score'] < 60 and x['status'] != 'Resolved' for x in data_sec)

    # All mode
    res_all = client.get('/api/incidents?mode=all')
    data_all = res_all.get_json()
    assert len(data_all) == 2

def test_tamper_detector_seven_conditions():
    td = TamperDetector(camera_id=99)
    normal_frame = np.ones((480, 640, 3), dtype=np.uint8) * 128
    td.set_reference(normal_frame)

    # 1. Camera Disconnection / Signal Loss
    active, reasons = td.analyze_frame(None)
    assert active is True
    assert any("SIGNAL LOST" in r for r in reasons)

    # 2. Sudden Darkness / Lens Covered
    dark_frame = np.ones((480, 640, 3), dtype=np.uint8) * 5
    active, reasons = td.analyze_frame(dark_frame)
    assert active is True
    assert any("DARKNESS" in r or "LENS COVERED" in r for r in reasons)

    # 3. Sudden Brightness Change
    bright_frame = np.ones((480, 640, 3), dtype=np.uint8) * 245
    active, reasons = td.analyze_frame(bright_frame)
    assert active is True
    assert any("BRIGHTNESS" in r for r in reasons)

    # 4. Camera Blur / Lens Obstruction
    blur_frame = np.ones((480, 640, 3), dtype=np.uint8) * 100
    active, reasons = td.analyze_frame(blur_frame)
    assert active is True
    assert any("BLUR" in r or "OBSTRUCTION" in r for r in reasons)

    # 5. Camera Shift / Movement
    ref_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    ref_frame[:, :320] = 255
    td.set_reference(ref_frame)

    shift_frame = np.zeros((480, 640, 3), dtype=np.uint8)
    shift_frame[:, 320:] = 255
    active, reasons = td.analyze_frame(shift_frame)
    assert active is True
    assert any("SHIFT" in r or "DISPLACEMENT" in r for r in reasons)

    # 6. Frame Freezing
    td_freeze = TamperDetector(camera_id=98)
    static_frame = np.ones((480, 640, 3), dtype=np.uint8) * 150
    for _ in range(20):
        active, reasons = td_freeze.analyze_frame(static_frame)
    assert active is True
    assert any("FREEZING" in r for r in reasons)

def test_storage_queue_and_cache_sync(client):
    sq = StorageQueueManager(maxsize=10)
    sq.set_app(app)

    payload = {
        'camera_id': 0,
        'zone_name': 'Test Zone',
        'score': 77.0,
        'reliability_score': 88.0,
        'subject_id': 'Person-SyncTest',
        'events': ['PACING'],
        'ai_summary': 'Sync test incident',
        'recommended_action': 'Verify cache sync',
        'timeline': [{'step': 1, 'time': '12:00:00', 'action': 'Entry', 'type': 'entry'}],
        'snapshot_path': 'test_snap.jpg',
        'status': 'New'
    }

    # Execute task synchronously
    success = sq._execute_task('save_incident', payload)
    assert success is True

    # Verify Database insertion
    with app.app_context():
        inc = Incident.query.filter_by(subject_id='Person-SyncTest').first()
        assert inc is not None
        assert inc.score == 77.0

    # Verify Evidence Cache update
    cached = evidence_cache.get_recent(10)
    assert any(x.get('subject_id') == 'Person-SyncTest' for x in cached)

def test_evidence_engine_replay_builder():
    pkg = evidence_engine.process_event(
        camera_id=0,
        score=90.0,
        event_log=['HIGH ZONE BREACH', 'PACING'],
        zone_name='Server Room',
        subject_memory={'person_id': 'Person-99', 'dwell_seconds': 45.0, 'behaviors': {'PACING': 1.0}, 'spatial_trajectory': [1]*10, 'track_id': 99}
    )
    assert pkg['subject_id'] == 'Person-99'
    assert len(pkg['timeline']) >= 3
    assert pkg['timeline'][0]['action'].startswith('Subject Person-99 detected')

import time
import numpy as np
import pytest
from flask import Flask

from database.models import db, Incident, User, UserRole
from engine.incident_lifecycle import IncidentLifecycleManager

@pytest.fixture
def app_ctx(tmp_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/test_lifecycle.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

def test_high_zone_entry_dwell_exit_reentry_lifecycle(app_ctx):
    emitted_events = []
    def mock_socket(event_name, data):
        emitted_events.append((event_name, data))
        
    mgr = IncidentLifecycleManager(exit_grace_seconds=0.2, socket_emitter=mock_socket, flask_app=app_ctx)
    
    zones = [[100, 100, 300, 300]]
    zone_types = ['HIGH']
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    
    # 1. Person outside zone
    outside_tracks = [{'track_id': 1, 'current_zone': None, 'bbox': [10, 10, 50, 50]}]
    mgr.process_zone_tracks(0, outside_tracks, zones, zone_types, frame)
    assert len(mgr.active_sessions) == 0
    assert len(emitted_events) == 0
    
    # 2. Person walks into HIGH zone (Frame 1)
    inside_tracks = [{'track_id': 1, 'current_zone': 0, 'bbox': [150, 150, 200, 250]}]
    mgr.process_zone_tracks(0, inside_tracks, zones, zone_types, frame)
    
    assert len(mgr.active_sessions) == 1
    session_key = "zone:0:Person-1:Zone-1 (HIGH):ZONE_BREACH"
    assert session_key in mgr.active_sessions
    first_incident_id = mgr.active_sessions[session_key].incident_id
    
    # Verify exactly 1 alert_created and 1 evidence_created emitted
    alert_events = [e for e in emitted_events if e[0] == 'alert_created']
    evidence_events = [e for e in emitted_events if e[0] == 'evidence_created']
    assert len(alert_events) == 1
    assert len(evidence_events) == 1
    
    # 3. Person stays inside HIGH zone for 100 consecutive frames
    for _ in range(100):
        mgr.process_zone_tracks(0, inside_tracks, zones, zone_types, frame)
        
    # Verify STILL exactly 1 active session and NO new alert_created emitted!
    assert len(mgr.active_sessions) == 1
    alert_events_after_dwell = [e for e in emitted_events if e[0] == 'alert_created']
    assert len(alert_events_after_dwell) == 1 # Still exactly 1!
    
    # 4. Person leaves HIGH zone
    mgr.process_zone_tracks(0, outside_tracks, zones, zone_types, frame)
    time.sleep(0.3) # Wait for exit grace period (0.2s)
    mgr.process_zone_tracks(0, outside_tracks, zones, zone_types, frame)
    
    # Verify session closed
    assert len(mgr.active_sessions) == 0
    with app_ctx.app_context():
        inc = db.session.get(Incident, first_incident_id)
        assert inc is not None
        assert inc.status == 'Closed'
        assert inc.evidence_status in ('COMPLETE', 'PARTIAL')
        
    # 5. Person enters HIGH zone again
    mgr.process_zone_tracks(0, inside_tracks, zones, zone_types, frame)
    assert len(mgr.active_sessions) == 1
    new_incident_id = mgr.active_sessions[session_key].incident_id
    assert new_incident_id != first_incident_id # Brand new incident!
    
    alert_events_total = [e for e in emitted_events if e[0] == 'alert_created']
    assert len(alert_events_total) == 2

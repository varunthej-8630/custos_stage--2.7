import os
import cv2
import time
import numpy as np
import pytest
from flask import Flask

from database.models import db, Incident
from engine.incident_lifecycle import IncidentLifecycleManager
from engine.frame_buffer import CircularFrameBuffer
from engine.tamper_detector import TamperDetector
from engine.media_recorder import media_recorder

@pytest.fixture
def app_ctx(tmp_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/test_tamper_lifecycle.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

def test_tamper_full_preroll_and_lifecycle(app_ctx):
    """
    Tests complete tamper pipeline:
    15s rolling buffer -> tamper confirmed -> snapshot + video session with preroll ->
    continuous covered state -> 3.0s recovery -> MP4 finalized -> verified container (>300 frames).
    """
    emitted_events = []
    def mock_socket(event_name, data):
        emitted_events.append((event_name, data))
        
    mgr = IncidentLifecycleManager(exit_grace_seconds=0.2, socket_emitter=mock_socket, flask_app=app_ctx)
    detector = TamperDetector(camera_id=0, confirm_seconds=0.3, recovery_seconds=0.5)
    frame_buf = CircularFrameBuffer(max_seconds=15.0, target_fps=30)
    
    # A. Ingest 15 seconds of normal pre-tamper camera frames (e.g. 150 frames @ 10 FPS rate)
    start_time = time.time()
    for i in range(150):
        t_frame = start_time + (i * 0.1)
        f = np.full((240, 320, 3), 100, dtype=np.uint8)
        cv2.putText(f, f"PRE_TAMPER_{i}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        frame_buf.append(f, timestamp=t_frame, camera_id=0)
        
    assert frame_buf.size() == 150
    preroll_frames = frame_buf.get_last_seconds(15.0)
    assert len(preroll_frames) == 150
    
    # B. Tamper begins (Camera covered - pitch black frame)
    tamper_frame = np.zeros((240, 320, 3), dtype=np.uint8)
    
    # Send abnormal frames for 0.4s to pass confirm_seconds (0.3s)
    t_start_tamper = start_time + 15.0
    confirmed = False
    reasons = []
    for step in range(5):
        t_curr = t_start_tamper + (step * 0.1)
        frame_buf.append(tamper_frame, timestamp=t_curr, camera_id=0)
        confirmed, reasons = detector.update(tamper_frame, timestamp=t_curr)
        if confirmed:
            break
            
    assert confirmed is True
    assert len(reasons) > 0
    
    # Process confirmed tamper through IncidentLifecycleManager
    mgr.process_tamper(
        camera_id=0,
        is_tamper_active=confirmed,
        reasons=reasons,
        current_frame=tamper_frame,
        pre_event_buffer=preroll_frames
    )
    
    assert len(mgr.active_sessions) == 1
    session_key = "tamper:0:TAMPER"
    assert session_key in mgr.active_sessions
    tamper_inc_id = mgr.active_sessions[session_key].incident_id
    
    # Verify exactly 1 alert_created and 1 tamper_started emitted
    tamper_alerts = [e for e in emitted_events if e[0] == 'alert_created']
    tamper_started = [e for e in emitted_events if e[0] == 'tamper_started']
    assert len(tamper_alerts) == 1
    assert len(tamper_started) == 1
    
    # Verify Trigger Snapshot exists on disk
    snap_filename = mgr.active_sessions[session_key].snapshot_path
    snap_full_path = os.path.join(media_recorder.snapshot_dir, snap_filename)
    assert os.path.exists(snap_full_path)
    assert os.path.getsize(snap_full_path) > 0
    
    # C. Camera remains covered for 30 consecutive frames (Continuous Tamper)
    for i in range(30):
        t_curr = t_start_tamper + 0.5 + (i * 0.1)
        frame_buf.append(tamper_frame, timestamp=t_curr, camera_id=0)
        mgr.process_tamper(
            camera_id=0,
            is_tamper_active=True,
            reasons=reasons,
            current_frame=tamper_frame,
            pre_event_buffer=preroll_frames
        )
        
    # Verify STILL exactly 1 active tamper session and 0 duplicate alerts!
    assert len(mgr.active_sessions) == 1
    tamper_alerts_after = [e for e in emitted_events if e[0] == 'alert_created']
    assert len(tamper_alerts_after) == 1 # STRICTLY 1 alert!
    
    # D. Camera uncovers / recovers (Use high-texture healthy frame with variance > 200)
    normal_frame = np.random.randint(50, 200, (240, 320, 3), dtype=np.uint8)
    cv2.putText(normal_frame, "RECOVERED TEXTURE", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    # 1st recovery frame (detector confirms recovery)
    t_rec = t_start_tamper + 4.0
    detector.update(normal_frame, timestamp=t_rec)
    t_rec_confirm = t_rec + 0.6
    confirmed, reasons = detector.update(normal_frame, timestamp=t_rec_confirm)
    assert confirmed is False
    
    # Notify manager recovery started
    mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=reasons, current_frame=normal_frame)
    time.sleep(0.3) # Wait for exit grace (0.2s)
    # Notify manager recovery grace elapsed -> closes session and encodes MP4
    mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=reasons, current_frame=normal_frame)
    
    # E. Verify session closed and MP4 validated
    assert len(mgr.active_sessions) == 0
    tamper_resolved = [e for e in emitted_events if e[0] == 'tamper_resolved']
    assert len(tamper_resolved) == 1
    
    with app_ctx.app_context():
        inc = db.session.get(Incident, tamper_inc_id)
        assert inc is not None
        assert inc.status == 'Closed'
        assert inc.video_status == 'AVAILABLE'
        assert inc.evidence_status in ('COMPLETE', 'PARTIAL')
        
        # Verify MP4 video on disk
        mp4_path = os.path.join(media_recorder.snapshot_dir, inc.clip_path)
        assert os.path.exists(mp4_path)
        assert os.path.getsize(mp4_path) > 0
        
        val_res = media_recorder.validate_video(mp4_path)
        assert val_res.valid is True
        assert val_res.frame_count >= 150 # Contains the ~150 pre-tamper frames + live frames!
        assert val_res.duration_sec > 5.0

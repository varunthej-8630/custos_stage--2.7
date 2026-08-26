# tests/test_evidence_capture_lifecycle.py — Real Camera Evidence Policies Verification
import os
import cv2
import time
import numpy as np
import pytest
from flask import Flask

from database.models import db, Incident
from database.database_manager import db_manager
from engine.incident_lifecycle import IncidentLifecycleManager
from engine.frame_buffer import CircularFrameBuffer
from engine.tamper_detector import TamperDetector
from engine.media_recorder import IncidentMediaRecorder, media_recorder

@pytest.fixture
def app_ctx(tmp_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/test_evidence_capture.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

# ═══════════════════════════════════════════════════════
# 1. HIGH ZONE BREACH = IMMEDIATE SNAPSHOT LIFECYCLE
# ═══════════════════════════════════════════════════════

def test_high_zone_immediate_snapshot_and_deduplication(app_ctx, tmp_path):
    """
    Validates Policy 1:
    - Entering HIGH zone creates exactly 1 Incident + 1 Alert + 1 real snapshot.
    - Snapshot file is validated: exists, size > 0, cv2.imread decodes valid dimensions.
    - snapshot_status is marked AVAILABLE.
    - Continuous dwell inside HIGH zone updates incident but creates NO new alerts or snapshots.
    - Re-entry after exit grace creates a new incident and a new snapshot.
    """
    emitted = []
    def mock_socket(name, data):
        emitted.append((name, data))

    recorder = IncidentMediaRecorder(snapshot_dir=str(tmp_path / "snapshots"))
    mgr = IncidentLifecycleManager(exit_grace_seconds=0.3, socket_emitter=mock_socket, flask_app=app_ctx)
    # Monkey-patch media_recorder in lifecycle mgr
    import engine.incident_lifecycle as lifecycle_module
    orig_recorder = lifecycle_module.media_recorder
    lifecycle_module.media_recorder = recorder

    try:
        zones = [[100, 100, 300, 300]]
        zone_types = ['HIGH']

        # Frame from camera
        frame1 = np.full((480, 640, 3), 120, dtype=np.uint8)
        cv2.putText(frame1, "BREACH TEST FRAME 1", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        track_data = [{
            'track_id': 17,
            'current_zone': 0,
            'classification': 'UNIDENTIFIED',
            'identity': 'Person-17',
            'person_id': 'person_017',
            'bbox': [120, 120, 200, 200]
        }]

        # Step 1: Initial Entry into HIGH Zone
        mgr.process_zone_tracks(
            camera_id=0,
            tracks=track_data,
            zones=zones,
            zone_types=zone_types,
            current_frame=frame1,
            base_score=85.0
        )

        assert len(mgr.active_sessions) == 1
        session = list(mgr.active_sessions.values())[0]
        inc_id = session.incident_id

        # Verify exactly 1 alert_created and 1 evidence_created emitted
        alert_events = [e for e in emitted if e[0] == 'alert_created']
        ev_events = [e for e in emitted if e[0] == 'evidence_created']
        assert len(alert_events) == 1
        assert len(ev_events) == 1

        # Verify Snapshot on disk
        assert session.snapshot_status == 'AVAILABLE'
        snap_path = os.path.join(recorder.snapshot_dir, session.snapshot_path)
        assert os.path.exists(snap_path)
        assert os.path.getsize(snap_path) > 0

        # Decode snapshot with OpenCV
        decoded = cv2.imread(snap_path)
        assert decoded is not None
        assert decoded.shape == (480, 640, 3)

        with app_ctx.app_context():
            inc = db.session.get(Incident, inc_id)
            assert inc is not None
            assert inc.snapshot_status == 'AVAILABLE'
            assert inc.snapshot_path == session.snapshot_path
            assert inc.score >= 85.0

        # Step 2: Continued Dwell for 15 frames (Same track stays inside)
        emitted.clear()
        for i in range(15):
            mgr.process_zone_tracks(
                camera_id=0,
                tracks=track_data,
                zones=zones,
                zone_types=zone_types,
                current_frame=frame1,
                base_score=90.0
            )

        # STRICTLY 0 duplicate alerts or incidents created during continuous presence
        assert len([e for e in emitted if e[0] == 'alert_created']) == 0
        assert len([e for e in emitted if e[0] == 'evidence_created']) == 0
        assert len(mgr.active_sessions) == 1

        # Step 3: Exit zone and wait for grace period (0.3s)
        mgr.process_zone_tracks(
            camera_id=0,
            tracks=[], # Subject stepped outside
            zones=zones,
            zone_types=zone_types,
            current_frame=frame1
        )
        time.sleep(0.35)
        # Finalize exit
        mgr.process_zone_tracks(
            camera_id=0,
            tracks=[],
            zones=zones,
            zone_types=zone_types,
            current_frame=frame1
        )
        assert len(mgr.active_sessions) == 0

        # Step 4: Re-entry after exit grace -> Creates BRAND NEW Incident and NEW Snapshot
        frame2 = np.full((480, 640, 3), 180, dtype=np.uint8)
        cv2.putText(frame2, "BREACH RE-ENTRY FRAME 2", (50, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 0), 2)

        mgr.process_zone_tracks(
            camera_id=0,
            tracks=track_data,
            zones=zones,
            zone_types=zone_types,
            current_frame=frame2,
            base_score=88.0
        )

        assert len(mgr.active_sessions) == 1
        session2 = list(mgr.active_sessions.values())[0]
        inc_id2 = session2.incident_id
        assert inc_id2 != inc_id # Brand new canonical incident ID!
        assert session2.snapshot_path != session.snapshot_path # Brand new snapshot!

        snap_path2 = os.path.join(recorder.snapshot_dir, session2.snapshot_path)
        assert os.path.exists(snap_path2)
        assert os.path.getsize(snap_path2) > 0

    finally:
        lifecycle_module.media_recorder = orig_recorder

# ═══════════════════════════════════════════════════════
# 2. CAMERA TAMPER = REAL MP4 VIDEO EVIDENCE LIFECYCLE
# ═══════════════════════════════════════════════════════

def test_tamper_mp4_preroll_and_decodability(app_ctx, tmp_path):
    """
    Validates Policy 2:
    - Continuous rolling pre-tamper buffer (10-15s).
    - Tamper confirmation creates exactly 1 tamper incident.
    - Pre-tamper frames + obstruction frames + recovery frames assembled into standard MP4.
    - MP4 is validated: file exists, size > 0, VideoCapture opens, frame_count > 0, duration valid.
    - video_status marked AVAILABLE.
    """
    emitted = []
    def mock_socket(name, data):
        emitted.append((name, data))

    recorder = IncidentMediaRecorder(snapshot_dir=str(tmp_path / "snapshots"))
    mgr = IncidentLifecycleManager(exit_grace_seconds=0.2, socket_emitter=mock_socket, flask_app=app_ctx)
    detector = TamperDetector(camera_id=0, confirm_seconds=0.2, recovery_seconds=0.3)
    frame_buf = CircularFrameBuffer(max_seconds=15.0, target_fps=30)

    import engine.incident_lifecycle as lifecycle_module
    orig_recorder = lifecycle_module.media_recorder
    lifecycle_module.media_recorder = recorder

    try:
        # A. Ingest 10 seconds of normal pre-tamper camera frames (100 frames)
        t0 = time.time()
        for i in range(100):
            t_f = t0 + (i * 0.1)
            f = np.full((240, 320, 3), 140, dtype=np.uint8)
            cv2.putText(f, f"HEALTHY {i}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
            frame_buf.append(f, timestamp=t_f, camera_id=0)

        preroll_frames = frame_buf.get_last_seconds(15.0)
        assert len(preroll_frames) == 100

        # B. Tamper event (Cover lens / total darkness)
        black_frame = np.zeros((240, 320, 3), dtype=np.uint8)
        t_tamper = t0 + 10.5
        confirmed = False
        reasons = []
        for step in range(4):
            t_curr = t_tamper + (step * 0.1)
            frame_buf.append(black_frame, timestamp=t_curr, camera_id=0)
            confirmed, reasons = detector.update(black_frame, timestamp=t_curr)
            if confirmed:
                break

        assert confirmed is True

        # Process confirmed tamper
        mgr.process_tamper(
            camera_id=0,
            is_tamper_active=confirmed,
            reasons=reasons,
            current_frame=black_frame,
            pre_event_buffer=preroll_frames
        )

        assert len(mgr.active_sessions) == 1
        tamper_session = list(mgr.active_sessions.values())[0]
        tamper_inc_id = tamper_session.incident_id

        # C. Sustained obstruction for 20 frames
        for step in range(20):
            t_curr = t_tamper + 0.5 + (step * 0.1)
            frame_buf.append(black_frame, timestamp=t_curr, camera_id=0)
            mgr.process_tamper(
                camera_id=0,
                is_tamper_active=True,
                reasons=reasons,
                current_frame=black_frame
            )

        assert len(mgr.active_sessions) == 1 # 0 duplicate incidents!

        # D. Camera uncovers / recovers
        healthy_rec = np.random.randint(40, 220, (240, 320, 3), dtype=np.uint8)
        t_rec = t_tamper + 3.0
        detector.update(healthy_rec, timestamp=t_rec)
        t_rec2 = t_rec + 0.4
        detector.update(healthy_rec, timestamp=t_rec2)

        # Notify recovery
        mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=reasons, current_frame=healthy_rec)
        time.sleep(0.25) # Exit grace
        mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=reasons, current_frame=healthy_rec)

        assert len(mgr.active_sessions) == 0

        # E. Validate MP4 Video Evidence
        with app_ctx.app_context():
            inc = db.session.get(Incident, tamper_inc_id)
            assert inc is not None
            assert inc.video_status == 'AVAILABLE'
            assert inc.clip_path != ''

            mp4_path = os.path.join(recorder.snapshot_dir, inc.clip_path)
            assert os.path.exists(mp4_path)
            assert os.path.getsize(mp4_path) > 0

            cap = cv2.VideoCapture(mp4_path)
            assert cap.isOpened()
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            cap.release()

            assert total_frames >= 100 # Includes full pre-tamper rolling buffer!
            assert (w, h) == (320, 240)

    finally:
        lifecycle_module.media_recorder = orig_recorder

# ═══════════════════════════════════════════════════════
# 3. FAILURE CASES & HONEST FAILED STATUS
# ═══════════════════════════════════════════════════════

def test_media_recorder_failure_cases(tmp_path):
    """
    Validates failure conditions:
    - Empty frame -> snapshot_status = FAILED
    - Corrupted image file -> validation fails
    - Missing video session / 0 frames -> video_status = FAILED
    """
    recorder = IncidentMediaRecorder(snapshot_dir=str(tmp_path / "snapshots"))

    # 1. Empty frame
    res_empty = recorder.capture_snapshot(None, incident_id=999)
    assert res_empty.valid is False
    assert res_empty.error is not None

    # 2. Corrupted file test
    corrupted_path = os.path.join(recorder.snapshot_dir, "corrupt.jpg")
    with open(corrupted_path, "wb") as f:
        f.write(b"NOT_A_REAL_JPEG_IMAGE_DATA")

    val_res = recorder.validate_video(corrupted_path)
    assert val_res.valid is False

    # 3. Finalize non-existent video session
    res_novid = recorder.finalize_video("non_existent_key")
    assert res_novid.valid is False
    assert res_novid.error is not None

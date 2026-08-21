import os
import cv2
import time
import json
import numpy as np
import pytest
from flask import Flask

from database.models import db, Incident, User, UserRole, Evidence
from database.database_manager import db_manager
from engine.incident_lifecycle import IncidentLifecycleManager
from engine.media_recorder import media_recorder

def test_full_real_world_acceptance_lifecycle(tmp_path):
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{tmp_path}/acceptance.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['TESTING'] = True
    db.init_app(app)
    
    with app.app_context():
        db_manager.init_db(app)
        
        emitted_events = []
        def mock_socket(evt, data):
            emitted_events.append((evt, data))
            
        mgr = IncidentLifecycleManager(exit_grace_seconds=0.25, socket_emitter=mock_socket, flask_app=app)
        
        zones = [[100, 100, 400, 400]]
        zone_types = ['HIGH']
        
        # Frame generation helper simulating camera feed with person
        def make_camera_frame(has_person=True, x=200, y=200, w=80, h=150, is_tamper=False):
            if is_tamper:
                return np.zeros((480, 640, 3), dtype=np.uint8) # Dark/covered
            f = np.full((480, 640, 3), 40, dtype=np.uint8)
            cv2.rectangle(f, (100, 100), (400, 400), (40, 40, 220), 2)
            if has_person:
                cv2.rectangle(f, (x, y), (x+w, y+h), (0, 200, 255), -1)
                cv2.putText(f, "SUBJECT", (x, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
            return f
            
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 1: HIGH ZONE ENTRY
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 1] HIGH Zone Entry...")
        pre_frames = [make_camera_frame(has_person=False) for _ in range(10)]
        entry_frame = make_camera_frame(has_person=True, x=200, y=200)
        tracks_in = [{'track_id': 1, 'current_zone': 0, 'bbox': [200, 200, 280, 350], 'dwell_time': 0.0}]
        
        mgr.process_zone_tracks(
            camera_id=0,
            tracks=tracks_in,
            zones=zones,
            zone_types=zone_types,
            current_frame=entry_frame,
            pre_event_buffer=pre_frames,
            base_score=90.0
        )
        
        assert len(mgr.active_sessions) == 1
        session_key = "zone:0:Person-1:Zone-1 (HIGH):ZONE_BREACH"
        session = mgr.active_sessions[session_key]
        inc_id = session.incident_id
        
        # Verify 1 Alert created, 1 Evidence created
        alert_creations = [e for e in emitted_events if e[0] == 'alert_created']
        evidence_creations = [e for e in emitted_events if e[0] == 'evidence_created']
        assert len(alert_creations) == 1
        assert len(evidence_creations) == 1
        
        # Verify Snapshot on disk
        assert session.snapshot_status == 'AVAILABLE'
        snap_path = os.path.join(media_recorder.snapshot_dir, session.snapshot_path)
        assert os.path.exists(snap_path)
        test_img = cv2.imread(snap_path)
        assert test_img is not None
        assert test_img.shape == (480, 640, 3)
        print(f"  -> Snapshot Verified: {session.snapshot_path} ({os.path.getsize(snap_path)} bytes)")
        
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 2: PERSON STAYS INSIDE FOR EXTENDED TIME (DWELL)
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 2] Person Dwell in HIGH Zone (0 Duplicate Alerts)...")
        for i in range(60):
            dwell_frame = make_camera_frame(has_person=True, x=200 + (i%20), y=200)
            mgr.process_zone_tracks(
                camera_id=0,
                tracks=tracks_in,
                zones=zones,
                zone_types=zone_types,
                current_frame=dwell_frame,
                base_score=95.0
            )
            
        assert len(mgr.active_sessions) == 1 # Still 1 active session!
        alert_creations_after = [e for e in emitted_events if e[0] == 'alert_created']
        assert len(alert_creations_after) == 1 # STRICTLY 1 alert created!
        print("  -> Dwell Verified: Exactly 1 active Incident, 0 duplicate alerts.")
        
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 3: PERSON EXITS HIGH ZONE
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 3] Person Exits HIGH Zone...")
        tracks_out = [{'track_id': 1, 'current_zone': None, 'bbox': [20, 20, 80, 150]}]
        exit_frame = make_camera_frame(has_person=True, x=20, y=20)
        
        mgr.process_zone_tracks(0, tracks_out, zones, zone_types, exit_frame)
        time.sleep(0.35) # Wait for exit grace
        mgr.process_zone_tracks(0, tracks_out, zones, zone_types, exit_frame)
        
        assert len(mgr.active_sessions) == 0
        inc_record = db.session.get(Incident, inc_id)
        assert inc_record.status == 'Closed'
        assert inc_record.evidence_status in ('COMPLETE', 'PARTIAL')
        assert inc_record.video_status == 'AVAILABLE'
        
        # Verify MP4 video on disk
        vid_path = os.path.join(media_recorder.snapshot_dir, inc_record.clip_path)
        assert os.path.exists(vid_path)
        cap = cv2.VideoCapture(vid_path)
        assert cap.isOpened()
        frames_recorded = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        assert frames_recorded > 10
        cap.release()
        print(f"  -> Video Verified: {inc_record.clip_path} ({os.path.getsize(vid_path)} bytes, {frames_recorded} frames)")
        
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 4: PERSON ENTERS AGAIN -> NEW INCIDENT
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 4] Re-entry creates a brand new Incident...")
        mgr.process_zone_tracks(0, tracks_in, zones, zone_types, entry_frame)
        assert len(mgr.active_sessions) == 1
        new_inc_id = mgr.active_sessions[session_key].incident_id
        assert new_inc_id != inc_id
        print(f"  -> Re-entry Verified: New Incident #{new_inc_id} created.")
        
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 5, 6, 7: TAMPER DETECTION, DURATION & RECOVERY
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 5, 6, 7] Camera Tamper Lifecycle...")
        tamper_frame = make_camera_frame(is_tamper=True)
        mgr.process_tamper(
            camera_id=0,
            is_tamper_active=True,
            reasons=['SUDDEN DARKNESS / LENS COVERED'],
            current_frame=tamper_frame,
            pre_event_buffer=pre_frames
        )
        assert "tamper:0:TAMPER" in mgr.active_sessions
        tamper_inc = mgr.active_sessions["tamper:0:TAMPER"].incident_id
        
        # Continuous tamper
        for _ in range(30):
            mgr.process_tamper(
                camera_id=0,
                is_tamper_active=True,
                reasons=['SUDDEN DARKNESS / LENS COVERED'],
                current_frame=tamper_frame
            )
        assert len([e for e in emitted_events if e[0] == 'tamper_started']) == 1
        
        # Tamper recovers
        normal_frame = make_camera_frame(has_person=False)
        mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=[], current_frame=normal_frame)
        time.sleep(2.2)
        mgr.process_tamper(camera_id=0, is_tamper_active=False, reasons=[], current_frame=normal_frame)
        
        assert "tamper:0:TAMPER" not in mgr.active_sessions
        tamper_rec = db.session.get(Incident, tamper_inc)
        assert tamper_rec.status == 'Closed'
        assert tamper_rec.video_status == 'AVAILABLE'
        print(f"  -> Tamper Verified: Incident #{tamper_inc} closed with verified video {tamper_rec.clip_path}")
        
        # ═══════════════════════════════════════════════════════
        # MANDATORY TEST 8, 9: ALERT & EVIDENCE CENTER QUERY INTEGRATION
        # ═══════════════════════════════════════════════════════
        print("\n[TEST 8, 9] Database Queries & Stats Verification...")
        alerts_res = db_manager.query_alerts(app, {'severity': 'CRITICAL'})
        assert alerts_res['total'] >= 1
        
        ev_res = db_manager.query_evidence(app, {'type': 'breach'})
        assert ev_res['total'] >= 1
        
        astats = db_manager.get_alerts_stats(app)
        estats = db_manager.get_evidence_stats(app)
        assert astats['total_alerts'] >= 2
        assert estats['total_records'] >= 2
        assert estats['total_snapshots'] >= 2
        assert estats['total_clips'] >= 2
        print(f"  -> Query Stats Verified: Alerts={astats['total_alerts']} Evidence={estats['total_records']} Clips={estats['total_clips']}")
        
        print("\nALL MANDATORY REAL-WORLD ACCEPTANCE TESTS PASSED!")

# engine/incident_lifecycle.py — Canonical Incident Lifecycle & Deduplication Manager
import time
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple
import numpy as np

from config import settings as config
from engine.logger import app_logger
from engine.media_recorder import media_recorder
from engine.storage_queue import storage_queue

class IncidentSession:
    def __init__(
        self,
        session_key: str,
        incident_id: int,
        camera_id: int,
        incident_type: str,
        zone_name: str,
        subject_id: str,
        initial_score: float,
        initial_events: List[str],
        start_time: float
    ):
        self.session_key = session_key
        self.incident_id = incident_id
        self.camera_id = camera_id
        self.incident_type = incident_type
        self.zone_name = zone_name
        self.subject_id = subject_id
        self.score = initial_score
        self.events = list(initial_events)
        self.start_time = start_time
        self.last_seen = start_time
        self.exit_start_time: Optional[float] = None
        self.status = 'ACTIVE'
        self.snapshot_path = ''
        self.clip_path = ''
        self.snapshot_status = 'NONE'
        self.video_status = 'RECORDING'
        self.evidence_status = 'CAPTURING'
        self.last_timeline_emit = start_time
        self.timeline: List[Dict[str, Any]] = []

    def get_dwell_seconds(self) -> float:
        return max(0.0, self.last_seen - self.start_time)

class IncidentLifecycleManager:
    """
    Central Manager enforcing the Single Canonical Incident Rule:
    One Real-World Event -> ONE Incident -> ONE Alert -> ONE Evidence Session.
    
    Deduplication Keys:
      - Zone/Person: ("zone", camera_id, subject_id, zone_name, incident_type)
      - Tamper: ("tamper", camera_id, tamper_type, incident_type)
    """
    def __init__(self, exit_grace_seconds: float = 3.5, socket_emitter = None, flask_app = None):
        self.exit_grace_seconds = exit_grace_seconds
        self.socket_emitter = socket_emitter
        self.flask_app = flask_app
        self.active_sessions: Dict[str, IncidentSession] = {}
        self.lock = threading.Lock()
        self._next_synthetic_id = 1000

    def set_socket_emitter(self, emitter):
        self.socket_emitter = emitter

    def set_flask_app(self, app):
        self.flask_app = app

    def _generate_zone_key(self, camera_id: int, subject_id: str, zone_name: str, incident_type: str = 'BREACH') -> str:
        return f"zone:{camera_id}:{subject_id}:{zone_name}:{incident_type}"

    def _generate_tamper_key(self, camera_id: int, tamper_type: str = 'OBSTRUCTION', incident_type: str = 'TAMPER') -> str:
        return f"tamper:{camera_id}:{tamper_type}:{incident_type}"

    # ═══════════════════════════════════════════════════════
    # 1. ZONE & PERSON INCIDENT LIFECYCLE
    # ═══════════════════════════════════════════════════════

    def process_zone_tracks(
        self,
        camera_id: int,
        tracks: List[Dict[str, Any]],
        zones: List[List[int]],
        zone_types: List[str],
        current_frame: np.ndarray,
        pre_event_buffer: Optional[List[np.ndarray]] = None,
        base_score: float = 85.0
    ):
        """
        Evaluates active tracks inside HIGH / WATCH zones.
        Creates incidents on entry, maintains active sessions during dwell,
        and finalizes video / closes incidents upon verified exit.
        """
        now = time.time()
        active_zone_keys_this_frame = set()

        with self.lock:
            # Evaluate tracks for High Zone breaches and Suspicious Person detections
            for t in tracks:
                tid = t.get('track_id', 0)
                classification = t.get('classification', 'UNIDENTIFIED')
                subject_name = t.get('identity', f"Person-{tid}")
                person_id = t.get('person_id')
                subject_id = person_id or f"Person-{tid}"

                z_idx = t.get('current_zone')
                is_in_valid_zone = (z_idx is not None and 0 <= z_idx < len(zones))
                z_type = zone_types[z_idx] if is_in_valid_zone and z_idx < len(zone_types) else 'WATCH'
                is_high_breach = (is_in_valid_zone and z_type == getattr(config, 'ZONE_TYPE_HIGH', 'HIGH'))
                is_suspicious = (classification == 'SUSPICIOUS')

                if not is_high_breach and not is_suspicious:
                    continue

                if is_suspicious:
                    incident_type = 'SUSPICIOUS_PERSON'
                    zone_name = f"Zone-{z_idx+1} ({z_type})" if is_in_valid_zone else "Monitored Area"
                    session_key = f"suspicious:{camera_id}:{subject_id}:{incident_type}"
                    events_list = [f"SUSPICIOUS PERSON DETECTED: {subject_name}", f"Subject {subject_name} identified in {zone_name}"]
                    ai_summary = f"Suspicious individual {subject_name} detected in {zone_name}."
                    rec_action = "Verify security perimeter and track subject movements."
                else:
                    incident_type = 'ZONE_BREACH'
                    zone_name = f"Zone-{z_idx+1} (HIGH)"
                    session_key = self._generate_zone_key(camera_id, subject_id, zone_name, incident_type)
                    events_list = [f"Intrusion detected in {zone_name}", f"Subject {subject_name} entered restricted zone"]
                    ai_summary = f"Restricted {zone_name} breach by {subject_name}."
                    rec_action = "Dispatch security guard to verify perimeter breach."

                active_zone_keys_this_frame.add(session_key)
                session = self.active_sessions.get(session_key)

                # A. New Incident Trigger
                if not session:
                    if is_high_breach:
                        app_logger.warning(f"[ZONE_BREACH_CONFIRMED] camera={camera_id} zone={zone_name} subject={subject_name} (Track #{tid})")
                    elif is_suspicious:
                        app_logger.warning(f"[SUSPICIOUS_PERSON_CONFIRMED] camera={camera_id} subject={subject_name} (Track #{tid})")

                    # 1. Persist initial Incident row to database

                    initial_pkg = {
                        'camera_id': camera_id,
                        'zone_name': zone_name,
                        'score': base_score,
                        'reliability_score': 95.0,
                        'subject_id': subject_id,
                        'subject_dwell_time': 0.0,
                        'events': events_list,
                        'ai_summary': ai_summary,
                        'recommended_action': rec_action,
                        'timeline': [
                            {'step': 1, 'time': time.strftime("%H:%M:%S"), 'event': f"{incident_type.replace('_', ' ').title()}: {subject_name} in {zone_name}", 'severity': 'CRITICAL'}
                        ],
                        'snapshot_path': '',
                        'clip_path': '',
                        'status': 'Active'
                    }


                    # Synchronously or via DB Manager get canonical ID
                    from database.database_manager import db_manager
                    inc_id = db_manager.save_incident(self.flask_app, initial_pkg)
                    if not inc_id:
                        self._next_synthetic_id += 1
                        inc_id = self._next_synthetic_id

                    # 2. Capture and verify trigger snapshot
                    snap_res = media_recorder.capture_snapshot(current_frame, inc_id, prefix='incident')
                    snapshot_filename = snap_res.file_name if snap_res.valid else ''
                    snap_status = 'AVAILABLE' if snap_res.valid else 'FAILED'

                    # 3. Start Video Session with pre-event buffer
                    media_recorder.start_video_session(session_key, inc_id, pre_event_buffer)

                    # 4. Create Session Object
                    session = IncidentSession(
                        session_key=session_key,
                        incident_id=inc_id,
                        camera_id=camera_id,
                        incident_type=incident_type,
                        zone_name=zone_name,
                        subject_id=subject_id,
                        initial_score=base_score,
                        initial_events=events_list,
                        start_time=now
                    )
                    session.snapshot_path = snapshot_filename
                    session.snapshot_status = snap_status
                    session.timeline = initial_pkg['timeline']
                    self.active_sessions[session_key] = session

                    # 5. Update DB with snapshot & statuses
                    db_manager.update_incident_lifecycle(
                        self.flask_app,
                        inc_id,
                        snapshot_path=snapshot_filename,
                        snapshot_status=snap_status,
                        video_status='RECORDING',
                        evidence_status='CAPTURING',
                        status='Active'
                    )

                    # 6. Emit Socket.IO Events
                    alert_dict = db_manager.get_alert_by_id(self.flask_app, inc_id)
                    evidence_dict = db_manager.get_evidence_by_id(self.flask_app, inc_id)
                    if self.socket_emitter:
                        if alert_dict: self.socket_emitter('alert_created', alert_dict)
                        if evidence_dict: self.socket_emitter('evidence_created', evidence_dict)

                    app_logger.warning(f"[INCIDENT_CREATED] #{inc_id} ({session_key}) Score: {base_score} Snapshot: {snapshot_filename or 'FAILED'}")
                    app_logger.info(f"[ALERT_CREATED] #{inc_id} Alert Center synchronized")

                # B. Existing Active Incident Update (DWELL / STAYING INSIDE)
                else:
                    session.last_seen = now
                    session.exit_start_time = None # Reset exit timer if subject was briefly flickering
                    session.score = max(session.score, base_score)
                    media_recorder.append_frame(session_key, current_frame)

                    dwell_sec = session.get_dwell_seconds()

                    # Throttled timeline update (every 8 seconds of continuous dwell)
                    if now - session.last_timeline_emit >= 8.0:
                        session.last_timeline_emit = now
                        time_str = time.strftime("%H:%M:%S")
                        step_num = len(session.timeline) + 1
                        session.timeline.append({
                            'step': step_num,
                            'time': time_str,
                            'event': f"Sustained presence in {session.zone_name}: {round(dwell_sec, 1)}s dwell",
                            'severity': 'HIGH'
                        })

                        from database.database_manager import db_manager
                        db_manager.update_incident_lifecycle(
                            self.flask_app,
                            session.incident_id,
                            dwell_time=dwell_sec,
                            score=session.score,
                            timeline=session.timeline
                        )

                        if self.socket_emitter:
                            self.socket_emitter('incident_updated', {
                                'id': session.incident_id,
                                'dwell_time': round(dwell_sec, 1),
                                'score': session.score,
                                'timeline': session.timeline
                            })

                        app_logger.info(f"[INCIDENT_UPDATED] #{session.incident_id} Dwell: {round(dwell_sec, 1)}s (No duplicate alerts generated)")

            # Check for Exits / Inactive Zone Sessions
            sessions_to_close = []
            for key, session in list(self.active_sessions.items()):
                if not key.startswith("zone:"):
                    continue

                if key not in active_zone_keys_this_frame:
                    if session.exit_start_time is None:
                        session.exit_start_time = now

                    # Still append trailing exit frames to video
                    media_recorder.append_frame(key, current_frame)

                    # Check exit grace period
                    if (now - session.exit_start_time) >= self.exit_grace_seconds:
                        sessions_to_close.append((key, session))

            # Finalize and close exited sessions
            for key, session in sessions_to_close:
                self._finalize_and_close_session(key, session, exit_reason="Subject exited restricted zone")

    # ═══════════════════════════════════════════════════════
    # 2. CAMERA TAMPER LIFECYCLE
    # ═══════════════════════════════════════════════════════

    def process_tamper(
        self,
        camera_id: int,
        is_tamper_active: bool,
        reasons: List[str],
        current_frame: np.ndarray,
        pre_event_buffer: Optional[List[np.ndarray]] = None
    ):
        """
        Manages Tamper Incident Lifecycle:
        - Tamper begins: Exactly 1 tamper incident created, snapshot + video session started.
        - Tamper continues: Updates duration/timeline, 0 duplicate alerts.
        - Tamper recovers: Closes incident, finalizes video, verifies MP4 on disk.
        """
        now = time.time()
        session_key = f"tamper:{camera_id}:TAMPER"

        with self.lock:
            session = self.active_sessions.get(session_key)

            # A. Tamper Triggered (New Tamper Incident)
            if is_tamper_active and not session:
                events_list = [f"CAMERA TAMPER: {r}" for r in reasons] or ["CAMERA TAMPER: Lens obstruction detected"]
                initial_pkg = {
                    'camera_id': camera_id,
                    'zone_name': 'Camera Hardware Lens',
                    'score': 100.0,
                    'reliability_score': 98.0,
                    'subject_id': 'System-Tamper',
                    'subject_dwell_time': 0.0,
                    'events': events_list,
                    'ai_summary': f"Camera {camera_id} obstructed: {', '.join(reasons)}.",
                    'recommended_action': "Inspect physical camera mount and clear optical lens obstruction.",
                    'timeline': [
                        {'step': 1, 'time': time.strftime("%H:%M:%S"), 'event': f"Tamper obstruction confirmed: {', '.join(reasons)}", 'severity': 'CRITICAL'}
                    ],
                    'snapshot_path': '',
                    'clip_path': '',
                    'status': 'Active'
                }

                from database.database_manager import db_manager
                inc_id = db_manager.save_incident(self.flask_app, initial_pkg)
                if not inc_id:
                    self._next_synthetic_id += 1
                    inc_id = self._next_synthetic_id

                # Capture & verify tamper snapshot
                snap_res = media_recorder.capture_snapshot(current_frame, inc_id, prefix='tamper')
                snap_filename = snap_res.file_name if snap_res.valid else ''
                snap_status = 'AVAILABLE' if snap_res.valid else 'FAILED'

                # Start tamper video session preserving pre-tamper frames
                media_recorder.start_video_session(session_key, inc_id, pre_event_buffer)

                session = IncidentSession(
                    session_key=session_key,
                    incident_id=inc_id,
                    camera_id=camera_id,
                    incident_type='TAMPER',
                    zone_name='Camera Hardware Lens',
                    subject_id='System-Tamper',
                    initial_score=100.0,
                    initial_events=events_list,
                    start_time=now
                )
                session.snapshot_path = snap_filename
                session.snapshot_status = snap_status
                session.timeline = initial_pkg['timeline']
                self.active_sessions[session_key] = session

                # Update DB
                db_manager.update_incident_lifecycle(
                    self.flask_app,
                    inc_id,
                    snapshot_path=snap_filename,
                    snapshot_status=snap_status,
                    video_status='RECORDING',
                    evidence_status='CAPTURING',
                    status='Active'
                )

                # Emit Socket.IO
                alert_dict = db_manager.get_alert_by_id(self.flask_app, inc_id)
                evidence_dict = db_manager.get_evidence_by_id(self.flask_app, inc_id)
                if self.socket_emitter:
                    if alert_dict: self.socket_emitter('alert_created', alert_dict)
                    if evidence_dict: self.socket_emitter('evidence_created', evidence_dict)
                    self.socket_emitter('tamper_started', {'camera_id': camera_id, 'incident_id': inc_id, 'reasons': reasons})

                app_logger.warning(f"[TAMPER_STARTED] Camera {camera_id} Tamper #{inc_id}: {', '.join(reasons)}")
                app_logger.info(f"[TAMPER_INCIDENT_CREATED] incident_id={inc_id}")

            # B. Tamper Continues (Continuous Obstruction)
            elif is_tamper_active and session:
                session.last_seen = now
                session.exit_start_time = None
                media_recorder.append_frame(session_key, current_frame)

                # Periodic timeline update for prolonged tamper
                if now - session.last_timeline_emit >= 10.0:
                    session.last_timeline_emit = now
                    dwell_sec = session.get_dwell_seconds()
                    session.timeline.append({
                        'step': len(session.timeline) + 1,
                        'time': time.strftime("%H:%M:%S"),
                        'event': f"Camera obstruction ongoing ({round(dwell_sec, 1)}s elapsed)",
                        'severity': 'HIGH'
                    })
                    from database.database_manager import db_manager
                    db_manager.update_incident_lifecycle(
                        self.flask_app,
                        session.incident_id,
                        dwell_time=dwell_sec,
                        timeline=session.timeline
                    )
                    app_logger.info(f"[TAMPER_UPDATED] #{session.incident_id} Continuous obstruction ({round(dwell_sec, 1)}s) — 0 duplicate alerts")

            # C. Tamper Recovered
            elif not is_tamper_active and session:
                if session.exit_start_time is None:
                    session.exit_start_time = now

                media_recorder.append_frame(session_key, current_frame)

                recovery_grace = getattr(self, 'exit_grace_seconds', 2.0)
                if (now - session.exit_start_time) >= recovery_grace:
                    self._finalize_and_close_session(session_key, session, exit_reason="Camera view restored to normal")
                    if self.socket_emitter:
                        self.socket_emitter('tamper_resolved', {'camera_id': camera_id, 'incident_id': session.incident_id})
                    app_logger.info(f"[TAMPER_RESOLVED] Camera {camera_id} Incident #{session.incident_id} recovered")

    # ═══════════════════════════════════════════════════════
    # 3. SESSION FINALIZATION & MEDIA ENCODING
    # ═══════════════════════════════════════════════════════

    def _finalize_and_close_session(self, session_key: str, session: IncidentSession, exit_reason: str):
        """
        Finalizes MP4 video, validates container, updates Evidence & Incident records, and emits updates.
        """
        prefix = 'tamper' if session.incident_type == 'TAMPER' else 'incident'
        vid_res = media_recorder.finalize_video(session_key, fps=20, prefix=prefix)

        clip_filename = vid_res.file_name if vid_res.valid else ''
        video_status = 'AVAILABLE' if vid_res.valid else 'FAILED'
        evidence_status = 'COMPLETE' if (session.snapshot_status == 'AVAILABLE' and vid_res.valid) else 'PARTIAL' if (session.snapshot_status == 'AVAILABLE' or vid_res.valid) else 'FAILED'

        session.status = 'CLOSED'
        session.clip_path = clip_filename
        session.video_status = video_status
        session.evidence_status = evidence_status

        # Append closure step to timeline
        session.timeline.append({
            'step': len(session.timeline) + 1,
            'time': time.strftime("%H:%M:%S"),
            'event': f"{exit_reason} — Incident closed and evidence finalized",
            'severity': 'LOW'
        })

        from database.database_manager import db_manager
        db_manager.close_incident_lifecycle(
            self.flask_app,
            session.incident_id,
            clip_path=clip_filename,
            video_status=video_status,
            evidence_status=evidence_status,
            dwell_time=session.get_dwell_seconds(),
            timeline=session.timeline
        )

        # Remove from active map so future entries/tampers create a brand new Incident
        self.active_sessions.pop(session_key, None)

        # Broadcast update over Socket.IO
        evidence_dict = db_manager.get_evidence_by_id(self.flask_app, session.incident_id)
        alert_dict = db_manager.get_alert_by_id(self.flask_app, session.incident_id)
        if self.socket_emitter:
            if evidence_dict: self.socket_emitter('evidence_updated', evidence_dict)
            if alert_dict: self.socket_emitter('alert_updated', alert_dict)
            self.socket_emitter('incident_closed', {'incident_id': session.incident_id, 'camera_id': session.camera_id})

        app_logger.info(f"[INCIDENT_CLOSED] #{session.incident_id} Video: {clip_filename or 'FAILED'} Status: {evidence_status}")
        if session.incident_type == 'TAMPER':
            app_logger.info(f"[TAMPER_INCIDENT_CLOSED] incident_id={session.incident_id}")

incident_lifecycle_mgr = IncidentLifecycleManager()

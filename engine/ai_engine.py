# engine/ai_engine.py — CUSTOS 2.8 Unified AI Vision, Face Intelligence & Behavior Engine
import os
import cv2
import time
from typing import List, Dict, Any, Tuple, Optional
import numpy as np

from config import settings as config
from engine.logger import app_logger
from engine.perception_engine import PerceptionEngine
from engine.tracking_engine import TrackingEngine, MultiObjectTracker
from engine.zone_monitor import ZoneMonitor
from engine.behavior_analyzer import BehaviorAnalyzer, BehaviorStatus
from engine.risk_engine import RiskEngine
from engine.person_memory import person_memory_mgr
from engine.face_engine import face_engine


class AIEngine:
    """
    Unified AI Engine coordinating Perception, Multi-Object Tracking,
    Face Recognition & Identity Caching, Zone Analysis, Behavior Lifecycle,
    and Deterministic Risk Evaluation.
    """
    def __init__(self):
        self.perception = PerceptionEngine()
        self.tracking = TrackingEngine()
        self.zone_monitor = ZoneMonitor()
        self.behavior_analyzer = BehaviorAnalyzer()
        self.risk_engine = RiskEngine()
        
        self.flask_app = None
        self.socket_emitter = None

        self._last_dets: List[Dict[str, Any]] = []
        self._last_inference_time = 0.0
        self._frame_counter = 0
        app_logger.info("[AI ENGINE] Initialized CUSTOS 2.8 Modular Perception, Face Intelligence & Behavior Architecture")

    def set_app(self, app):
        self.flask_app = app
        face_engine.refresh_cache(app)

    def set_socket_emitter(self, emitter):
        self.socket_emitter = emitter

    def process_frame(
        self,
        frame: np.ndarray,
        frame_count: int,
        zones: List[List[int]],
        zone_types: List[str],
        monitoring: bool = True,
        tamper: bool = False,
        detections: Optional[List[Dict[str, Any]]] = None,
        camera_id: int = 0
    ) -> Tuple[float, List[str], bool, List[Dict[str, Any]]]:
        """
        Executes end-to-end frame intelligence through the modular pipeline stages.
        """
        self._frame_counter += 1
        if not monitoring or not zones:
            return 0.0, [], False, []

        # 1. Perception (with frame-skipping if configured)
        if detections is not None:
            person_dets = [d for d in detections if d.get('class_id', 0) == config.CLASS_PERSON]
            self._last_dets = person_dets
        else:
            skip = getattr(config, 'FRAME_SKIP', 2)
            if frame_count % skip == 0 or not self._last_dets:
                all_dets = self.perception.detect(frame)
                person_dets = [d for d in all_dets if d.get('class_id') == config.CLASS_PERSON]
                self._last_dets = person_dets
            else:
                person_dets = self._last_dets

        # 2. Multi-Object Tracking
        tracks = self.tracking.process(person_dets)

        # 3. Zone Analysis (Deterministic membership & dwell)
        tracks = self.zone_monitor.evaluate_tracks(tracks, zones, zone_types)

        # 4. Face Recognition & Real Identity Caching (per active track)
        for track in tracks:
            tid = track.get('track_id', 0)
            mem = person_memory_mgr.get_or_create(tid)
            mem.update_position(
                track.get('cx', 0),
                track.get('cy', 0),
                track.get('foot_x', 0),
                track.get('foot_y', 0)
            )
            mem.update_zone(track.get('current_zone'))
            mem.record_risk(track.get('dwell_time', 0.0))

            tbox = track.get('bbox', track.get('box', []))

            # Only run face recognition if not already locked on this track
            if mem.should_attempt_face_recognition(min_interval_sec=1.0) and tbox and len(tbox) == 4:
                rec_result = face_engine.recognize_person_in_bbox(frame, tbox, app=self.flask_app)
                status = rec_result.get('status', 'UNIDENTIFIED')

                if status != 'UNIDENTIFIED':
                    # Lock identity to this active track (prevents continuous unnecessary re-recognition)
                    mem.set_identity(rec_result, lock=True)

                    # Check if appearance record needs to be logged
                    if not mem.identity.get('appearance_logged', False) and self.flask_app:
                        from database.database_manager import db_manager
                        z_idx = track.get('current_zone')
                        z_name = f"Zone-{z_idx+1} ({zone_types[z_idx]})" if (z_idx is not None and z_idx < len(zone_types)) else "Observation Area"

                        # Save appearance snapshot
                        snap_rel_path = None
                        face_crop = rec_result.get('face_crop')
                        if face_crop is not None and face_crop.size > 0:
                            app_dir = getattr(config, 'PEOPLE_APPEARANCES_DIR', 'data/people/appearances')
                            os.makedirs(app_dir, exist_ok=True)
                            snap_name = f"app_cam{camera_id}_track{tid}_{int(time.time())}.jpg"
                            snap_path = os.path.join(app_dir, snap_name)
                            cv2.imwrite(snap_path, face_crop)
                            snap_rel_path = snap_path

                        app_id = db_manager.log_person_appearance(
                            app=self.flask_app,
                            camera_id=camera_id,
                            track_id=tid,
                            person_id=mem.identity.get('person_id'),
                            cluster_id=mem.identity.get('cluster_id'),
                            zone_name=z_name,
                            recognition_score=mem.identity.get('recognition_score', 0.0),
                            identity_status=mem.identity.get('classification', 'UNKNOWN'),
                            snapshot_path=snap_rel_path
                        )
                        mem.identity['appearance_logged'] = True

                        # Real-time event notifications via Socket.IO
                        if self.socket_emitter:
                            payload = {
                                'appearance_id': app_id,
                                'camera_id': camera_id,
                                'track_id': tid,
                                'person_id': mem.identity.get('person_id'),
                                'cluster_id': mem.identity.get('cluster_id'),
                                'name': mem.identity.get('label'),
                                'classification': mem.identity.get('classification'),
                                'score': mem.identity.get('recognition_score'),
                                'zone': z_name,
                                'timestamp': time.strftime("%H:%M:%S")
                            }
                            self.socket_emitter('person_appearance', payload)
                            if mem.identity.get('classification') == 'KNOWN':
                                self.socket_emitter('person_recognized', payload)
                            elif mem.identity.get('classification') == 'SUSPICIOUS':
                                self.socket_emitter('suspicious_person_detected', payload)

            # Copy cached identity context to track
            track['identity'] = mem.identity.get('label', f'Person-{tid}')
            track['person_id'] = mem.identity.get('person_id')
            track['cluster_id'] = mem.identity.get('cluster_id')
            track['classification'] = mem.identity.get('classification', 'UNIDENTIFIED')
            track['recognition_score'] = mem.identity.get('recognition_score', 0.0)
            track['identity_status'] = mem.identity.get('status', 'UNIDENTIFIED')

        person_memory_mgr.purge_stale()

        # 5. Behavior Analysis (Separates Validated vs Experimental vs Disabled)
        behavior_output = self.behavior_analyzer.process(
            tracks=tracks,
            context={'zones': zones, 'zone_types': zone_types}
        )
        validated_behaviors = behavior_output['validated']
        enriched_tracks = behavior_output['tracks']

        # 6. Risk Engine Evaluation (Consumes strictly validated signals & identity context)
        score, reasons, alert_active = self.risk_engine.evaluate(
            tracks=enriched_tracks,
            validated_behaviors=validated_behaviors,
            zones=zones,
            zone_types=zone_types,
            tamper=tamper
        )

        return score, reasons, alert_active, enriched_tracks

    def get_telemetry(self) -> Dict[str, Any]:
        """Returns comprehensive debug telemetry for AI processing."""
        p_info = self.perception.get_model_info()
        return {
            'model_name': p_info['model_name'],
            'model_path': p_info['model_path'],
            'confidence_threshold': p_info['confidence_threshold'],
            'inference_latency_ms': p_info['latency_ms'],
            'active_tracks': len(self.tracking.tracker.tracks),
            'analyzers': self.behavior_analyzer.get_analyzer_status(),
            'risk_mode': self.risk_engine.mode,
            'current_risk_score': self.risk_engine.score,
            'current_reasons': list(self.risk_engine.reasons)
        }


ai_engine = AIEngine()

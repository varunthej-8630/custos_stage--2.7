# engine/ai_engine.py — CUSTOS 2.6 Unified AI Vision & Behavior Engine
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


class AIEngine:
    """
    Unified AI Engine coordinating Perception, Multi-Object Tracking,
    Zone Analysis, Behavior Lifecycle, and Deterministic Risk Evaluation.
    """
    def __init__(self):
        self.perception = PerceptionEngine()
        self.tracking = TrackingEngine()
        self.zone_monitor = ZoneMonitor()
        self.behavior_analyzer = BehaviorAnalyzer()
        self.risk_engine = RiskEngine()
        
        self._last_dets: List[Dict[str, Any]] = []
        self._last_inference_time = 0.0
        self._frame_counter = 0
        app_logger.info("[AI ENGINE] Initialized CUSTOS 2.6 Modular Perception & Behavior Architecture")

    def process_frame(
        self,
        frame: np.ndarray,
        frame_count: int,
        zones: List[List[int]],
        zone_types: List[str],
        monitoring: bool = True,
        tamper: bool = False,
        detections: Optional[List[Dict[str, Any]]] = None
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

        # 4. Behavior Analysis (Separates Validated vs Experimental vs Disabled)
        behavior_output = self.behavior_analyzer.process(
            tracks=tracks,
            context={'zones': zones, 'zone_types': zone_types}
        )
        validated_behaviors = behavior_output['validated']
        enriched_tracks = behavior_output['tracks']

        # 5. Person Memory Updates
        for track in enriched_tracks:
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

        person_memory_mgr.purge_stale()

        # 6. Risk Engine Evaluation (Consumes strictly validated signals)
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

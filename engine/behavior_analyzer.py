# engine/behavior_analyzer.py — CUSTOS 2.6 Modular Behavior Analysis Layer
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from config import settings as config


class BehaviorStatus(str, Enum):
    DISABLED = "DISABLED"
    EXPERIMENTAL = "EXPERIMENTAL"
    VALIDATED = "VALIDATED"


@dataclass
class BehaviorResult:
    """Standardized result structure for all behavior analyzers."""
    behavior_name: str
    confidence: float
    status: BehaviorStatus
    track_id: int
    duration: float = 0.0
    evidence: Dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            'behavior_name': self.behavior_name,
            'confidence': round(self.confidence, 3),
            'status': self.status.value,
            'track_id': self.track_id,
            'duration': round(self.duration, 2),
            'evidence': self.evidence,
            'reason': self.reason,
            'timestamp': self.timestamp
        }


class BaseAnalyzer:
    """Base class for behavior analyzers."""
    def __init__(self, name: str, status: BehaviorStatus):
        self.name = name
        self.status = status

    def analyze(self, track: Dict[str, Any], context: Dict[str, Any]) -> Optional[BehaviorResult]:
        raise NotImplementedError


class PostureAnalyzer(BaseAnalyzer):
    """
    Evaluates human posture.
    STATUS: DISABLED (Unvalidated bbox shrink heuristics produce false alarms; requires PoseEngine).
    """
    def __init__(self):
        super().__init__("crouching", BehaviorStatus.DISABLED)

    def analyze(self, track: Dict[str, Any], context: Dict[str, Any]) -> Optional[BehaviorResult]:
        if self.status == BehaviorStatus.DISABLED:
            return None
        # Placeholder for future PoseEngine keypoint evaluation
        return None


class MotionAnalyzer(BaseAnalyzer):
    """
    Evaluates complex motion patterns (pacing, erratic, freeze).
    STATUS: DISABLED (Unvalidated 2D centroid reversals produce false alarms on bbox jitter).
    """
    def __init__(self):
        super().__init__("motion_patterns", BehaviorStatus.DISABLED)

    def analyze(self, track: Dict[str, Any], context: Dict[str, Any]) -> Optional[BehaviorResult]:
        if self.status == BehaviorStatus.DISABLED:
            return None
        return None


class DwellAnalyzer(BaseAnalyzer):
    """
    Evaluates stationary dwell time within a spatial bounding radius.
    STATUS: EXPERIMENTAL (Observational only; does not elevate production risk without zone breach).
    """
    def __init__(self):
        super().__init__("loitering", BehaviorStatus.EXPERIMENTAL)
        self.dwell_radius_px = getattr(config, 'DWELL_RADIUS_PX', 50)
        self.min_dwell_sec = getattr(config, 'DWELL_WARN_SEC', 10.0)

    def analyze(self, track: Dict[str, Any], context: Dict[str, Any]) -> Optional[BehaviorResult]:
        traj = track.get('trajectory', [])
        if len(traj) < 10:
            return None

        # Calculate spatial spread over past trajectory
        xs = [p[0] for p in traj]
        ys = [p[1] for p in traj]
        spread_x = max(xs) - min(xs)
        spread_y = max(ys) - min(ys)
        spatial_diameter = (spread_x**2 + spread_y**2) ** 0.5

        t_start = traj[0][2]
        t_end = traj[-1][2]
        elapsed = max(0.0, t_end - t_start)

        # If person stayed within bounded radius for > min_dwell_sec
        if spatial_diameter <= self.dwell_radius_px and elapsed >= self.min_dwell_sec:
            conf = min(1.0, elapsed / 30.0)
            return BehaviorResult(
                behavior_name="loitering",
                confidence=conf,
                status=self.status,
                track_id=track.get('track_id', 0),
                duration=elapsed,
                evidence={
                    'spatial_diameter_px': round(spatial_diameter, 1),
                    'dwell_duration_sec': round(elapsed, 1),
                    'radius_limit_px': self.dwell_radius_px
                },
                reason=f"Stationary dwell within {self.dwell_radius_px}px radius for {elapsed:.1f}s"
            )
        return None


class ZoneTransitionAnalyzer(BaseAnalyzer):
    """
    Evaluates HIGH and WATCH zone entry, residency, and breach.
    STATUS: VALIDATED (Deterministic polygon/rectangle membership).
    """
    def __init__(self):
        super().__init__("zone_entry", BehaviorStatus.VALIDATED)

    def analyze(self, track: Dict[str, Any], context: Dict[str, Any]) -> Optional[BehaviorResult]:
        zone_idx = track.get('current_zone')
        if zone_idx is None:
            return None

        zone_types = context.get('zone_types', [])
        zone_type = zone_types[zone_idx] if zone_idx < len(zone_types) else 'WATCH'
        dwell_time = track.get('dwell_time', 0.0)
        tid = track.get('track_id', 0)

        if zone_type == config.ZONE_TYPE_HIGH:
            return BehaviorResult(
                behavior_name="high_zone_entry",
                confidence=1.0,
                status=self.status,
                track_id=tid,
                duration=dwell_time,
                evidence={'zone_index': zone_idx, 'zone_type': 'HIGH'},
                reason=f"HIGH security zone #{zone_idx + 1} breach"
            )
        else:
            return BehaviorResult(
                behavior_name="watch_zone_entry",
                confidence=0.8,
                status=self.status,
                track_id=tid,
                duration=dwell_time,
                evidence={'zone_index': zone_idx, 'zone_type': 'WATCH', 'dwell_time': dwell_time},
                reason=f"WATCH zone #{zone_idx + 1} entry (dwell {dwell_time:.1f}s)"
            )


class BehaviorAnalyzer:
    """
    Modular Behavior Analyzer coordinating all behavior sub-analyzers.
    Guarantees strict separation between VALIDATED, EXPERIMENTAL, and DISABLED behaviors.
    """
    def __init__(self):
        self.analyzers: List[BaseAnalyzer] = [
            PostureAnalyzer(),
            MotionAnalyzer(),
            DwellAnalyzer(),
            ZoneTransitionAnalyzer()
        ]
        self.enable_experimental = getattr(config, 'ENABLE_EXPERIMENTAL_BEHAVIORS', False)

    def process(self, tracks: List[Dict[str, Any]], context: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Evaluates active tracks through all analyzers.
        
        :param tracks: List of track state dictionaries from TrackingEngine
        :param context: Dictionary containing 'zones', 'zone_types', etc.
        :return: Dict containing:
            - 'validated': List[BehaviorResult] (ONLY these may affect production risk)
            - 'experimental': List[BehaviorResult] (Debug telemetry only)
            - 'all': List[BehaviorResult]
            - 'tracks': List[Dict] with embedded behavior flags
        """
        context = context or {}
        validated_results: List[BehaviorResult] = []
        experimental_results: List[BehaviorResult] = []
        all_results: List[BehaviorResult] = []

        enriched_tracks = []
        for track in tracks:
            t_copy = dict(track)
            t_copy['behaviors'] = []
            
            for analyzer in self.analyzers:
                if analyzer.status == BehaviorStatus.DISABLED:
                    continue
                res = analyzer.analyze(track, context)
                if res:
                    all_results.append(res)
                    t_copy['behaviors'].append(res.behavior_name)
                    if res.status == BehaviorStatus.VALIDATED:
                        validated_results.append(res)
                    elif res.status == BehaviorStatus.EXPERIMENTAL:
                        experimental_results.append(res)
            enriched_tracks.append(t_copy)

        return {
            'validated': validated_results,
            'experimental': experimental_results,
            'all': all_results,
            'tracks': enriched_tracks
        }

    def get_analyzer_status(self) -> List[Dict[str, str]]:
        """Returns telemetry describing the active lifecycle status of each analyzer."""
        return [
            {
                'behavior': a.name,
                'status': a.status.value,
                'affects_production_risk': "YES" if a.status == BehaviorStatus.VALIDATED else "NO"
            }
            for a in self.analyzers
        ]

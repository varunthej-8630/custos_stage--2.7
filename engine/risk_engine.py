# engine/risk_engine.py — CUSTOS 2.8 Deterministic & Explainable Risk Engine with People Intelligence
import time
from typing import List, Dict, Any, Tuple, Optional

from config import settings as config
from engine.logger import app_logger
from engine.behavior_analyzer import BehaviorResult, BehaviorStatus


class RiskEngine:
    """
    Deterministic & Explainable Risk Scoring Engine.
    Consumes strictly VALIDATED security signals and Identity Classifications:
      - Camera Tamper: Highest priority (100.0 score, independent).
      - Suspicious Person: Direct security signal escalation (SUSPICIOUS_PERSON_DETECTED).
      - Restricted High Zone: Evaluated for all persons (including Known/Unknown).
      - Observation Watch Zone: Dwell-based evaluation.
    """
    def __init__(self):
        self.score = 0.0
        self.last_update = time.time()
        self.mode = 'DAY'
        self._last_activity = time.time()
        self._above_threshold_since: Optional[float] = None
        self.reasons: List[str] = []
        self.event_log: List[str] = []

    def set_mode(self, mode: str):
        if mode in ('DAY', 'GUARD') and mode != self.mode:
            self.mode = mode
            app_logger.info(f'Mode → {mode}')

    def auto_check_mode(self):
        now = time.time()
        idle = (now - self._last_activity) / 60.0
        if idle >= getattr(config, 'AUTO_GUARD_IDLE_MIN', 30) and self.mode != 'GUARD':
            self.mode = 'GUARD'
            app_logger.info(f'Auto GUARD MODE (idle {idle:.0f} min)')
            return

        hour = time.localtime().tm_hour
        guard_start = getattr(config, 'GUARD_MODE_START', 22)
        guard_end = getattr(config, 'GUARD_MODE_END', 7)
        in_guard = (hour >= guard_start or hour < guard_end) if guard_start > guard_end else (guard_start <= hour < guard_end)
        sched = 'GUARD' if in_guard else 'DAY'
        if self.mode != sched:
            self.mode = sched
            app_logger.info(f'Schedule → {sched}')

    def should_alert(self) -> bool:
        """Requires sustained score >= RISK_THRESHOLD for at least 1.8s before alerting."""
        now = time.time()
        if self.score >= config.RISK_THRESHOLD:
            if self._above_threshold_since is None:
                self._above_threshold_since = now
            return (now - self._above_threshold_since) >= 1.8
        else:
            self._above_threshold_since = None
            return False

    def evaluate(
        self,
        tracks: List[Dict[str, Any]],
        validated_behaviors: List[BehaviorResult],
        zones: List[List[int]],
        zone_types: List[str],
        tamper: bool = False
    ) -> Tuple[float, List[str], bool]:
        """
        Evaluates current validated signals, identity classifications, and updates risk score and reasons.
        :return: (score: float, reasons: List[str], alert_active: bool)
        """
        now = time.time()
        elapsed = max(1e-3, min(now - self.last_update, 1.0))
        self.last_update = now
        self.reasons = []
        self.event_log = []

        # 1. Camera Tampering (Highest severity signal — completely independent)
        if tamper:
            self.score = 100.0
            self.reasons.append("CAMERA TAMPER DETECTED")
            self.event_log.append("CAMERA TAMPERED!")
            self._last_activity = now
            return self.score, self.reasons, True

        if tracks:
            self._last_activity = now

        anyone_in_high = False
        anyone_in_watch = False
        suspicious_detected = False
        target_delta = 0.0

        for track in tracks:
            tid = track.get('track_id', 0)
            classification = track.get('classification', 'UNIDENTIFIED')
            identity_label = track.get('identity', f'Person-{tid}')
            z_idx = track.get('current_zone')
            dwell = track.get('dwell_time', 0.0)

            # 2. Identity Evaluation: Suspicious Person Signal
            if classification == 'SUSPICIOUS':
                suspicious_detected = True
                sus_score = 90.0 if self.mode == 'GUARD' else 75.0
                target_delta = max(target_delta, sus_score)
                self.reasons.append(f"SUSPICIOUS_PERSON_DETECTED ({identity_label} on Track #{tid})")
                self.event_log.append(f"[SECURITY] Suspicious person recognized: {identity_label}")

            # 3. Zone Analysis
            if z_idx is not None and 0 <= z_idx < len(zones):
                z_type = zone_types[z_idx] if z_idx < len(zone_types) else 'WATCH'

                if z_type == config.ZONE_TYPE_HIGH:
                    anyone_in_high = True
                    # High zone security rules apply to ALL persons (Known, Unknown, Suspicious)
                    label_suffix = f" ({identity_label} on Track #{tid})" if (classification in ('KNOWN', 'SUSPICIOUS') and not identity_label.startswith('Person-')) else f" (Track #{tid})"
                    if self.mode == 'GUARD':
                        target_delta = max(target_delta, 100.0)
                        self.reasons.append(f"+ HIGH zone breach{label_suffix} [GUARD MODE]")
                        self.event_log.append(f"[HIGH] {identity_label} in restricted zone — GUARD MODE")
                    else:
                        target_delta = max(target_delta, float(config.RISK_THRESHOLD))
                        self.reasons.append(f"+ HIGH zone breach{label_suffix}")
                        self.event_log.append(f"[HIGH] {identity_label} entered restricted zone")

                else:
                    anyone_in_watch = True
                    # WATCH zone: evaluate dwell beyond grace period
                    grace_sec = getattr(config, 'WATCH_GRACE_SEC', 10.0)
                    if dwell >= grace_sec:
                        dwell_score = min(50.0, 20.0 + (dwell - grace_sec) * 1.5)
                        target_delta = max(target_delta, dwell_score)
                        self.reasons.append(f"+ WATCH zone dwell {dwell:.1f}s ({identity_label} on Track #{tid})")
                        self.event_log.append(f"#{tid} ({identity_label}) in WATCH zone {dwell:.0f}s")

        # 4. Deterministic 3-State Score Smoothing & Decay
        base_decay = getattr(config, 'SCORE_DECAY_RATE', 8.0)
        if anyone_in_high or suspicious_detected:
            decay_rate = base_decay * 0.4
        elif anyone_in_watch:
            decay_rate = base_decay * 2.0
        else:
            decay_rate = base_decay * 6.0

        if anyone_in_high or suspicious_detected:
            self.score = max(self.score, target_delta)
        elif target_delta > self.score:
            step = (target_delta - self.score) * 0.6
            self.score = min(100.0, self.score + step)
        else:
            self.score = max(0.0, self.score - (decay_rate * elapsed))

        self.score = round(self.score, 1)
        alert_active = self.should_alert()
        return self.score, self.reasons, alert_active

    def update(self, person_events: list, zone_types: dict = None, tamper: bool = False) -> float:
        """Legacy compatibility wrapper for update()."""
        zone_types_dict = zone_types or {}
        zones = [[0, 0, 100, 100]] * max(1, len(zone_types_dict))
        types_list = [zone_types_dict.get(i, 'WATCH') for i in range(len(zones))]
        score, _, _ = self.evaluate(person_events, [], zones, types_list, tamper)
        return score
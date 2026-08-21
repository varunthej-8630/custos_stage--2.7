# engine/decision_engine.py — CUSTOS 2.6 Decision Layer
import time
from typing import List, Dict, Any, Tuple
from config import settings as config
from engine.zone_monitor import is_box_in_zone
from engine.risk_engine import RiskEngine

class DecisionEngine:
    """
    Coordinates final alert escalation and decision rules.
    """
    def __init__(self):
        self.risk_engine = RiskEngine()
        self.mode = 'DAY'
        self.event_log = set()

    def is_person_in_zone(self, track_or_dict: Any, zone: List[int]) -> bool:
        if isinstance(track_or_dict, dict):
            box = track_or_dict.get('bbox', track_or_dict.get('box', []))
        elif isinstance(track_or_dict, (list, tuple)):
            box = list(track_or_dict)
        else:
            return False
        return is_box_in_zone(box, zone, getattr(config, 'TOUCH_IOU_THRESHOLD', 0.10))

    def process(self, reasoned_data: List[Dict[str, Any]], zones: List[List[int]], zone_types: List[str], tamper: bool = False) -> Tuple[float, List[str], bool]:
        score, reasons, alert_active = self.risk_engine.evaluate(
            tracks=reasoned_data,
            validated_behaviors=[],
            zones=zones,
            zone_types=zone_types,
            tamper=tamper
        )
        self.event_log = set(self.risk_engine.event_log)
        self.mode = self.risk_engine.mode
        return score, list(self.event_log), alert_active

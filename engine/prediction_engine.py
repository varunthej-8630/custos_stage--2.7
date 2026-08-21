# engine/prediction_engine.py — Deprecated compatibility wrapper
from typing import List, Dict, Any

class PredictionEngine:
    """
    Deprecated: Linear centroid extrapolation heuristics are disabled.
    Kept as pass-through for backwards compatibility.
    """
    def process(self, behaviors: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return behaviors

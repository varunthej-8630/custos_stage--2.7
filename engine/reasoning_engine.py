# engine/reasoning_engine.py — Deprecated compatibility wrapper
from typing import List, Dict, Any

class ReasoningEngine:
    """
    Deprecated: Unvalidated probabilistic multipliers are replaced by RiskEngine evaluation.
    Kept as pass-through for backwards compatibility.
    """
    def process(self, predictions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return predictions

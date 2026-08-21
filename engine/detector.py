# engine/detector.py — Deprecated compatibility wrapper for PerceptionEngine
from engine.perception_engine import PerceptionEngine

class ObjectDetector(PerceptionEngine):
    """
    Deprecated: Kept for backwards compatibility with legacy tests.
    Use PerceptionEngine instead.
    """
    pass

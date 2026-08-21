# engine/tracker.py — Compatibility bridge for PersonTracker using MultiObjectTracker
from engine.tracking_engine import MultiObjectTracker, TrackingEngine

class PersonTracker(MultiObjectTracker):
    """
    Deprecated bridge: Maps legacy PersonTracker calls to MultiObjectTracker.
    """
    def __init__(self):
        super().__init__(match_iou=0.3, max_unseen_sec=3.0)

    def is_person_in_zone(self, foot_x, foot_y, zone, tolerance=10):
        x1, y1, x2, y2 = zone
        return (x1 + tolerance <= foot_x <= x2 - tolerance and
                y1 + tolerance <= foot_y <= y2 - tolerance)

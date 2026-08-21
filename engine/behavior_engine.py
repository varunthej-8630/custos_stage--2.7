# engine/behavior_engine.py — Compatibility Bridge for BehaviorEngine
from engine.behavior_analyzer import BehaviorAnalyzer

class BehaviorEngine:
    """
    Deprecated bridge: Maps legacy BehaviorEngine.process() to BehaviorAnalyzer.
    Unvalidated heuristics (crouching, pacing, erratic, freeze) are marked DISABLED.
    """
    def __init__(self):
        self.analyzer = BehaviorAnalyzer()

    def process(self, tracks):
        res = self.analyzer.process(tracks)
        results = []
        for t in res['tracks']:
            results.append({
                'track_id': t.get('track_id', 0),
                'box': t.get('bbox', t.get('box', [])),
                'foot_x': t.get('foot_x', 0),
                'foot_y': t.get('foot_y', 0),
                'movement': t.get('speed', 0.0),
                'dwell_time': t.get('dwell_time', 0.0),
                # Legacy unvalidated flags default to False
                'is_running': t.get('speed', 0.0) > 25.0,
                'is_erratic': False,
                'is_frozen': False,
                'is_pacing': False,
                'is_crouching': False,
                'active_behaviors': t.get('behaviors', [])
            })
        return results

import time
import collections

class PersonMemory:
    """
    Persistent in-memory state tracking per subject across frames.
    Maintains spatial history, zone dwell breakdown, expanded behavior flags, and risk trends.
    """
    def __init__(self, track_id, first_seen=None):
        self.track_id = track_id
        now = time.time()
        self.first_seen = first_seen or now
        self.last_seen = now
        self.cx = 0.0
        self.cy = 0.0
        self.foot_x = 0.0
        self.foot_y = 0.0
        
        # Spatial trajectory history (max 50 points)
        self.trajectory = collections.deque(maxlen=50)
        self.speeds = collections.deque(maxlen=20)
        
        # Zone Dwell Tracking
        self.zone_dwell_map = {} # zone_index -> total_dwell_seconds
        self.current_zone = None
        self.zone_enter_time = None
        self.visited_zones = set()
        
        # Expanded 9-Behavior Suite Flags
        self.behaviors = {
            'crouching': False,
            'pacing': False,
            'frozen': False,
            'erratic': False,
            'loitering': False,
            'repeated_visits': False,
            'zone_hopping': False,
            'fall_detected': False,
            'object_abandoned': False
        }
        
        # Risk & Identity
        self.risk_score_history = collections.deque(maxlen=30)
        self.peak_risk_score = 0.0
        self.identity = {
            'status': 'TRACKED_SUBJECT', # Temporary Track ID (Stage 2)
            'label': f'Person-{track_id}',
            'confidence': 1.0
        }

    def update_position(self, cx, cy, foot_x, foot_y):
        now = time.time()
        if self.trajectory:
            prev_x, prev_y = self.trajectory[-1]
            move = ((cx - prev_x)**2 + (cy - prev_y)**2) ** 0.5
            self.speeds.append(move)
        
        self.cx = cx
        self.cy = cy
        self.foot_x = foot_x
        self.foot_y = foot_y
        self.trajectory.append((cx, cy))
        self.last_seen = now

    def update_zone(self, zone_idx):
        now = time.time()
        if zone_idx != self.current_zone:
            if self.current_zone is not None and self.zone_enter_time:
                dwell = now - self.zone_enter_time
                self.zone_dwell_map[self.current_zone] = self.zone_dwell_map.get(self.current_zone, 0.0) + dwell
                if self.current_zone != zone_idx and zone_idx is not None:
                    self.behaviors['zone_hopping'] = True
            self.current_zone = zone_idx
            self.zone_enter_time = now if zone_idx is not None else None
            if zone_idx is not None:
                self.visited_zones.add(zone_idx)
        elif zone_idx is not None and self.zone_enter_time:
            dwell = now - self.zone_enter_time
            curr_total = self.zone_dwell_map.get(zone_idx, 0.0) + (now - self.last_seen)
            self.zone_dwell_map[zone_idx] = curr_total
            if curr_total > 15.0:
                self.behaviors['loitering'] = True

    def record_risk(self, score):
        self.risk_score_history.append(score)
        if score > self.peak_risk_score:
            self.peak_risk_score = score

    def to_dict(self):
        total_dwell = sum(self.zone_dwell_map.values())
        return {
            'person_id': f"Person-{self.track_id}",
            'track_id': self.track_id,
            'dwell_seconds': round(total_dwell, 1),
            'current_zone': self.current_zone,
            'visited_zones': list(self.visited_zones),
            'behaviors': dict(self.behaviors),
            'peak_risk': round(self.peak_risk_score, 1),
            'identity': dict(self.identity)
        }

class PersonMemoryManager:
    """
    Manages active subject state memories across frames.
    Auto-purges stale tracks inactive for > 5 seconds.
    """
    def __init__(self):
        self.memories = {}

    def get_or_create(self, track_id):
        if track_id not in self.memories:
            self.memories[track_id] = PersonMemory(track_id)
        return self.memories[track_id]

    def purge_stale(self, max_stale_sec=5.0):
        now = time.time()
        stale_ids = [tid for tid, mem in self.memories.items() if now - mem.last_seen > max_stale_sec]
        for tid in stale_ids:
            del self.memories[tid]

person_memory_mgr = PersonMemoryManager()

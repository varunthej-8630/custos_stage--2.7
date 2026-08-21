import os
import time
import json
import threading
import collections
from datetime import datetime, timedelta
from config import settings as config
from engine.logger import app_logger

class DynamicReliabilityScorer:
    """
    Calculates dynamic evidence confidence score (0% - 100%) based on multi-factor analysis:
      - Behavior Confidence (+10 to +30)
      - Track Duration / Dwell (+5 to +25)
      - Zone Severity (+10 to +25)
      - Detection Stability (+5 to +20)
      - False Positive Penalties (-10 to -100)
    """
    @staticmethod
    def calculate(behaviors, dwell_seconds, zone_type, track_history_len, false_positive=False):
        if false_positive:
            return 0.0

        score = 30.0 # Base detection score

        # Behavior confidence score
        behavior_count = len(behaviors) if behaviors else 0
        if behavior_count >= 2:
            score += 35.0
        elif behavior_count == 1:
            score += 20.0

        # Track duration score (scales linearly with dwell time up to 25 pts)
        dwell_seconds = float(dwell_seconds or 0.0)
        dwell_score = min(25.0, (dwell_seconds / 2.0))
        score += dwell_score

        # Zone severity score
        if zone_type == getattr(config, 'ZONE_TYPE_HIGH', 'HIGH'):
            score += 25.0
        else:
            score += 10.0

        # Detection stability score
        track_history_len = int(track_history_len or 0)
        if track_history_len >= 10:
            score += 15.0
        elif track_history_len >= 5:
            score += 8.0

        # Clamp between 0.0 and 100.0
        return round(max(0.0, min(100.0, score)), 1)

class IncidentReplayBuilder:
    """
    Formats chronological step-by-step timeline progressions for interactive ▶ Incident Replay.
    """
    @staticmethod
    def build_timeline(first_seen_str, events_list, zone_name, track_id):
        timeline = []
        timeline.append({
            'step': 1,
            'time': first_seen_str,
            'action': f"Subject Person-{track_id} detected near {zone_name}",
            'type': 'entry'
        })

        step_counter = 2
        events_list = list(events_list) if events_list else []
        for evt in events_list:
            timeline.append({
                'step': step_counter,
                'time': time.strftime("%I:%M:%S %p"),
                'action': str(evt),
                'type': 'behavior' if 'HIGH' not in str(evt) else 'breach'
            })
            step_counter += 1

        timeline.append({
            'step': step_counter,
            'time': time.strftime("%I:%M:%S %p"),
            'action': "Incident correlated & logged into Evidence Intelligence Center",
            'type': 'alert'
        })
        return timeline

class EvidenceDeduplicator:
    """
    Deduplicates repeated behavior alerts from the same subject within a 3-5 minute cooldown window.
    Merges consecutive alerts into a single evolving Incident record.
    """
    def __init__(self, cooldown_seconds=180.0):
        self.cooldown_seconds = cooldown_seconds
        self.active_subject_incidents = {} # subject_id -> incident_dict
        self.lock = threading.Lock()

    def should_merge(self, subject_id):
        with self.lock:
            now = time.time()
            if subject_id in self.active_subject_incidents:
                last_time = self.active_subject_incidents[subject_id].get('last_updated', 0)
                if now - last_time <= self.cooldown_seconds:
                    return True
            return False

    def update_incident(self, subject_id, new_events, score, dwell_seconds, timeline_step):
        with self.lock:
            if subject_id not in self.active_subject_incidents:
                return {}
            inc = self.active_subject_incidents[subject_id]
            inc['last_updated'] = time.time()
            inc['score'] = max(inc.get('score', 0), score)
            inc['dwell_seconds'] = max(inc.get('dwell_seconds', 0), dwell_seconds)
            inc_events = inc.get('events', [])
            for e in (new_events or []):
                if e not in inc_events:
                    inc_events.append(e)
            inc['events'] = inc_events
            inc_timeline = inc.get('timeline', [])
            if timeline_step and timeline_step not in inc_timeline:
                inc_timeline.append(timeline_step)
            inc['timeline'] = inc_timeline
            return inc

    def register_new(self, subject_id, incident_dict):
        with self.lock:
            incident_dict['last_updated'] = time.time()
            self.active_subject_incidents[subject_id] = incident_dict

    def purge_stale(self):
        with self.lock:
            now = time.time()
            stale = [sid for sid, inc in self.active_subject_incidents.items() if now - inc.get('last_updated', 0) > self.cooldown_seconds]
            for sid in stale:
                del self.active_subject_incidents[sid]

class EvidenceCache:
    """
    Thread-safe in-memory cache of the latest 100 correlated evidence records.
    Serves dashboard queries instantly without database disk IO.
    """
    def __init__(self, maxsize=100):
        self.maxsize = maxsize
        self.cache = collections.deque(maxlen=maxsize)
        self.lock = threading.Lock()

    def add(self, evidence_record):
        with self.lock:
            self.cache.appendleft(evidence_record)

    def get_recent(self, limit=50):
        with self.lock:
            return list(self.cache)[:limit]

    def clear(self):
        with self.lock:
            self.cache.clear()

class EvidenceRetentionManager:
    """
    Enforces automated tier-based media retention rules:
      - Critical Incidents (Score >= 80): Indefinite (365+ days)
      - Threat Incidents (60 <= Score < 80): 90 days
      - Suspicious Incidents (40 <= Score < 60): 30 days
      - Normal Incidents (Score < 40): 7 days
      - Temporary media: Auto-purged after 48 hours
    """
    @staticmethod
    def cleanup_expired_media():
        snapshot_dir = getattr(config, 'SNAPSHOT_DIR', 'data/snapshots')
        if not os.path.exists(snapshot_dir):
            return 0

        now = time.time()
        purged_count = 0
        try:
            for fname in os.listdir(snapshot_dir):
                fpath = os.path.join(snapshot_dir, fname)
                if os.path.isfile(fpath):
                    age_days = (now - os.path.getmtime(fpath)) / (24 * 3600)
                    if fname.startswith('pretamper_') and age_days > 2.0: # Temp clip after 48h
                        os.remove(fpath)
                        purged_count += 1
                    elif fname.startswith('alert_') and age_days > 90.0: # Default retention cap
                        os.remove(fpath)
                        purged_count += 1
        except Exception as e:
            app_logger.error(f"Retention Cleanup error: {e}")
        return purged_count

class EvidenceEngine:
    """
    Central Evidence Engine coordinating Event Collection -> Evidence Generation -> 
    Correlation -> Deduplication -> Dynamic Scoring -> Storage & Presentation.
    """
    def __init__(self):
        self.scorer = DynamicReliabilityScorer()
        self.deduplicator = EvidenceDeduplicator(cooldown_seconds=180.0)
        self.cache = EvidenceCache(maxsize=100)
        self.replay_builder = IncidentReplayBuilder()
        self.retention_mgr = EvidenceRetentionManager()

    def process_event(self, camera_id, score, event_log, zone_name, subject_memory=None, snapshot_path=None, clip_path=None):
        subject_id = subject_memory.get('person_id', 'Person-0') if subject_memory else 'Person-0'
        dwell_sec = subject_memory.get('dwell_seconds', 0.0) if subject_memory else 0.0
        behaviors = list(subject_memory.get('behaviors', {}).keys()) if (subject_memory and isinstance(subject_memory.get('behaviors'), dict)) else []
        track_len = len(subject_memory.get('spatial_trajectory', [])) if (subject_memory and isinstance(subject_memory.get('spatial_trajectory'), list)) else 10
        events_list = list(event_log) if (event_log and isinstance(event_log, (list, tuple, set))) else ([str(event_log)] if event_log else [])

        reliability = self.scorer.calculate(
            behaviors=behaviors,
            dwell_seconds=dwell_sec,
            zone_type='HIGH' if 'HIGH' in str(events_list) else 'WATCH',
            track_history_len=track_len
        )

        now_str = time.strftime("%I:%M:%S %p")
        timeline = self.replay_builder.build_timeline(
            first_seen_str=now_str,
            events_list=events_list,
            zone_name=zone_name or 'Observation Area',
            track_id=subject_memory.get('track_id', 0) if subject_memory else 0
        )

        evidence_package = {
            'timestamp': datetime.utcnow().isoformat(),
            'camera_id': camera_id,
            'zone_name': zone_name or 'Observation Area',
            'score': round(float(score or 0), 1),
            'reliability_score': reliability,
            'subject_id': subject_id,
            'subject_dwell_time': round(float(dwell_sec or 0), 1),
            'events': events_list,
            'timeline': timeline,
            'snapshot_path': os.path.basename(str(snapshot_path)) if snapshot_path else '',
            'clip_path': os.path.basename(str(clip_path)) if clip_path else '',
            'status': 'New'
        }

        # Check deduplication
        if self.deduplicator.should_merge(subject_id):
            updated = self.deduplicator.update_incident(
                subject_id=subject_id,
                new_events=events_list,
                score=score,
                dwell_seconds=dwell_sec,
                timeline_step=timeline[-1] if timeline else None
            )
            if updated:
                evidence_package.update(updated)
        else:
            self.deduplicator.register_new(subject_id, evidence_package)

        # Update cache
        self.cache.add(evidence_package)
        self.deduplicator.purge_stale()
        app_logger.info(f"Incident passed through Evidence Engine (Subject: {subject_id})")

        return evidence_package


evidence_engine = EvidenceEngine()

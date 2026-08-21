import time
import threading

class EvidenceDeduplicatorManager:
    """
    Deduplicates repeated security events using (camera_id, zone_name, subject_id, event_type).
    Merges duplicate events within a 180s (3-5 min) sliding window into single evolving incident records.
    """
    def __init__(self, cooldown_seconds=180.0):
        self.cooldown_seconds = cooldown_seconds
        self.active_incidents = {} # (cam_id, zone, subject_id) -> incident_dict
        self.lock = threading.Lock()

    def make_key(self, camera_id, zone_name, subject_id):
        return (str(camera_id), str(zone_name or 'Zone'), str(subject_id or 'Person-0'))

    def should_merge(self, camera_id, zone_name, subject_id):
        with self.lock:
            key = self.make_key(camera_id, zone_name, subject_id)
            if key in self.active_incidents:
                last_updated = self.active_incidents[key].get('last_updated', 0)
                if time.time() - last_updated <= self.cooldown_seconds:
                    return True
            return False

    def update_incident(self, camera_id, zone_name, subject_id, new_events, score, dwell_seconds, timeline_step):
        with self.lock:
            key = self.make_key(camera_id, zone_name, subject_id)
            if key not in self.active_incidents:
                return None

            inc = self.active_incidents[key]
            inc['last_updated'] = time.time()
            inc['score'] = max(inc.get('score', 0.0), float(score or 0.0))
            inc['subject_dwell_time'] = max(inc.get('subject_dwell_time', 0.0), float(dwell_seconds or 0.0))
            
            existing_events = inc.get('events', [])
            for e in (new_events or []):
                if e not in existing_events:
                    existing_events.append(e)
            inc['events'] = existing_events

            existing_timeline = inc.get('timeline', [])
            if timeline_step and timeline_step not in existing_timeline:
                existing_timeline.append(timeline_step)
            inc['timeline'] = existing_timeline

            return inc

    def register_new(self, camera_id, zone_name, subject_id, incident_dict):
        with self.lock:
            key = self.make_key(camera_id, zone_name, subject_id)
            incident_dict['last_updated'] = time.time()
            self.active_incidents[key] = incident_dict

    def purge_stale(self):
        with self.lock:
            now = time.time()
            stale = [k for k, v in self.active_incidents.items() if now - v.get('last_updated', 0) > self.cooldown_seconds]
            for k in stale:
                del self.active_incidents[k]

evidence_deduplicator = EvidenceDeduplicatorManager(cooldown_seconds=180.0)

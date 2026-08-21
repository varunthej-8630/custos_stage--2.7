import threading
import collections
from engine.logger import app_logger

class EvidenceCacheManager:
    """
    Thread-safe O(1) In-Memory Cache for the latest 100 Evidence packages.
    Serves dashboard queries instantly without database disk IO.
    """
    def __init__(self, maxsize=100):
        self.maxsize = maxsize
        self.cache = collections.deque(maxlen=maxsize)
        self.index_map = {} # id/ts -> record
        self.lock = threading.Lock()

    def add(self, evidence_record):
        if not evidence_record:
            return
        with self.lock:
            key = evidence_record.get('id') or evidence_record.get('timestamp')
            app_logger.info(f"Incident passed through Evidence Cache (Key: {key})")
            if key and key in self.index_map:
                # Update existing in-memory record
                self.index_map[key].update(evidence_record)
            else:
                self.cache.appendleft(evidence_record)
                if key:
                    self.index_map[key] = evidence_record
                # Enforce maxsize index cleanup
                while len(self.cache) > self.maxsize:
                    removed = self.cache.pop()
                    r_key = removed.get('id') or removed.get('timestamp')
                    if r_key in self.index_map:
                        del self.index_map[r_key]

    def get_recent(self, limit=50):
        with self.lock:
            return list(self.cache)[:limit]

    def get_by_id(self, key):
        with self.lock:
            return self.index_map.get(key)

    def clear(self):
        with self.lock:
            self.cache.clear()
            self.index_map.clear()

evidence_cache = EvidenceCacheManager(maxsize=100)

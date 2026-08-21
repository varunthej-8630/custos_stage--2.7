import threading
from engine.logger import app_logger

class ZoneStore:
    """
    Thread-safe in-memory store for camera protection zones.
    Allows real-time zone updates without restarting camera capture or resetting tracking states.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._zones = {}
                cls._instance._types = {}
                cls._instance._monitoring = {}
                cls._instance._store_lock = threading.Lock()
            return cls._instance

    def set_zones(self, camera_id, zones, types, monitoring=True):
        with self._store_lock:
            self._zones[camera_id] = [list(z) for z in zones]
            self._types[camera_id] = list(types)
            self._monitoring[camera_id] = bool(monitoring)
            app_logger.info(f"ZoneStore: Updated Camera {camera_id} with {len(zones)} zone(s), monitoring={monitoring}")

    def get_zones(self, camera_id):
        with self._store_lock:
            zones = self._zones.get(camera_id, [])
            types = self._types.get(camera_id, [])
            monitoring = self._monitoring.get(camera_id, False)
            return [list(z) for z in zones], list(types), monitoring

    def is_monitoring(self, camera_id):
        with self._store_lock:
            return self._monitoring.get(camera_id, False)

    def clear(self, camera_id=None):
        with self._store_lock:
            if camera_id is not None:
                self._zones.pop(camera_id, None)
                self._types.pop(camera_id, None)
                self._monitoring.pop(camera_id, None)
            else:
                self._zones.clear()
                self._types.clear()
                self._monitoring.clear()

# Global ZoneStore instance
zone_store = ZoneStore()

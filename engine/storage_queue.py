# engine/storage_queue.py — Hardened Asynchronous Task & Storage Queue
import queue
import time
import uuid
import threading
from typing import Dict, Any, Optional
from datetime import datetime

from engine.logger import app_logger
from engine.evidence_cache import evidence_cache

class StorageTask:
    def __init__(self, task_type: str, payload: Any, incident_id: Optional[int] = None):
        self.task_id = str(uuid.uuid4())[:8]
        self.incident_id = incident_id or (payload.get('incident_id') if isinstance(payload, dict) else None)
        self.task_type = task_type
        self.payload = payload
        self.created_at = time.time()
        self.status = 'PENDING' # PENDING, PROCESSING, COMPLETED, FAILED
        self.retry_count = 0
        self.max_retries = 3
        self.error = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            'task_id': self.task_id,
            'incident_id': self.incident_id,
            'task_type': self.task_type,
            'created_at': self.created_at,
            'status': self.status,
            'retry_count': self.retry_count,
            'error': self.error
        }

class StorageQueueManager:
    """
    Hardened Asynchronous Storage Queue Manager.
    Guarantees that database persistence, media updates, and Socket.IO emissions
    execute reliably with full task tracking and exponential backoff retry.
    """
    def __init__(self, maxsize=100):
        self.queue = queue.Queue(maxsize=maxsize)
        self.running = False
        self.worker_thread = None
        self.flask_app = None
        self.socket_emitter = None
        self.recent_tasks: Dict[str, StorageTask] = {}
        self.lock = threading.Lock()

    def set_app(self, app):
        self.flask_app = app

    def set_socket_emitter(self, emitter):
        self.socket_emitter = emitter

    def start(self):
        if not self.running:
            self.running = True
            self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
            self.worker_thread.start()
            app_logger.info("[STORAGE QUEUE] Hardened Storage Queue Worker Started")

    def stop(self):
        self.running = False
        if self.worker_thread and self.worker_thread.is_alive():
            self.worker_thread.join(timeout=2.0)

    def put_task(self, task_type: str, payload: Any, incident_id: Optional[int] = None) -> bool:
        """
        Enqueues a structured StorageTask.
        """
        task = StorageTask(task_type, payload, incident_id=incident_id)
        with self.lock:
            self.recent_tasks[task.task_id] = task
            # Keep history under 200 items
            if len(self.recent_tasks) > 200:
                oldest = sorted(self.recent_tasks.keys(), key=lambda k: self.recent_tasks[k].created_at)[:50]
                for k in oldest:
                    del self.recent_tasks[k]

        try:
            self.queue.put_nowait(task)
            return True
        except queue.Full:
            task.status = 'FAILED'
            task.error = 'Storage Queue Full'
            app_logger.error(f"[STORAGE QUEUE] Queue full — could not enqueue task {task.task_id} ({task_type})")
            return False

    def _worker_loop(self):
        while self.running:
            try:
                task: StorageTask = self.queue.get(timeout=0.5)
                task.status = 'PROCESSING'
                success = self._execute_task(task)
                if success:
                    task.status = 'COMPLETED'
                else:
                    if task.retry_count < task.max_retries:
                        task.retry_count += 1
                        time.sleep(0.15 * (2 ** task.retry_count)) # Exponential backoff
                        self.queue.put(task)
                    else:
                        task.status = 'FAILED'
                        app_logger.error(f"[STORAGE QUEUE] Task {task.task_id} ({task.task_type}) failed permanently: {task.error}")
                self.queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                app_logger.error(f"[STORAGE QUEUE] Worker loop unexpected error: {e}")

    def _execute_task(self, task_or_type, payload=None) -> bool:
        if isinstance(task_or_type, StorageTask):
            task = task_or_type
            task_type = task.task_type
            payload = task.payload
        else:
            task_type = task_or_type
            task = StorageTask(task_type, payload)

        try:
            if task_type == 'save_incident':
                from database.database_manager import db_manager
                inc_id = db_manager.save_incident(self.flask_app, payload)
                if inc_id:
                    task.incident_id = inc_id
                    if self.socket_emitter:
                        alert_dict = db_manager.get_alert_by_id(self.flask_app, inc_id)
                        evidence_dict = db_manager.get_evidence_by_id(self.flask_app, inc_id)
                        if alert_dict: self.socket_emitter('alert_created', alert_dict)
                        if evidence_dict: self.socket_emitter('evidence_created', evidence_dict)
                    evidence_cache.add(payload)
                    return True
                else:
                    task.error = "db_manager.save_incident returned None"
                    return False

            elif task_type == 'update_lifecycle':
                from database.database_manager import db_manager
                inc_id = task.incident_id or payload.get('incident_id')
                return db_manager.update_incident_lifecycle(
                    self.flask_app,
                    inc_id,
                    snapshot_path=payload.get('snapshot_path'),
                    snapshot_status=payload.get('snapshot_status'),
                    video_status=payload.get('video_status'),
                    evidence_status=payload.get('evidence_status'),
                    dwell_time=payload.get('dwell_time'),
                    score=payload.get('score'),
                    timeline=payload.get('timeline'),
                    status=payload.get('status')
                )

            elif task_type == 'close_lifecycle':
                from database.database_manager import db_manager
                inc_id = task.incident_id or payload.get('incident_id')
                return db_manager.close_incident_lifecycle(
                    self.flask_app,
                    inc_id,
                    clip_path=payload.get('clip_path'),
                    video_status=payload.get('video_status', 'AVAILABLE'),
                    evidence_status=payload.get('evidence_status', 'COMPLETE'),
                    dwell_time=payload.get('dwell_time'),
                    timeline=payload.get('timeline')
                )

            return True

        except Exception as e:
            task.error = str(e)
            app_logger.error(f"[STORAGE QUEUE] Task Execution Error ({task_type}, ID {task.task_id}): {e}")
            return False

storage_queue = StorageQueueManager(maxsize=100)

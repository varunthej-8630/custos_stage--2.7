import threading
from engine.pipeline import CameraPipeline
from engine.logger import app_logger

class CameraManager:
    def __init__(self, socket_emitter=None, flask_app=None):
        self.pipelines = {}
        self.socket_emitter = socket_emitter
        self.flask_app = flask_app
        self.lock = threading.Lock()

    def start_cameras(self, camera_sources):
        with self.lock:
            for idx, source in enumerate(camera_sources):
                if idx not in self.pipelines:
                    pipeline = CameraPipeline(source, camera_id=idx)
                    if self.socket_emitter:
                        pipeline.set_socket_emitter(self.socket_emitter)
                    if self.flask_app:
                        pipeline.set_app_context(self.flask_app)
                    pipeline.start()
                    self.pipelines[idx] = pipeline
                    app_logger.info(f'Started pipeline for camera {idx} (source: {source})')

    def get_pipeline(self, camera_id):
        with self.lock:
            return self.pipelines.get(camera_id)

    def get_all_pipelines(self):
        with self.lock:
            return list(self.pipelines.values())

    def set_zones(self, camera_id, zones, types, monitoring):
        from engine.zone_store import zone_store
        zone_store.set_zones(camera_id, zones, types, monitoring)
        pipeline = self.get_pipeline(camera_id)
        if pipeline:
            pipeline.set_zones(zones, types, monitoring)


    def stop_all(self):
        with self.lock:
            for pid, pipeline in self.pipelines.items():
                app_logger.info(f'Stopping pipeline {pid}')
                pipeline.stop()
            self.pipelines.clear()

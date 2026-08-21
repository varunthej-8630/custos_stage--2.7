import cv2
import time
import os
import collections
import threading
import platform
import queue

from config import settings as config
from engine.logger import get_camera_logger
from web.alert_manager import AlertManager

from engine.ai_engine import ai_engine
from engine.zone_monitor import ZoneMonitor
from engine.zone_store import zone_store
from engine.health_monitor import system_health, CameraHealthMonitor
from engine.situation_engine import situation_engine
from engine.storage_queue import storage_queue
from engine.tamper_detector import tamper_detector
from engine.incident_lifecycle import incident_lifecycle_mgr
from engine.media_recorder import media_recorder
from engine.frame_buffer import CircularFrameBuffer

def open_camera(source, logger):
    cap = None
    if platform.system() == 'Windows':
        cap = cv2.VideoCapture(source, cv2.CAP_DSHOW)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            ret, _ = cap.read()
            if ret:
                logger.info('Opened with DSHOW backend')
                return cap
            cap.release()
        logger.info('DSHOW failed, trying default backend...')
    cap = cv2.VideoCapture(source)
    if cap.isOpened():
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap

class CameraPipeline(threading.Thread):
    def __init__(self, camera_source, camera_id=0, alerts=None):
        super().__init__(daemon=True)
        self.camera_source = camera_source
        self.camera_id = camera_id
        self.logger = get_camera_logger(camera_id)
        
        self.running = True
        self.cap = None
        
        self.zones = []
        self.zone_types = []
        self.monitoring = False
        self.ref_set = False
        self.zones_lock = threading.Lock()
        
        self.alert_history = collections.deque(maxlen=50)
        self.latest_frame_bytes = None
        
        self.state = {
            'score': 0.0, 'mode': 'DAY', 'persons': 0, 'in_zone': 0,
            'alert_active': False, 'alert_resolved': False, 'tamper': False,
            'fps': 0.0, 'event_log': [], 'alerts': [], 'uptime_start': time.time(),
            'cam_w': 640, 'cam_h': 480, 'camera_id': self.camera_id
        }
        self.state_lock = threading.Lock()
        self.frame_lock = threading.Lock()
        
        self.alerts = alerts or AlertManager()
        self.socket_emitter = None 
        self.latest_raw_frame = None 
        
        self.flask_app = None
        self.camera_health = CameraHealthMonitor(camera_id)
        self.capture_queue = queue.Queue(maxsize=2)
        # Dedicated thread-safe rolling circular frame buffer (15s @ 30 FPS)
        self.frame_buffer = CircularFrameBuffer(max_seconds=15.0, target_fps=30)

    def set_socket_emitter(self, emitter):
        self.socket_emitter = emitter
        incident_lifecycle_mgr.set_socket_emitter(emitter)
        storage_queue.set_socket_emitter(emitter)

    def set_app_context(self, app):
        self.flask_app = app
        incident_lifecycle_mgr.set_flask_app(app)
        storage_queue.set_app(app)
        storage_queue.start()

    def set_zones(self, zones, types, monitoring):
        zone_store.set_zones(self.camera_id, zones, types, monitoring)
        with self.zones_lock:
            self.zones = zones
            self.zone_types = types
            self.monitoring = monitoring
            self.ref_set = False
            self.logger.info(f'{len(self.zones)} zone(s) monitoring={self.monitoring}')

    def run(self):
        self.cap = open_camera(self.camera_source, self.logger)
        if not self.cap.isOpened(): 
            self.logger.error('Cannot open camera')
            return
            
        self.logger.info('Camera Ready')
        for _ in range(config.CAMERA_WARMUP_FRAMES): self.cap.read()
        
        ret_dim, dim_frame = self.cap.read()
        if ret_dim:
            h_cam, w_cam = dim_frame.shape[:2]
            with self.state_lock:
                self.state['cam_w'] = w_cam
                self.state['cam_h'] = h_cam
            
        monitor = ZoneMonitor()
        # Circular pre-event buffer holding ~5-7 seconds of frames (150 frames @ 25 FPS)
        pre_event_buf = collections.deque(maxlen=150)
        frame_count = 0
        fps_timer = time.time()
        fps = 0
        _fail_count = 0

        while self.running:
            start_t = time.time()
            ret, frame = self.cap.read()
            if not ret:
                _fail_count += 1
                self.camera_health.record_disconnect()
                system_health.record_metrics(dropped=1)
                time.sleep(0.1)
                if _fail_count >= 30:
                    self.logger.warning('Feed lost — reopening...')
                    self.cap.release()
                    time.sleep(1.0)
                    self.cap = open_camera(self.camera_source, self.logger)
                    _fail_count = 0
                continue

            _fail_count = 0
            self.camera_health.record_frame()
            
            with self.frame_lock:
                self.latest_raw_frame = frame.copy()
            frame_count += 1
            # Append directly to thread-safe 15-second rolling circular buffer
            self.frame_buffer.append(frame, timestamp=start_t, camera_id=self.camera_id)
            
            if frame_count % 30 == 0:
                fps = 30 / max(time.time() - fps_timer, 0.01)
                fps_timer = time.time()

            # Push to CaptureQueue (maxsize=2)
            if self.capture_queue.full():
                try: self.capture_queue.get_nowait()
                except queue.Empty: pass
                system_health.record_metrics(dropped=1)
            self.capture_queue.put((frame_count, frame))

            current_zones, current_types, is_monitoring = zone_store.get_zones(self.camera_id)
            if not current_zones:
                with self.zones_lock:
                    current_zones = self.zones.copy()
                    current_types = self.zone_types.copy()
                    is_monitoring = self.monitoring

            if current_zones and not self.ref_set:
                monitor.set_reference(frame, current_zones)
                tamper_detector.set_reference(frame)
                self.ref_set = True

            # Draw zones
            display = frame.copy()
            for i, z in enumerate(current_zones):
                x1, y1, x2, y2 = z
                is_high = i < len(current_types) and current_types[i] == config.ZONE_TYPE_HIGH
                col = (40, 40, 220) if is_high else (40, 180, 80)
                ov = display.copy()
                cv2.rectangle(ov, (x1, y1), (x2, y2), col, -1)
                cv2.addWeighted(ov, 0.12, display, 0.88, 0, display)
                cv2.rectangle(display, (x1, y1), (x2, y2), col, 2)
                L = 14
                for (ex, ey, dx, dy) in [(x1,y1,1,1),(x2,y1,-1,1),(x1,y2,1,-1),(x2,y2,-1,-1)]:
                    cv2.line(display, (ex, ey), (ex + dx*L, ey), col, 3)
                    cv2.line(display, (ex, ey), (ex, ey + dy*L), col, 3)
                lbl = 'HIGH SEC' if is_high else 'OBSERVATION'
                cv2.putText(display, f'Z{i+1} {lbl}', (x1+8, y1+18), cv2.FONT_HERSHEY_DUPLEX, 0.45, col, 1, cv2.LINE_AA)

            any_tamper = False
            tamper_reasons = []
            tracks = []
            score = 0.0
            event_log = []
            alert_active = False
            
            if is_monitoring and current_zones:
                try:
                    # 1. Advanced 7-condition Tamper Analysis with Temporal Confirmation
                    any_tamper, tamper_reasons = tamper_detector.update(frame, timestamp=start_t)
                    
                    # 2. AI Perception, Tracking, Zone & Validated Risk Analysis
                    score, event_log, alert_active, tracks = ai_engine.process_frame(
                        frame=frame,
                        frame_count=frame_count,
                        zones=current_zones,
                        zone_types=current_types,
                        monitoring=is_monitoring,
                        tamper=any_tamper
                    )
                    
                    in_zone_count = sum(1 for t in tracks if t.get('current_zone') is not None)
                    
                    # 3. Draw tracked persons
                    for t in tracks:
                        bx = t.get('bbox', t.get('box', []))
                        if bx and len(bx) == 4:
                            x1, y1, x2, y2 = bx
                            in_zone = t.get('current_zone') is not None
                            col_p = (0, 200, 255) if in_zone else (160, 255, 160)
                            cv2.rectangle(display, (int(x1), int(y1)), (int(x2), int(y2)), col_p, 2)
                            tid = t.get('track_id', 0)
                            cv2.putText(display, f"#{tid}", (int(x1), int(y1)-5), cv2.FONT_HERSHEY_SIMPLEX, 0.45, col_p, 1)

                    # Extract up to 15s of rolling pre-event camera frames
                    pre_roll_frames = self.frame_buffer.get_last_seconds(15.0)

                    # 4. Central Canonical Incident Lifecycle Evaluation
                    # Handles entry snapshot, continuous dwell updates (0 alert spam), exit grace, video finalization
                    incident_lifecycle_mgr.process_zone_tracks(
                        camera_id=self.camera_id,
                        tracks=tracks,
                        zones=current_zones,
                        zone_types=current_types,
                        current_frame=frame,
                        pre_event_buffer=pre_roll_frames,
                        base_score=score
                    )

                    # 5. Central Tamper Incident Lifecycle Evaluation (with 15s pre-tamper buffer)
                    incident_lifecycle_mgr.process_tamper(
                        camera_id=self.camera_id,
                        is_tamper_active=any_tamper,
                        reasons=tamper_reasons,
                        current_frame=frame,
                        pre_event_buffer=pre_roll_frames
                    )

                    h_f, w_f = display.shape[:2]
                    sc_col = (80, 255, 100) if score < 40 else (0, 200, 255) if score < 70 else (50, 50, 255)
                    fill = int(w_f * score / 100)
                    cv2.rectangle(display, (0, h_f - 4), (w_f, h_f), (20, 20, 20), -1)
                    cv2.rectangle(display, (0, h_f - 4), (fill, h_f), sc_col, -1)
                    
                    briefing = situation_engine.evaluate(score, event_log, len(tracks))
                    
                    with self.state_lock:
                        self.state['score'] = round(score, 1)
                        self.state['mode'] = ai_engine.risk_engine.mode
                        self.state['persons'] = len(tracks)
                        self.state['in_zone'] = in_zone_count
                        self.state['alert_active'] = alert_active or any_tamper
                        self.state['tamper'] = any_tamper
                        self.state['fps'] = round(fps, 1)
                        self.state['event_log'] = list(event_log)
                        self.state['situation_briefing'] = briefing
                except Exception as e:
                    self.logger.error(f"Pipeline frame processing error: {e}")
            else:
                with self.state_lock:
                    self.state['score'] = 0.0
                    self.state['alert_active'] = False
                    self.state['fps'] = round(fps, 1)
                    self.state['persons'] = 0

            _, jpeg = cv2.imencode('.jpg', display, [cv2.IMWRITE_JPEG_QUALITY, 72])
            with self.frame_lock:
                self.latest_frame_bytes = jpeg.tobytes()

            elapsed_ms = (time.time() - start_t) * 1000
            system_health.record_metrics(
                capture_fps=fps,
                analytics_fps=fps,
                latency_ms=elapsed_ms,
                queues={'CaptureQueue': self.capture_queue.qsize(), 'StorageQueue': storage_queue.queue.qsize()}
            )

            if frame_count % 6 == 0 and self.socket_emitter:
                with self.state_lock: s = dict(self.state)
                keys = ['score','mode','persons','in_zone','alert_active','alert_resolved','tamper','fps','event_log','situation_briefing','cam_w','cam_h','camera_id']
                self.socket_emitter('risk_update', {k: s[k] for k in keys if k in s})

            if system_health.should_emit() and self.socket_emitter:
                h_data = system_health.get_status()
                h_data['camera'] = self.camera_health.get_status()
                self.socket_emitter('system_health', h_data)
                
        self.cap.release()

    def get_state(self):
        with self.state_lock:
            return dict(self.state)

    def get_latest_frame_bytes(self):
        with self.frame_lock:
            return self.latest_frame_bytes

    def stop(self):
        self.running = False
        if self.cap: self.cap.release()

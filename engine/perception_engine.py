# engine/perception_engine.py — CUSTOS 2.6 Perception Layer
import time
from typing import List, Dict, Any, Optional
import numpy as np
from ultralytics import YOLO

from config import settings as config
from engine.logger import detector_logger


class PerceptionEngine:
    """
    Modular Object Detection Engine wrapping YOLOv8.
    Decoupled from tracking, risk scoring, and business logic.
    """
    def __init__(self, model_path: Optional[str] = None, confidence: Optional[float] = None):
        self.model_path = model_path or config.MODEL_PATH
        self.confidence = confidence if confidence is not None else getattr(config, 'CONFIDENCE', 0.40)
        self.input_size = getattr(config, 'INPUT_SIZE', 480)
        
        detector_logger.info(f'Loading Perception Model: {self.model_path} (conf={self.confidence}, size={self.input_size})')
        self.model = YOLO(self.model_path)
        self.model_name = getattr(self.model, 'model_name', 'yolov8n')
        self.last_latency_ms = 0.0
        detector_logger.info('Perception Engine Ready!')

    def detect(self, frame: np.ndarray, classes: Optional[List[int]] = None) -> List[Dict[str, Any]]:
        """
        Executes object detection on a single frame.
        
        :param frame: BGR image (numpy ndarray)
        :param classes: Optional list of class IDs to filter for (e.g. [0] for persons)
        :return: List of detection dictionaries:
            [
                {
                    "class_id": int,
                    "class_name": str,
                    "confidence": float,
                    "bbox": [x1, y1, x2, y2],
                    "box": [x1, y1, x2, y2],     # backwards compatibility
                    "label": str                  # backwards compatibility
                }
            ]
        """
        if frame is None or not isinstance(frame, np.ndarray) or frame.size == 0:
            return []

        start_t = time.perf_counter()
        try:
            results = self.model(
                frame,
                verbose=False,
                conf=self.confidence,
                imgsz=self.input_size,
                classes=classes
            )[0]
        except Exception as e:
            detector_logger.error(f"Perception inference error: {e}")
            return []

        self.last_latency_ms = (time.perf_counter() - start_t) * 1000.0

        detections = []
        if results and results.boxes is not None:
            names = results.names or {}
            for box in results.boxes:
                class_id = int(box.cls[0])
                conf = float(box.conf[0])
                x1, y1, x2, y2 = [int(v) for v in box.xyxy[0]]
                class_name = names.get(class_id, str(class_id))
                
                det = {
                    'class_id': class_id,
                    'class_name': class_name,
                    'confidence': round(conf, 4),
                    'bbox': [x1, y1, x2, y2],
                    # Legacy compatibility keys
                    'box': [x1, y1, x2, y2],
                    'label': class_name
                }
                detections.append(det)

        return detections

    def process(self, frame: np.ndarray) -> List[Dict[str, Any]]:
        """Backwards compatibility alias for detect(frame)."""
        return self.detect(frame)

    def get_model_info(self) -> Dict[str, Any]:
        """Returns metadata and latency for telemetry."""
        return {
            'model_name': 'YOLOv8 Nano (yolov8n.pt)',
            'model_path': self.model_path,
            'confidence_threshold': self.confidence,
            'input_size': self.input_size,
            'latency_ms': round(self.last_latency_ms, 2)
        }

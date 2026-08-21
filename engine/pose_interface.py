# engine/pose_interface.py — CUSTOS 2.6 Pose Estimation Interface
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import time

@dataclass
class PoseResult:
    """Standardized output structure for pose estimation models."""
    track_id: int
    posture: str                  # 'standing', 'sitting', 'crouching', 'fallen', 'unknown'
    confidence: float
    keypoints: List[List[float]]  # [[x, y, conf], ...] 17 COCO keypoints
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)

class PoseEngineInterface(ABC):
    """
    Abstract interface for Pose Estimation backends (e.g., YOLOv8-pose, MediaPipe).
    Ensures modularity so pose estimation can be integrated without modifying the core pipeline.
    """
    @abstractmethod
    def detect_pose(self, frame, person_bbox: List[int], track_id: int = 0) -> Optional[PoseResult]:
        """
        Extracts human keypoints and determines true biometric posture.
        
        :param frame: Full image frame (numpy ndarray)
        :param person_bbox: [x1, y1, x2, y2]
        :param track_id: Target person track ID
        :return: PoseResult instance or None
        """
        pass

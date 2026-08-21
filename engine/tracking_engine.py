# engine/tracking_engine.py — CUSTOS 2.6 Multi-Object Tracking Layer
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
from scipy.optimize import linear_sum_assignment

from config import settings as config
from engine.utils import iou


@dataclass
class TrackState:
    """Represents the complete state of an actively tracked object."""
    track_id: int
    class_id: int
    class_name: str
    bbox: List[int]                     # [x1, y1, x2, y2]
    confidence: float
    first_seen: float
    last_seen: float
    age_frames: int = 0
    missed_frames: int = 0
    
    # Spatial properties
    center: Tuple[float, float] = (0.0, 0.0)      # (cx, cy)
    foot: Tuple[float, float] = (0.0, 0.0)        # (foot_x, foot_y)
    velocity: Tuple[float, float, float] = (0.0, 0.0, 0.0) # (vx, vy, speed_px_per_sec)
    trajectory: List[Tuple[float, float, float]] = field(default_factory=list) # [(x, y, time)]
    
    # Zone occupancy
    current_zone: Optional[int] = None
    zone_dwell_time: float = 0.0
    zone_enter_time: Optional[float] = None
    
    def update(self, bbox: List[int], confidence: float, now: float):
        x1, y1, x2, y2 = bbox
        cx = (x1 + x2) / 2.0
        cy = (y1 + y2) / 2.0
        foot_x = cx
        foot_y = float(y2)
        
        dt = max(now - self.last_seen, 1e-4)
        if self.trajectory:
            prev_cx, prev_cy, _ = self.trajectory[-1]
            vx = (cx - prev_cx) / dt
            vy = (cy - prev_cy) / dt
            speed = (vx**2 + vy**2) ** 0.5
            self.velocity = (round(vx, 2), round(vy, 2), round(speed, 2))
        else:
            self.velocity = (0.0, 0.0, 0.0)

        self.bbox = bbox
        self.confidence = confidence
        self.center = (round(cx, 2), round(cy, 2))
        self.foot = (round(foot_x, 2), round(foot_y, 2))
        self.last_seen = now
        self.age_frames += 1
        self.missed_frames = 0
        
        self.trajectory.append((cx, cy, now))
        if len(self.trajectory) > 60: # Keep 2-3 seconds at 25-30 fps
            self.trajectory.pop(0)

    @property
    def age_seconds(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    def to_dict(self) -> Dict[str, Any]:
        """Serializes track state for pipeline consumption and telemetry."""
        return {
            'track_id': self.track_id,
            'class_id': self.class_id,
            'class_name': self.class_name,
            'bbox': self.bbox,
            'box': self.bbox, # backwards compatibility
            'confidence': self.confidence,
            'cx': self.center[0],
            'cy': self.center[1],
            'foot_x': self.foot[0],
            'foot_y': self.foot[1],
            'velocity': self.velocity,
            'speed': self.velocity[2],
            'first_seen': self.first_seen,
            'last_seen': self.last_seen,
            'age_frames': self.age_frames,
            'age_seconds': round(self.age_seconds, 2),
            'current_zone': self.current_zone,
            'dwell_time': round(self.zone_dwell_time, 2),
            'trajectory': list(self.trajectory)
        }


class MultiObjectTracker:
    """
    Robust IoU and Spatial Proximity Multi-Object Tracker.
    Associates continuous bounding boxes with stable, persistent Track IDs.
    """
    def __init__(self, match_iou: float = 0.3, max_unseen_sec: float = 3.0):
        self.match_iou = match_iou
        self.max_unseen_sec = max_unseen_sec
        self.tracks: Dict[int, TrackState] = {}
        self.next_id = 1

    def _compute_iou_matrix(self, boxes_a: List[List[int]], boxes_b: List[List[int]]) -> np.ndarray:
        if not boxes_a or not boxes_b:
            return np.zeros((len(boxes_a), len(boxes_b)))
        matrix = np.zeros((len(boxes_a), len(boxes_b)))
        for i, a in enumerate(boxes_a):
            for j, b in enumerate(boxes_b):
                matrix[i, j] = iou(a, b)
        return matrix

    def update(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Updates active tracks with current frame detections.
        
        :param detections: List of detection dicts with 'bbox', 'confidence', 'class_id', 'class_name'
        :return: List of active track state dictionaries
        """
        now = time.time()
        
        # 1. Separate detections
        det_boxes = [d.get('bbox', d.get('box', [])) for d in detections]
        
        active_ids = list(self.tracks.keys())
        active_boxes = [self.tracks[tid].bbox for tid in active_ids]
        
        matched_tracks = set()
        matched_dets = set()
        
        if active_boxes and det_boxes:
            iou_matrix = self._compute_iou_matrix(active_boxes, det_boxes)
            # Cost = 1 - IoU
            cost_matrix = 1.0 - iou_matrix
            
            row_ind, col_ind = linear_sum_assignment(cost_matrix)
            for r, c in zip(row_ind, col_ind):
                if iou_matrix[r, c] >= self.match_iou:
                    tid = active_ids[r]
                    det = detections[c]
                    self.tracks[tid].update(det['bbox'], det.get('confidence', 1.0), now)
                    matched_tracks.add(tid)
                    matched_dets.add(c)
                elif cost_matrix[r, c] < 0.9:
                    # Spatial proximity fallback if IoU is slight
                    tid = active_ids[r]
                    det = detections[c]
                    t_cx, t_cy = self.tracks[tid].center
                    d_bx = det['bbox']
                    d_cx, d_cy = (d_bx[0] + d_bx[2]) / 2, (d_bx[1] + d_bx[3]) / 2
                    dist = ((t_cx - d_cx)**2 + (t_cy - d_cy)**2) ** 0.5
                    if dist < 80.0:
                        self.tracks[tid].update(det['bbox'], det.get('confidence', 1.0), now)
                        matched_tracks.add(tid)
                        matched_dets.add(c)

        # 2. Unmatched tracks (increment missed frames)
        for r, tid in enumerate(active_ids):
            if tid not in matched_tracks:
                self.tracks[tid].missed_frames += 1

        # 3. New detections -> Create TrackState
        for c, det in enumerate(detections):
            if c not in matched_dets:
                bbox = det.get('bbox', det.get('box', []))
                cid = det.get('class_id', 0)
                cname = det.get('class_name', det.get('label', 'person'))
                conf = det.get('confidence', 1.0)
                
                new_track = TrackState(
                    track_id=self.next_id,
                    class_id=cid,
                    class_name=cname,
                    bbox=bbox,
                    confidence=conf,
                    first_seen=now,
                    last_seen=now
                )
                new_track.update(bbox, conf, now)
                self.tracks[self.next_id] = new_track
                matched_tracks.add(self.next_id)
                self.next_id += 1

        # 4. Remove expired/stale tracks
        stale_ids = [
            tid for tid, trk in self.tracks.items()
            if (now - trk.last_seen) > self.max_unseen_sec
        ]
        for tid in stale_ids:
            del self.tracks[tid]

        # 5. Return currently visible tracks
        visible = [
            trk.to_dict() for trk in self.tracks.values()
            if trk.missed_frames == 0
        ]
        return visible


class TrackingEngine:
    """Wrapper exposing standard TrackingEngine interface for CUSTOS."""
    def __init__(self):
        match_iou = getattr(config, 'TRACK_MATCH_IOU', 0.30)
        max_unseen = getattr(config, 'TRACK_EXPIRATION_SEC', 3.0)
        self.tracker = MultiObjectTracker(match_iou=match_iou, max_unseen_sec=max_unseen)

    def process(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.tracker.update(detections)

    def update(self, detections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return self.tracker.update(detections)

# engine/zone_monitor.py — CUSTOS 2.6 Zone Analysis and Tamper Detection
import cv2
import numpy as np
import time
from typing import List, Dict, Any, Tuple, Optional

from config import settings as config
from engine.logger import app_logger


def is_box_in_zone(box: List[int], zone: List[int], touch_iou_threshold: float = 0.10) -> bool:
    """
    Deterministic check: returns True if person's feet, center point,
    or bounding box intersects with the zone by >= touch_iou_threshold.
    """
    if not box or not zone or len(box) < 4 or len(zone) < 4:
        return False
    bx1, by1, bx2, by2 = box
    zx1, zy1, zx2, zy2 = zone

    # 1. Footpoint check (bottom center of bbox)
    fx = (bx1 + bx2) / 2.0
    fy = float(by2)
    if zx1 <= fx <= zx2 and zy1 <= fy <= zy2:
        return True

    # 2. Centroid check
    cx = (bx1 + bx2) / 2.0
    cy = (by1 + by2) / 2.0
    if zx1 <= cx <= zx2 and zy1 <= cy <= zy2:
        return True

    # 3. Intersection / Overlap Area
    ix1 = max(bx1, zx1)
    iy1 = max(by1, zy1)
    ix2 = min(bx2, zx2)
    iy2 = min(by2, zy2)

    if ix2 > ix1 and iy2 > iy1:
        inter_area = (ix2 - ix1) * (iy2 - iy1)
        box_area = max(1, (bx2 - bx1) * (by2 - by1))
        if (inter_area / box_area) >= touch_iou_threshold:
            return True

    return False


class ZoneMonitor:
    """
    Evaluates spatial zone membership and performs camera tamper & occlusion monitoring.
    """
    def __init__(self):
        self.reference_crops = {}
        self.last_object_check = 0
        self.object_check_interval = 3.0
        self.camera_tamper_since = None
        self.touch_iou_threshold = getattr(config, 'TOUCH_IOU_THRESHOLD', 0.10)
        self.track_zone_sessions = {} # track_id -> {'zone_idx', 'enter_time', 'dwell_time'}

    def is_person_in_zone(self, track_or_box: Any, zone: List[int]) -> bool:
        if isinstance(track_or_box, dict):
            box = track_or_box.get('bbox', track_or_box.get('box', []))
        elif isinstance(track_or_box, (list, tuple)):
            box = list(track_or_box)
        else:
            return False
        return is_box_in_zone(box, zone, self.touch_iou_threshold)

    def evaluate_tracks(self, tracks: List[Dict[str, Any]], zones: List[List[int]], zone_types: List[str]) -> List[Dict[str, Any]]:
        """
        Updates zone membership and dwell metrics deterministically for each active track.
        """
        now = time.time()
        for track in tracks:
            tid = track.get('track_id', 0)
            box = track.get('bbox', track.get('box', []))
            
            matched_zone_idx = None
            for i, zone in enumerate(zones):
                if self.is_person_in_zone(box, zone):
                    matched_zone_idx = i
                    break
            
            if matched_zone_idx is not None:
                if tid not in self.track_zone_sessions or self.track_zone_sessions[tid]['zone_idx'] != matched_zone_idx:
                    self.track_zone_sessions[tid] = {
                        'zone_idx': matched_zone_idx,
                        'enter_time': now,
                        'dwell_time': 0.0
                    }
                else:
                    session = self.track_zone_sessions[tid]
                    session['dwell_time'] = now - session['enter_time']
                
                track['current_zone'] = matched_zone_idx
                track['dwell_time'] = round(self.track_zone_sessions[tid]['dwell_time'], 2)
            else:
                track['current_zone'] = None
                track['dwell_time'] = 0.0
                if tid in self.track_zone_sessions:
                    del self.track_zone_sessions[tid]

        # Clean stale sessions
        active_tids = {t.get('track_id') for t in tracks}
        stale = [t for t in self.track_zone_sessions if t not in active_tids]
        for t in stale:
            del self.track_zone_sessions[t]

        return tracks

    def _sanitize_zone_crop(self, frame: np.ndarray, zone: List[int]) -> np.ndarray:
        if frame is None or frame.size == 0 or len(zone) < 4:
            return np.array([])
        h, w = frame.shape[:2]
        x1, y1, x2, y2 = zone
        xmin = max(0, min(int(x1), int(x2)))
        xmax = min(w, max(int(x1), int(x2)))
        ymin = max(0, min(int(y1), int(y2)))
        ymax = min(h, max(int(y1), int(y2)))
        if xmax <= xmin or ymax <= ymin:
            return np.array([])
        return frame[ymin:ymax, xmin:xmax]

    def set_reference(self, frame: np.ndarray, zones: List[List[int]]):
        self.reference_crops = {}
        for i, zone in enumerate(zones):
            crop = self._sanitize_zone_crop(frame, zone)
            if crop.size > 0:
                self.reference_crops[i] = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
                app_logger.info(f'Reference saved for Zone {i+1}')

    def update(self, frame: np.ndarray, zones: List[List[int]], occupied_zones=None) -> Dict[int, Dict[str, Any]]:
        occupied_zones = occupied_zones or set()
        now = time.time()
        results = {
            i: {'zone_index': i, 'occluded': False, 'object_moved': False}
            for i in range(len(zones))
        }

        # ── Whole-camera tamper check ─────────────────
        if self._check_whole_camera_tamper(frame, now):
            for i in results:
                results[i]['occluded'] = True
            return results

        # ── Object-moved check ────────────────────────
        if now - self.last_object_check >= self.object_check_interval:
            self.last_object_check = now
            for i, zone in enumerate(zones):
                if i not in self.reference_crops or i in occupied_zones:
                    continue
                current_crop = self._sanitize_zone_crop(frame, zone)
                if current_crop.size == 0:
                    continue
                current_gray = cv2.cvtColor(current_crop, cv2.COLOR_BGR2GRAY)
                ref_gray = self.reference_crops[i]
                if current_gray.shape != ref_gray.shape:
                    ref_gray = cv2.resize(ref_gray, (current_gray.shape[1], current_gray.shape[0]))
                diff_score = float(np.mean(cv2.absdiff(current_gray, ref_gray)))
                if diff_score > 45:
                    results[i]['object_moved'] = True
                    app_logger.info(f'Zone {i+1}: object moved (diff={diff_score:.1f})')

        return results

    def _check_whole_camera_tamper(self, frame: np.ndarray, now: float) -> bool:
        if frame is None or frame.size == 0:
            return True
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        std = float(np.std(gray))

        if std < getattr(config, 'TAMPER_STD_THRESH', 10):
            if self.camera_tamper_since is None:
                self.camera_tamper_since = now
                app_logger.warning(f'Possible cover — std={std:.1f}')
            elif now - self.camera_tamper_since >= getattr(config, 'TAMPER_CONFIRM_SEC', 2.0):
                app_logger.warning(f'TAMPER CONFIRMED — std={std:.1f}')
                return True
        else:
            if self.camera_tamper_since is not None:
                app_logger.info(f'Camera clear — std={std:.1f}')
            self.camera_tamper_since = None

        return False
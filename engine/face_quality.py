# engine/face_quality.py — CUSTOS Real Face Quality Validator
import cv2
import numpy as np
from typing import Tuple, Optional
from config import settings as config

class FaceQualityValidator:
    """
    Validates face image quality for both live camera frames and user photo enrollment.
    Enforces strict physical quality gates: minimum resolution, sharpness/blur,
    illumination balance, and aspect ratio.
    """
    def __init__(
        self,
        min_size_px: int = None,
        min_blur_var: float = None,
        min_upload_size_px: int = 50,
        min_upload_blur_var: float = 40.0
    ):
        self.min_size_px = min_size_px or getattr(config, 'FACE_MIN_SIZE_PX', 36)
        self.min_blur_var = min_blur_var or getattr(config, 'FACE_MIN_BLUR_VAR', 35.0)
        self.min_upload_size_px = min_upload_size_px
        self.min_upload_blur_var = min_upload_blur_var

    def calculate_sharpness(self, face_img: np.ndarray) -> float:
        """Calculates Laplacian variance as a proxy for image sharpness/blur."""
        if face_img is None or face_img.size == 0:
            return 0.0
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) == 3 else face_img
        lap = cv2.Laplacian(gray, cv2.CV_64F)
        return float(lap.var())

    def calculate_illumination(self, face_img: np.ndarray) -> Tuple[float, float]:
        """Calculates average brightness and contrast (standard deviation)."""
        if face_img is None or face_img.size == 0:
            return 0.0, 0.0
        gray = cv2.cvtColor(face_img, cv2.COLOR_BGR2GRAY) if len(face_img.shape) == 3 else face_img
        mean_val = float(np.mean(gray))
        std_val = float(np.std(gray))
        return mean_val, std_val

    def validate(
        self,
        frame: np.ndarray,
        box: Tuple[int, int, int, int],
        is_upload: bool = False
    ) -> Tuple[bool, float, str]:
        """
        Validates a face crop against quality constraints.
        :param frame: Source image/frame (BGR)
        :param box: (x, y, w, h) bounding box
        :param is_upload: If True, applies stricter enrollment standards
        :return: (is_valid: bool, quality_score: float, reason: str)
        """
        if frame is None or frame.size == 0:
            return False, 0.0, "Frame is empty or invalid"

        x, y, w, h = box
        img_h, img_w = frame.shape[:2]

        # 1. Coordinate sanity check
        x1 = max(0, int(x))
        y1 = max(0, int(y))
        x2 = min(img_w, int(x + w))
        y2 = min(img_h, int(y + h))

        crop_w = x2 - x1
        crop_h = y2 - y1

        if crop_w <= 0 or crop_h <= 0:
            return False, 0.0, "Face box coordinates out of image bounds"

        # 2. Minimum dimension check
        min_dim = self.min_upload_size_px if is_upload else self.min_size_px
        if crop_w < min_dim or crop_h < min_dim:
            return False, 0.0, f"Face too small ({crop_w}x{crop_h}px < min {min_dim}px)"

        # 3. Aspect ratio sanity check (human faces typically 0.5 - 1.8 w/h)
        aspect = crop_w / float(crop_h)
        if aspect < 0.45 or aspect > 2.0:
            return False, 0.0, f"Abnormal face aspect ratio ({aspect:.2f})"

        face_crop = frame[y1:y2, x1:x2]

        # 4. Illumination check
        mean_bright, std_bright = self.calculate_illumination(face_crop)
        if mean_bright < 18.0:
            return False, 0.0, f"Face severely underexposed / dark (brightness {mean_bright:.1f}/255)"
        if mean_bright > 248.0:
            return False, 0.0, f"Face severely overexposed / washed out (brightness {mean_bright:.1f}/255)"
        if std_bright < 10.0:
            return False, 0.0, f"Face contrast too low (std {std_bright:.1f})"

        # 5. Sharpness / Blur check
        sharpness = self.calculate_sharpness(face_crop)
        min_blur = self.min_upload_blur_var if is_upload else self.min_blur_var
        if sharpness < min_blur:
            return False, 0.0, f"Face blurry / out of focus (sharpness {sharpness:.1f} < min {min_blur})"

        # 6. Compute normalized composite quality score (0.0 to 1.0)
        res_factor = min(1.0, crop_w / 120.0)
        sharp_factor = min(1.0, sharpness / 150.0)
        illum_factor = 1.0 - (abs(mean_bright - 128.0) / 128.0) * 0.5
        quality_score = max(0.1, min(1.0, (res_factor * 0.35 + sharp_factor * 0.40 + illum_factor * 0.25)))

        return True, round(quality_score, 2), "Quality verified"

face_quality_validator = FaceQualityValidator()

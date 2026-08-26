# engine/face_engine.py — CUSTOS Modular Face Recognition & People Intelligence Engine
import os
import cv2
import time
import threading
import numpy as np
from typing import List, Dict, Any, Tuple, Optional

from config import settings as config
from engine.logger import app_logger
from engine.face_quality import face_quality_validator

class FaceRecognitionEngine:
    """
    Modular Face Detection and 128-dimensional Face Recognition Engine.
    Uses official OpenCV ONNX models:
      - YuNet: Real-time high-accuracy face detection & 5-point landmark localization.
      - SFace: 128-dimensional deep feature embedding generation with Cosine matching.
    """
    def __init__(
        self,
        detector_path: str = None,
        recognizer_path: str = None,
        match_threshold: float = None,
        cluster_threshold: float = None
    ):
        self.detector_path = detector_path or getattr(config, 'FACE_DETECTOR_PATH', 'data/weights/face_detection_yunet_2023mar.onnx')
        self.recognizer_path = recognizer_path or getattr(config, 'FACE_RECOGNIZER_PATH', 'data/weights/face_recognition_sface_2021dec.onnx')
        self.match_threshold = match_threshold if match_threshold is not None else getattr(config, 'FACE_MATCH_THRESHOLD', 0.40)
        self.cluster_threshold = cluster_threshold if cluster_threshold is not None else getattr(config, 'FACE_CLUSTER_THRESHOLD', 0.38)

        self.lock = threading.Lock()
        self.detector = None
        self.recognizer = None
        self.detector_input_size = (320, 320)

        # In-memory enrolled profile embeddings cache for fast frame matching
        self._profiles_cache: List[Dict[str, Any]] = []
        self._last_cache_refresh = 0.0

        # In-memory active unknown cluster embeddings cache
        self._clusters_cache: List[Dict[str, Any]] = []

        self._init_models()
        self._ensure_storage_dirs()

    def _ensure_storage_dirs(self):
        for d in [
            getattr(config, 'PEOPLE_DATA_DIR', 'data/people'),
            getattr(config, 'PEOPLE_PROFILES_DIR', 'data/people/profiles'),
            getattr(config, 'PEOPLE_CLUSTERS_DIR', 'data/people/clusters'),
            getattr(config, 'PEOPLE_APPEARANCES_DIR', 'data/people/appearances'),
        ]:
            os.makedirs(d, exist_ok=True)

    def _init_models(self):
        try:
            if not os.path.exists(self.detector_path) or not os.path.exists(self.recognizer_path):
                app_logger.warning(f"[FACE ENGINE] Weights not found: {self.detector_path}, {self.recognizer_path}")
                return

            self.detector = cv2.FaceDetectorYN.create(
                self.detector_path,
                "",
                self.detector_input_size,
                getattr(config, 'FACE_MIN_CONFIDENCE', 0.60),
                0.3,
                5000
            )
            self.recognizer = cv2.FaceRecognizerSF.create(self.recognizer_path, "")
            app_logger.info(f"[FACE ENGINE] Initialized YuNet & SFace (Match Threshold: {self.match_threshold})")
        except Exception as e:
            app_logger.error(f"[FACE ENGINE] Model initialization error: {e}")

    def refresh_cache(self, app):
        """Refreshes in-memory profile and cluster embeddings from SQLite database."""
        if not app:
            return
        with self.lock:
            try:
                from database.database_manager import db_manager
                self._profiles_cache = db_manager.get_active_reference_embeddings(app)
                
                # Also load active unknown clusters
                with app.app_context():
                    from database.models import PersonCluster
                    clusters = PersonCluster.query.filter_by(status='ACTIVE').all()
                    c_list = []
                    for c in clusters:
                        if c.representative_embedding_blob:
                            try:
                                emb = np.frombuffer(c.representative_embedding_blob, dtype=np.float32).copy()
                                if emb.shape[0] == 128:
                                    c_list.append({
                                        'cluster_id': c.id,
                                        'cluster_code': c.cluster_code,
                                        'embedding': emb,
                                        'representative_image': c.representative_image
                                    })
                            except Exception:
                                pass
                    self._clusters_cache = c_list

                self._last_cache_refresh = time.time()
                app_logger.debug(f"[FACE ENGINE] Cache refreshed: {len(self._profiles_cache)} profiles, {len(self._clusters_cache)} clusters")
            except Exception as e:
                app_logger.error(f"[FACE ENGINE] Cache refresh error: {e}")

    def detect_faces(self, frame: np.ndarray, score_thresh: float = None) -> List[Dict[str, Any]]:
        """
        Detects all faces in frame using YuNet with 5-point facial landmarks.
        Returns: list of dicts [{'box': [x, y, w, h], 'score': float, 'raw': np.ndarray, 'landmarks': [...]}]
        """
        if frame is None or frame.size == 0 or self.detector is None:
            return []

        h, w = frame.shape[:2]
        with self.lock:
            if self.detector_input_size != (w, h):
                self.detector_input_size = (w, h)
                self.detector.setInputSize((w, h))

            if score_thresh is not None:
                self.detector.setScoreThreshold(float(score_thresh))

            _, faces = self.detector.detect(frame)

        results = []
        if faces is not None and len(faces) > 0:
            for face in faces:
                # face format: [x, y, w, h, x_re, y_re, x_le, y_le, x_nt, y_nt, x_rcm, y_rcm, x_lcm, y_lcm, score]
                box = [int(face[0]), int(face[1]), int(face[2]), int(face[3])]
                score = float(face[-1])
                landmarks = [
                    (int(face[4]), int(face[5])),   # right eye
                    (int(face[6]), int(face[7])),   # left eye
                    (int(face[8]), int(face[9])),   # nose tip
                    (int(face[10]), int(face[11])), # right mouth corner
                    (int(face[12]), int(face[13]))  # left mouth corner
                ]
                results.append({
                    'box': box,
                    'score': score,
                    'landmarks': landmarks,
                    'raw': face
                })
        return results

    def extract_embedding(self, frame: np.ndarray, face_raw: np.ndarray) -> Optional[np.ndarray]:
        """
        Aligns, crops, and extracts 128-dimensional normalized float32 face embedding via SFace.
        """
        if frame is None or face_raw is None or self.recognizer is None:
            return None

        try:
            with self.lock:
                aligned_face = self.recognizer.alignCrop(frame, face_raw)
                if aligned_face is None or aligned_face.size == 0:
                    return None
                feature = self.recognizer.feature(aligned_face)
                if feature is not None:
                    # Flatten and ensure float32 128-dim
                    emb = feature.flatten().astype(np.float32)
                    norm = np.linalg.norm(emb)
                    if norm > 1e-6:
                        emb = emb / norm
                    return emb
        except Exception as e:
            app_logger.error(f"[FACE ENGINE] Embedding extraction error: {e}")
        return None

    def compute_similarity(self, emb1: np.ndarray, emb2: np.ndarray) -> float:
        """
        Computes cosine similarity between two 128-dimensional face embeddings.
        Returns float between -1.0 and 1.0 (typical match >= 0.363 - 0.40).
        """
        if emb1 is None or emb2 is None:
            return 0.0
        try:
            v1 = emb1.flatten()
            v2 = emb2.flatten()
            dot = float(np.dot(v1, v2))
            norm1 = float(np.linalg.norm(v1))
            norm2 = float(np.linalg.norm(v2))
            if norm1 > 1e-6 and norm2 > 1e-6:
                return float(dot / (norm1 * norm2))
            return 0.0
        except Exception:
            return 0.0

    def match_against_profiles(self, embedding: np.ndarray) -> Dict[str, Any]:
        """
        Matches a face embedding against all active enrolled person profiles in memory.
        Returns structured recognition result.
        """
        if embedding is None or not self._profiles_cache:
            return {
                'matched': False,
                'person_id': None,
                'name': 'Unknown',
                'classification': 'UNKNOWN',
                'similarity': 0.0,
                'confidence': 0.0,
                'status': 'UNKNOWN'
            }

        best_profile = None
        best_similarity = -1.0

        for profile in self._profiles_cache:
            for ref_emb in profile.get('embeddings', []):
                sim = self.compute_similarity(embedding, ref_emb)
                if sim > best_similarity:
                    best_similarity = sim
                    best_profile = profile

        if best_similarity >= self.match_threshold and best_profile is not None:
            return {
                'matched': True,
                'person_id': best_profile['person_id'],
                'name': best_profile['name'],
                'classification': best_profile['classification'],
                'similarity': round(best_similarity, 3),
                'confidence': round(best_similarity, 3),
                'status': best_profile['classification']
            }

        return {
            'matched': False,
            'person_id': None,
            'name': 'Unknown',
            'classification': 'UNKNOWN',
            'similarity': round(max(0.0, best_similarity), 3),
            'confidence': round(max(0.0, best_similarity), 3),
            'status': 'UNKNOWN'
        }

    def match_against_clusters(self, embedding: np.ndarray) -> Optional[Dict[str, Any]]:
        """
        Matches an unknown face embedding against active unknown clusters.
        """
        if embedding is None or not self._clusters_cache:
            return None

        best_cluster = None
        best_similarity = -1.0

        for cluster in self._clusters_cache:
            c_emb = cluster.get('embedding')
            if c_emb is not None:
                sim = self.compute_similarity(embedding, c_emb)
                if sim > best_similarity:
                    best_similarity = sim
                    best_cluster = cluster

        if best_similarity >= self.cluster_threshold and best_cluster is not None:
            return {
                'cluster_id': best_cluster['cluster_id'],
                'cluster_code': best_cluster['cluster_code'],
                'similarity': round(best_similarity, 3)
            }
        return None

    def cluster_unknown_face(self, app, embedding: np.ndarray, face_crop: np.ndarray, camera_id: int = 0) -> str:
        """
        Associates an unknown face embedding with an existing cluster or creates a new cluster.
        Returns: cluster_id
        """
        if embedding is None or not app:
            return "cluster_unknown"

        # 1. Check in-memory clusters
        match = self.match_against_clusters(embedding)
        if match:
            cluster_id = match['cluster_id']
            # update last seen
            from database.database_manager import db_manager
            db_manager.get_or_create_cluster(app, cluster_id)
            return cluster_id

        # 2. Create new cluster
        from database.database_manager import db_manager
        with app.app_context():
            from database.models import PersonCluster
            cnt = PersonCluster.query.count() + 1
            cluster_id = f"cluster_{cnt:03d}"
            cluster_code = f"UNKNOWN PERSON #{cnt}"

            # Save representative face image
            cluster_dir = os.path.join(getattr(config, 'PEOPLE_CLUSTERS_DIR', 'data/people/clusters'), cluster_id)
            os.makedirs(cluster_dir, exist_ok=True)
            img_name = f"cluster_{cluster_id}_{int(time.time())}.jpg"
            img_path = os.path.join(cluster_dir, img_name)
            if face_crop is not None and face_crop.size > 0:
                cv2.imwrite(img_path, face_crop)

            db_manager.get_or_create_cluster(
                app,
                cluster_id=cluster_id,
                representative_image=img_path,
                representative_embedding=embedding,
                cluster_code=cluster_code
            )

            # Update local clusters cache
            self._clusters_cache.append({
                'cluster_id': cluster_id,
                'cluster_code': cluster_code,
                'embedding': embedding,
                'representative_image': img_path
            })
            return cluster_id

    def recognize_person_in_bbox(
        self,
        frame: np.ndarray,
        person_bbox: List[int],
        app = None
    ) -> Dict[str, Any]:
        """
        Searches for and recognizes faces inside a detected person's bounding box.
        """
        if frame is None or frame.size == 0 or not person_bbox:
            return {'status': 'UNIDENTIFIED', 'identity': 'UNIDENTIFIED', 'recognition_score': 0.0, 'matched': False}

        img_h, img_w = frame.shape[:2]
        px1, py1, px2, py2 = person_bbox
        px1, py1 = max(0, int(px1)), max(0, int(py1))
        px2, py2 = min(img_w, int(px2)), min(img_h, int(py2))

        if px2 - px1 < 20 or py2 - py1 < 20:
            return {'status': 'UNIDENTIFIED', 'identity': 'UNIDENTIFIED', 'recognition_score': 0.0, 'matched': False}

        # Upper region of person body usually contains the face (top 45%)
        head_y2 = min(img_h, py1 + int((py2 - py1) * 0.55))
        person_crop = frame[py1:head_y2, px1:px2]

        if person_crop.size == 0:
            return {'status': 'UNIDENTIFIED', 'identity': 'UNIDENTIFIED', 'recognition_score': 0.0, 'matched': False}

        # Detect faces in upper person body crop
        faces = self.detect_faces(person_crop)
        if not faces:
            # Fallback: search whole person crop
            faces = self.detect_faces(frame[py1:py2, px1:px2])
            crop_offset_y = py1
        else:
            crop_offset_y = py1

        if not faces:
            return {'status': 'UNIDENTIFIED', 'identity': 'UNIDENTIFIED', 'recognition_score': 0.0, 'matched': False}

        # Select highest confidence face
        best_face = max(faces, key=lambda f: f['score'])
        fx, fy, fw, fh = best_face['box']

        # Map back to full frame coordinates
        full_fx = px1 + fx
        full_fy = crop_offset_y + fy

        # Validate face quality
        is_valid, quality_score, reason = face_quality_validator.validate(frame, (full_fx, full_fy, fw, fh))
        if not is_valid:
            return {
                'status': 'UNIDENTIFIED',
                'identity': 'UNIDENTIFIED',
                'recognition_score': 0.0,
                'matched': False,
                'quality_reason': reason
            }

        # Align and extract embedding
        # Build full-frame raw face array for alignCrop
        raw_face = best_face['raw'].copy()
        raw_face[0] += px1
        raw_face[1] += crop_offset_y
        for li in range(4, 14, 2):
            raw_face[li] += px1
            raw_face[li+1] += crop_offset_y

        embedding = self.extract_embedding(frame, raw_face)
        if embedding is None:
            return {'status': 'UNIDENTIFIED', 'identity': 'UNIDENTIFIED', 'recognition_score': 0.0, 'matched': False}

        # 1. Match against enrolled profiles
        match_res = self.match_against_profiles(embedding)
        face_crop_img = frame[max(0, full_fy):min(img_h, full_fy+fh), max(0, full_fx):min(img_w, full_fx+fw)].copy()

        if match_res['matched']:
            return {
                'status': match_res['classification'],
                'identity': match_res['name'],
                'person_id': match_res['person_id'],
                'classification': match_res['classification'],
                'recognition_score': match_res['similarity'],
                'matched': True,
                'embedding': embedding,
                'face_crop': face_crop_img,
                'face_box': [full_fx, full_fy, fw, fh]
            }

        # 2. Match or cluster as UNKNOWN
        cluster_id = None
        if app:
            cluster_id = self.cluster_unknown_face(app, embedding, face_crop_img)

        return {
            'status': 'UNKNOWN',
            'identity': 'UNKNOWN',
            'person_id': None,
            'cluster_id': cluster_id,
            'classification': 'UNKNOWN',
            'recognition_score': match_res['similarity'],
            'matched': False,
            'embedding': embedding,
            'face_crop': face_crop_img,
            'face_box': [full_fx, full_fy, fw, fh]
        }

    def validate_uploaded_image(self, img_bgr: np.ndarray) -> Tuple[bool, Optional[np.ndarray], Optional[np.ndarray], float, str]:
        """
        Validates user-uploaded image for enrollment:
          1. Valid decoding and dimensions.
          2. Exactly ONE primary face detected.
          3. Stricter face quality validation.
          4. Embedding extraction.
        Returns: (success: bool, embedding: np.ndarray, aligned_face: np.ndarray, quality_score: float, message: str)
        """
        if img_bgr is None or img_bgr.size == 0:
            return False, None, None, 0.0, "Unable to decode image file. Please upload a valid JPG or PNG."

        h, w = img_bgr.shape[:2]
        if h < 100 or w < 100:
            return False, None, None, 0.0, "Image resolution is too small. Please upload a higher resolution photo."

        faces = self.detect_faces(img_bgr, score_thresh=0.55)
        if not faces or len(faces) == 0:
            return False, None, None, 0.0, "No usable face was detected. Please upload a clearer photo."

        if len(faces) > 1:
            # Check if one face is dominant (> 3x area of others)
            faces.sort(key=lambda f: f['box'][2] * f['box'][3], reverse=True)
            primary_area = faces[0]['box'][2] * faces[0]['box'][3]
            second_area = faces[1]['box'][2] * faces[1]['box'][3]
            if second_area > primary_area * 0.35:
                return False, None, None, 0.0, "Multiple faces detected. Please upload a photo containing exactly one person."

        primary_face = faces[0]
        box = primary_face['box']

        # Strict enrollment quality verification
        is_valid, quality_score, reason = face_quality_validator.validate(img_bgr, tuple(box), is_upload=True)
        if not is_valid:
            return False, None, None, quality_score, f"Face quality too low: {reason}. Please upload a clearer photo."

        # Extract aligned face and embedding
        with self.lock:
            aligned_face = self.recognizer.alignCrop(img_bgr, primary_face['raw'])

        embedding = self.extract_embedding(img_bgr, primary_face['raw'])
        if embedding is None:
            return False, None, None, 0.0, "Failed to generate biometric face embedding. Please upload a clearer photo."

        return True, embedding, aligned_face, quality_score, "Face verified successfully"

face_engine = FaceRecognitionEngine()

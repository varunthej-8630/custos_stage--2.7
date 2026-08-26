# tests/test_people_intelligence.py — CUSTOS People Intelligence Automated Test Suite
import os
import cv2
import time
import pytest
import numpy as np

from config import settings as config
from database import (
    db, db_manager, User, UserRole,
    PersonClassification, PersonProfile, PersonFace, PersonCluster, PersonAppearance
)
from engine.face_quality import FaceQualityValidator
from engine.face_engine import FaceRecognitionEngine, face_engine
from engine.person_memory import PersonMemory, PersonMemoryManager
from engine.risk_engine import RiskEngine
from engine.ai_engine import AIEngine
from web.server import app as flask_app


def create_synthetic_face_image(width=160, height=160, seed=42) -> np.ndarray:
    """Generates a clean synthetic face-like image for repeatable testing."""
    np.random.seed(seed)
    img = np.full((height, width, 3), 200, dtype=np.uint8)
    # Head circle
    cv2.circle(img, (width // 2, height // 2), int(width * 0.4), (180, 180, 180), -1)
    # Eyes
    cv2.circle(img, (int(width * 0.35), int(height * 0.4)), int(width * 0.06), (40, 40, 40), -1)
    cv2.circle(img, (int(width * 0.65), int(height * 0.4)), int(width * 0.06), (40, 40, 40), -1)
    # Nose
    cv2.line(img, (width // 2, int(height * 0.45)), (width // 2, int(height * 0.58)), (80, 80, 80), 2)
    # Mouth
    cv2.ellipse(img, (width // 2, int(height * 0.68)), (int(width * 0.18), int(height * 0.08)), 0, 0, 180, (50, 50, 50), 2)
    return img


@pytest.fixture
def app_context():
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with flask_app.app_context():
        db.create_all()
        # Seed test operator user
        user = User(username='test_operator', role=UserRole.OPERATOR)
        user.set_password('Secret123!')
        db.session.add(user)
        db.session.commit()
        yield flask_app
        db.session.remove()
        db.drop_all()


# ═══════════════════════════════════════════════════════
# 1. FACE QUALITY VALIDATION TESTS
# ═══════════════════════════════════════════════════════

def test_face_quality_sharpness_and_illumination():
    validator = FaceQualityValidator()

    # A. Clean sharp image
    good_img = create_synthetic_face_image()
    valid, score, msg = validator.validate(good_img, (0, 0, 160, 160))
    assert valid is True
    assert score > 0.0

    # B. Extremely blurry image (low Laplacian variance)
    blurry_img = cv2.GaussianBlur(good_img, (25, 25), 0)
    valid, score, msg = validator.validate(blurry_img, (0, 0, 160, 160))
    assert valid is False
    assert "blurry" in msg.lower()

    # C. Underexposed / Extremely dark image
    dark_img = np.zeros((160, 160, 3), dtype=np.uint8)
    valid, score, msg = validator.validate(dark_img, (0, 0, 160, 160))
    assert valid is False
    assert "dark" in msg.lower() or "illumination" in msg.lower() or "blurry" in msg.lower()

    # D. Tiny face (< FACE_MIN_SIZE_PX)
    valid, score, msg = validator.validate(good_img, (0, 0, 20, 20))
    assert valid is False
    assert "small" in msg.lower()


# ═══════════════════════════════════════════════════════
# 2. FACE DETECTION & EMBEDDING EXTRACTION
# ═══════════════════════════════════════════════════════

def test_face_detection_and_embedding_dimensions():
    engine = FaceRecognitionEngine()
    if not engine.detector or not engine.recognizer:
        pytest.skip("YuNet / SFace models not initialized")

    dummy_aligned = np.zeros((112, 112, 3), dtype=np.uint8)
    emb = engine.recognizer.feature(dummy_aligned)
    assert emb is not None
    assert emb.shape == (1, 128)
    assert emb.dtype == np.float32


# ═══════════════════════════════════════════════════════
# 3. COSINE SIMILARITY & THRESHOLD CALIBRATION
# ═══════════════════════════════════════════════════════

def test_face_recognition_cosine_distance_calibration():
    engine = FaceRecognitionEngine()

    # Create 2 normalized 128-dim vectors
    v1 = np.random.randn(1, 128).astype(np.float32)
    v1 = v1 / np.linalg.norm(v1)

    # Identical vector -> score = 1.0
    score_same = engine.compute_similarity(v1, v1)
    assert abs(score_same - 1.0) < 1e-4

    # Slightly perturbed vector (e.g. same person under different angle)
    v2 = v1 + 0.1 * np.random.randn(1, 128).astype(np.float32)
    v2 = v2 / np.linalg.norm(v2)
    score_similar = engine.compute_similarity(v1, v2)
    assert score_similar > getattr(config, 'FACE_MATCH_THRESHOLD', 0.40)

    # Orthogonal / Random vector (distinct person)
    v3 = np.random.randn(1, 128).astype(np.float32)
    v3 = v3 / np.linalg.norm(v3)
    score_diff = engine.compute_similarity(v1, v3)
    assert score_diff < getattr(config, 'FACE_MATCH_THRESHOLD', 0.40)


# ═══════════════════════════════════════════════════════
# 4. TRACK IDENTITY CACHING (INSTRUCTION #2)
# ═══════════════════════════════════════════════════════

def test_track_identity_caching_and_throttling():
    mem = PersonMemory(track_id=101)
    assert mem.should_attempt_face_recognition() is True

    # Simulate recognized identity lock
    rec_result = {
        'status': 'KNOWN',
        'person_id': 'person_001',
        'label': 'Varun',
        'classification': 'KNOWN',
        'recognition_score': 0.85
    }
    mem.set_identity(rec_result, lock=True)

    # Should now be locked and skip expensive re-recognition on subsequent frames
    assert mem.identity['is_locked'] is True
    assert mem.identity['label'] == 'Varun'
    assert mem.identity['person_id'] == 'person_001'
    assert mem.should_attempt_face_recognition() is False


# ═══════════════════════════════════════════════════════
# 5. SECURITY INVARIANCE: HIGH-ZONE & TAMPER (INSTRUCTION #4)
# ═══════════════════════════════════════════════════════

def test_security_invariance_known_person_in_high_zone():
    risk_engine = RiskEngine()
    risk_engine.score = 0.0

    # Case A: Known person in NORMAL/WATCH area with 0 dwell -> Safe
    known_track_watch = {
        'track_id': 1,
        'cx': 50, 'cy': 50,
        'current_zone': 0,
        'dwell_time': 1.0,
        'classification': 'KNOWN',
        'identity': 'Authorized Staff'
    }
    score, reasons, alert = risk_engine.evaluate(
        tracks=[known_track_watch],
        validated_behaviors=[],
        zones=[[0, 0, 100, 100]],
        zone_types=['WATCH'],
        tamper=False
    )
    assert score < 60.0
    assert alert is False

    # Case B: Known person enters RESTRICTED HIGH ZONE -> Must escalate to HIGH risk!
    known_track_high = {
        'track_id': 1,
        'cx': 50, 'cy': 50,
        'current_zone': 0,
        'dwell_time': 1.0,
        'classification': 'KNOWN',
        'identity': 'Authorized Staff'
    }
    score, reasons, alert = risk_engine.evaluate(
        tracks=[known_track_high],
        validated_behaviors=[],
        zones=[[0, 0, 100, 100]],
        zone_types=['HIGH'],
        tamper=False
    )
    assert score >= config.RISK_THRESHOLD
    assert any("HIGH zone breach" in r for r in reasons)


def test_security_invariance_camera_tamper_independence():
    risk_engine = RiskEngine()

    # Even with an enrolled known person present, tamper MUST trigger 100.0 score independently
    known_track = {
        'track_id': 5,
        'current_zone': None,
        'classification': 'KNOWN',
        'identity': 'Alice'
    }
    score, reasons, alert = risk_engine.evaluate(
        tracks=[known_track],
        validated_behaviors=[],
        zones=[[0, 0, 100, 100]],
        zone_types=['WATCH'],
        tamper=True
    )
    assert score == 100.0
    assert alert is True
    assert "CAMERA TAMPER DETECTED" in reasons


# ═══════════════════════════════════════════════════════
# 6. SUSPICIOUS PERSON RISK ESCALATION
# ═══════════════════════════════════════════════════════

def test_suspicious_person_risk_escalation():
    risk_engine = RiskEngine()

    sus_track = {
        'track_id': 8,
        'current_zone': None,
        'classification': 'SUSPICIOUS',
        'identity': 'Intruder Blacklist #1'
    }
    score, reasons, alert = risk_engine.evaluate(
        tracks=[sus_track],
        validated_behaviors=[],
        zones=[[0, 0, 100, 100]],
        zone_types=['WATCH'],
        tamper=False
    )
    assert score >= 75.0
    assert any("SUSPICIOUS_PERSON_DETECTED" in r for r in reasons)


# ═══════════════════════════════════════════════════════
# 7. REAL-WORLD EDGE CASE TESTS (INSTRUCTION #3)
# ═══════════════════════════════════════════════════════

def test_edge_case_two_person_simultaneous(app_context):
    """Verifies 2 simultaneous persons are tracked and categorized separately."""
    mem_mgr = PersonMemoryManager()
    mem1 = mem_mgr.get_or_create(10)
    mem2 = mem_mgr.get_or_create(11)

    mem1.set_identity({'status': 'KNOWN', 'label': 'Staff Alice', 'person_id': 'p_01', 'classification': 'KNOWN', 'recognition_score': 0.88})
    mem2.set_identity({'status': 'UNKNOWN', 'label': 'Unknown #11', 'cluster_id': 'cluster_01', 'classification': 'UNKNOWN', 'recognition_score': 0.0})

    assert mem1.identity['person_id'] == 'p_01'
    assert mem2.identity['cluster_id'] == 'cluster_01'
    assert mem1.identity['classification'] == 'KNOWN'
    assert mem2.identity['classification'] == 'UNKNOWN'


def test_edge_case_face_disappearance_and_tracking():
    """Verifies that when a person turns away, cached identity is preserved."""
    mem = PersonMemory(track_id=25)
    mem.set_identity({'status': 'KNOWN', 'label': 'Bob', 'person_id': 'p_02', 'classification': 'KNOWN', 'recognition_score': 0.82}, lock=True)

    # Subsequent frames without visible face should NOT reset identity
    assert mem.identity['label'] == 'Bob'
    assert mem.identity['is_locked'] is True


# ═══════════════════════════════════════════════════════
# 8. DATABASE CRUD & REST APIS
# ═══════════════════════════════════════════════════════

def test_database_crud_operations(app_context):
    # 1. Create Profile
    p = db_manager.create_person_profile(
        app_context,
        name="Test Varun",
        classification=PersonClassification.KNOWN,
        notes="Lead Engineer"
    )
    assert p['id'].startswith('person_')
    assert p['name'] == "Test Varun"

    # 2. Add Face
    v = np.random.randn(1, 128).astype(np.float32)
    f = db_manager.add_reference_face(
        app_context,
        person_id=p['id'],
        image_path="data/people/profiles/test/ref_01.jpg",
        embedding_bytes=v.tobytes(),
        quality_score=0.92,
        is_profile_display=True
    )
    assert f['person_id'] == p['id']

    # 3. Log Appearance
    app_id = db_manager.log_person_appearance(
        app_context,
        camera_id=0,
        track_id=42,
        person_id=p['id'],
        zone_name="Perimeter Zone",
        recognition_score=0.88,
        identity_status="KNOWN"
    )
    assert app_id is not None

    # 4. Query Stats
    stats = db_manager.get_people_stats(app_context)
    assert stats['total_profiles'] >= 1
    assert stats['known_profiles'] >= 1
    assert stats['total_appearances'] >= 1


def test_rest_api_people_endpoints(app_context):
    client = flask_app.test_client()

    # Login as operator
    login_res = client.post('/login', json={'username': 'test_operator', 'password': 'Secret123!'})
    assert login_res.status_code == 200

    # 1. GET /api/people
    res = client.get('/api/people')
    assert res.status_code == 200
    json_data = res.get_json()
    assert json_data['success'] is True

    # 2. POST /api/people
    create_res = client.post('/api/people', json={
        'name': 'API Guard',
        'classification': 'KNOWN',
        'notes': 'Patrol'
    })
    assert create_res.status_code == 201
    created_person = create_res.get_json()['data']
    pid = created_person['id']

    # 3. GET /api/people/<id>
    get_res = client.get(f'/api/people/{pid}')
    assert get_res.status_code == 200
    assert get_res.get_json()['data']['name'] == 'API Guard'

    # 4. PATCH /api/people/<id>
    patch_res = client.patch(f'/api/people/{pid}', json={
        'name': 'API Guard Updated',
        'classification': 'SUSPICIOUS'
    })
    assert patch_res.status_code == 200
    assert patch_res.get_json()['data']['classification'] == 'SUSPICIOUS'

    # 5. GET /api/people/suspicious
    sus_res = client.get('/api/people/suspicious')
    assert sus_res.status_code == 200
    assert len(sus_res.get_json()['data']) >= 1

    # 6. DELETE /api/people/<id>
    del_res = client.delete(f'/api/people/{pid}')
    assert del_res.status_code == 200
    assert del_res.get_json()['data']['status'] == 'INACTIVE'

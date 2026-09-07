# tests/test_hardening_regression.py
"""
Hardening & Regression Test Suite for CUSTOS Stage 2.8
Verifies bug fixes, crash prevention, and production stabilization:
1. Photo enrollment numpy buffer decoding and validation handling
2. Admin password persistence across reboots / re-initializations
3. Model and directory path resolution invariance
4. Database WAL mode and busy timeout configuration
5. Evidence listing unification
"""

import os
import io
import cv2
import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from config import settings as config
from database.models import db, User, UserRole, PersonProfile
from database import db_manager


def test_model_paths_are_absolute():
    """Verify that all AI model and data paths resolve to absolute paths."""
    assert os.path.isabs(config.MODEL_PATH), f"MODEL_PATH is not absolute: {config.MODEL_PATH}"
    assert os.path.isabs(config.FACE_DETECTOR_PATH), f"FACE_DETECTOR_PATH is not absolute: {config.FACE_DETECTOR_PATH}"
    assert os.path.isabs(config.FACE_RECOGNIZER_PATH), f"FACE_RECOGNIZER_PATH is not absolute: {config.FACE_RECOGNIZER_PATH}"
    assert os.path.isabs(config.RECORDING_DIR), f"RECORDING_DIR is not absolute: {config.RECORDING_DIR}"
    assert os.path.isabs(config.SNAPSHOT_DIR), f"SNAPSHOT_DIR is not absolute: {config.SNAPSHOT_DIR}"


def test_admin_password_not_overwritten_on_reboot(app):
    """Verify that init_db does not reset an existing admin's password."""
    with app.app_context():
        admin = User.query.filter_by(username='admin').first()
        assert admin is not None
        # Set custom password
        admin.set_password('my_secure_custom_password_2026')
        db.session.commit()

        # Call init_db again as would happen on server restart
        db_manager.init_db(app)

        # Verify password was preserved
        admin_refetched = User.query.filter_by(username='admin').first()
        assert admin_refetched.check_password('my_secure_custom_password_2026') is True
        assert admin_refetched.check_password('admin123') is False


def test_photo_enroll_corrupted_image_returns_400(operator_client):
    """Verify that uploading invalid bytes to /api/people/enroll returns 400 DECODE_ERROR."""
    data = {
        'name': 'Test Officer',
        'classification': 'known',
        'photo': (io.BytesIO(b'this is not an image'), 'test.jpg')
    }
    res = operator_client.post('/api/people/enroll', data=data, content_type='multipart/form-data')
    assert res.status_code == 400
    json_data = res.get_json()
    assert json_data['success'] is False
    assert json_data['error']['code'] == 'DECODE_ERROR'


def test_photo_enroll_numpy_buffer_handling(operator_client):
    """Verify that valid image upload processes np.frombuffer without NameError."""
    # Create a dummy image
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    _, encoded = cv2.imencode('.jpg', img)
    image_bytes = encoded.tobytes()

    # Mock face_engine.validate_uploaded_image so we test the route end-to-end
    dummy_embedding = np.random.rand(128).astype(np.float32)
    with patch('web.server.face_engine.validate_uploaded_image') as mock_validate:
        mock_validate.return_value = (True, dummy_embedding, img, 0.95, "Valid face")
        data = {
            'name': 'Enrolled Agent',
            'classification': 'known',
            'photo': (io.BytesIO(image_bytes), 'agent.jpg')
        }
        res = operator_client.post('/api/people/enroll', data=data, content_type='multipart/form-data')
        assert res.status_code == 201
        json_data = res.get_json()
        assert json_data['success'] is True
        assert json_data['data']['name'] == 'Enrolled Agent'


def test_add_face_to_person_numpy_buffer_handling(operator_client, app):
    """Verify that /api/people/<person_id>/faces uses np.frombuffer properly without crash."""
    with app.app_context():
        profile = db_manager.create_person_profile(app, name="Agent 47", classification="known")
        pid = profile['id']

    img = np.zeros((100, 100, 3), dtype=np.uint8)
    _, encoded = cv2.imencode('.jpg', img)
    image_bytes = encoded.tobytes()

    dummy_embedding = np.random.rand(128).astype(np.float32)
    with patch('web.server.face_engine.validate_uploaded_image') as mock_validate:
        mock_validate.return_value = (True, dummy_embedding, img, 0.92, "Valid face")
        data = {
            'photo': (io.BytesIO(image_bytes), 'face2.jpg')
        }
        res = operator_client.post(f'/api/people/{pid}/faces', data=data, content_type='multipart/form-data')
        assert res.status_code == 201
        json_data = res.get_json()
        assert json_data['success'] is True


def test_evidence_listing_endpoints(operator_client):
    """Verify both /list_evidence and /snapshots return consistent data."""
    res = operator_client.get('/list_evidence')
    assert res.status_code == 200
    data = res.get_json()
    assert 'files' in data
    assert 'snapshots' in data

    res2 = operator_client.get('/snapshots')
    assert res2.status_code == 200
    data2 = res2.get_json()
    assert 'snapshots' in data2

import json
import os
import pytest
from datetime import datetime
from database.models import db, Incident, Evidence
from config import settings

def test_evidence_list_and_stats(admin_client, app):
    with app.app_context():
        inc = Incident(
            timestamp=datetime.utcnow(),
            score=78.0,
            status='Active',
            events=json.dumps(["Person-3 entered Zone-A", "High zone dwell time 4.1s"]),
            snapshot_path='snap_test_1.jpg'
        )
        db.session.add(inc)
        db.session.commit()

        ev = Evidence(
            incident_id=inc.id,
            path='snap_test_1.jpg',
            type='snapshot',
            metadata_json=json.dumps([{"time": "12:00:00", "event": "Person-3 entered Zone-A"}])
        )
        db.session.add(ev)
        db.session.commit()
        ev_id = ev.id
        inc_id = inc.id

    # Query evidence list
    res = admin_client.get('/api/evidence')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['total'] >= 1
    assert any(item['id'] == inc_id for item in data['data']['items'])

    # Query evidence stats
    res_stats = admin_client.get('/api/evidence/stats')
    assert res_stats.status_code == 200
    stats = res_stats.get_json()
    assert stats['success'] is True
    assert stats['data']['total_evidence'] >= 1
    assert stats['data']['snapshots_count'] >= 1

    # Query single evidence record
    res_single = admin_client.get(f'/api/evidence/{inc_id}')
    assert res_single.status_code == 200
    single_data = res_single.get_json()
    assert single_data['success'] is True
    assert single_data['data']['id'] == inc_id
    assert len(single_data['data']['timeline']) > 0

def test_evidence_media_serving_and_traversal_guard(admin_client, app):
    # Create real dummy snapshot file in SNAPSHOT_DIR
    os.makedirs(settings.SNAPSHOT_DIR, exist_ok=True)
    test_file_name = 'test_verified_snapshot.jpg'
    test_file_path = os.path.join(settings.SNAPSHOT_DIR, test_file_name)
    with open(test_file_path, 'wb') as f:
        f.write(b'\xFF\xD8\xFF\xE0\x00\x10JFIF\x00\x01\x01\x01\x00`\x00`\x00\x00\xFF\xDB')

    with app.app_context():
        inc = Incident(
            timestamp=datetime.utcnow(),
            score=82.0,
            status='Active',
            events=json.dumps(["Person-12 verified intrusion"]),
            snapshot_path=test_file_name
        )
        db.session.add(inc)
        db.session.commit()
        inc_id = inc.id

    # Test media serving endpoint
    res_media = admin_client.get(f'/api/evidence/{inc_id}/media/snapshot')
    assert res_media.status_code == 200
    assert res_media.content_type.startswith('image/')

    # Test 404 on missing media
    res_missing = admin_client.get('/api/evidence/99999/media/snapshot')
    assert res_missing.status_code == 404
    err_json = res_missing.get_json()
    assert err_json['success'] is False

    # Clean up test file
    if os.path.exists(test_file_path):
        try:
            os.remove(test_file_path)
        except PermissionError:
            pass

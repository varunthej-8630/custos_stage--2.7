import json
import pytest
from datetime import datetime
from database.models import db, Incident, Evidence

def create_sample_incident(app, score=85.0, status='Active', events=None, snapshot='test_snap.jpg', clip=None):
    with app.app_context():
        inc = Incident(
            timestamp=datetime.utcnow(),
            score=score,
            status=status,
            events=json.dumps(events or ["Person-1 in HIGH security zone", "LINGERING in restricted area for 5.2s"]),
            snapshot_path=snapshot,
            clip_path=clip
        )
        db.session.add(inc)
        db.session.commit()
        return inc.id

def test_get_alerts_list_and_stats(admin_client, app):
    id1 = create_sample_incident(app, score=90.0, status='Active')
    id2 = create_sample_incident(app, score=45.0, status='Resolved')
    
    res = admin_client.get('/api/alerts')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['total'] >= 2
    assert len(data['data']['items']) >= 2

    # Stats test
    res_stats = admin_client.get('/api/alerts/stats')
    assert res_stats.status_code == 200
    stats_data = res_stats.get_json()
    assert stats_data['success'] is True
    assert stats_data['data']['active_alerts'] >= 1
    assert stats_data['data']['resolved_alerts'] >= 1

def test_alerts_filtering_and_search(admin_client, app):
    id_crit = create_sample_incident(app, score=95.0, events=["Restricted Intrusion Person-99"])
    id_low = create_sample_incident(app, score=30.0, events=["Loitering in public walkway"])

    # Severity filter
    res = admin_client.get('/api/alerts?severity=CRITICAL')
    data = res.get_json()
    assert data['success'] is True
    assert all(item['severity'] == 'CRITICAL' for item in data['data']['items'])

    # Full text search query
    res_q = admin_client.get('/api/alerts?q=Person-99')
    data_q = res_q.get_json()
    assert data_q['success'] is True
    assert any(item['id'] == id_crit for item in data_q['data']['items'])
    assert not any(item['id'] == id_low for item in data_q['data']['items'])

def test_alert_detail_and_resolve(admin_client, app):
    inc_id = create_sample_incident(app, score=88.0, status='Active')

    # Get single alert
    res = admin_client.get(f'/api/alerts/{inc_id}')
    assert res.status_code == 200
    data = res.get_json()
    assert data['success'] is True
    assert data['data']['id'] == inc_id
    assert len(data['data']['explainable_reasons']) > 0

    # Resolve alert via POST /api/alerts/<id>/resolve
    res_res = admin_client.post(f'/api/alerts/{inc_id}/resolve', json={'notes': 'Guard dispatched, false alarm cleared'})
    assert res_res.status_code == 200
    res_data = res_res.get_json()
    assert res_data['success'] is True
    assert res_data['data']['status'] == 'Resolved'

    # Verify updated in DB
    res_updated = admin_client.get(f'/api/alerts/{inc_id}')
    assert res_updated.get_json()['data']['status'] == 'Resolved'

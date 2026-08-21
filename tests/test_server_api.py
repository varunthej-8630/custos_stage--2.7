import json
from web.models import db, Incident, User, UserRole

def test_ping_endpoint(client):
    res = client.get('/ping')
    assert res.status_code == 200
    data = res.get_json()
    assert data['status'] == 'ok'
    assert 'ts' in data

def test_login_success(client):
    res = client.post('/login', data={'username': 'admin', 'password': 'adminpass'}, follow_redirects=True)
    assert res.status_code == 200

def test_login_failure(client):
    res = client.post('/login', data={'username': 'admin', 'password': 'wrongpassword'})
    assert res.status_code == 200
    assert b'Invalid credentials' in res.data

def test_unauthorized_access(client):
    res = client.get('/api/incidents')
    assert res.status_code in (302, 401)


def test_incidents_crud_and_filtering(app, operator_client):
    with app.app_context():
        inc1 = Incident(score=90.0, events='["RESTRICTED AREA"]', status='New', snapshot_path='snap1.jpg')
        inc2 = Incident(score=45.0, events='["PACING"]', status='Resolved', snapshot_path='snap2.jpg')
        inc3 = Incident(score=75.0, events='["CROUCHING"]', status='New', snapshot_path='snap3.jpg')
        db.session.add_all([inc1, inc2, inc3])
        db.session.commit()
        inc1_id, inc2_id, inc3_id = inc1.id, inc2.id, inc3.id

    # 1. Fetch all incidents
    res = operator_client.get('/api/incidents')
    assert res.status_code == 200
    incidents = res.get_json()
    assert len(incidents) >= 3

    # 2. Filter by status=New
    res_new = operator_client.get('/api/incidents?status=New')
    assert res_new.status_code == 200
    new_incidents = res_new.get_json()
    assert all(i['status'] == 'New' for i in new_incidents)

    # 3. Filter by min_score=80
    res_high = operator_client.get('/api/incidents?min_score=80')
    assert res_high.status_code == 200
    high_incidents = res_high.get_json()
    assert all(i['score'] >= 80 for i in high_incidents)

    # 4. Search query q=CROUCHING
    res_search = operator_client.get('/api/incidents?q=CROUCHING')
    assert res_search.status_code == 200
    search_incidents = res_search.get_json()
    assert len(search_incidents) >= 1
    assert 'CROUCHING' in search_incidents[0]['events']

    # 5. Resolve incident
    res_resolve = operator_client.post(f'/api/incidents/{inc1_id}/resolve', json={'notes': 'Resolved by operator'})
    assert res_resolve.status_code == 200
    assert res_resolve.get_json()['success'] is True

    # 6. Delete incident
    res_del = operator_client.delete(f'/api/incidents/{inc3_id}')
    assert res_del.status_code == 200
    assert res_del.get_json()['success'] is True

def test_rbac_viewer_forbidden(app, viewer_client):
    with app.app_context():
        inc = Incident(score=88.0, events='["HIGH ZONE BREACH"]', status='New')
        db.session.add(inc)
        db.session.commit()
        inc_id = inc.id

    # Viewer should be forbidden (403) from resolving incidents
    res_v = viewer_client.post(f'/api/incidents/{inc_id}/resolve', json={'notes': 'Viewer try'})
    assert res_v.status_code == 403

def test_rbac_operator_allowed(app, operator_client):
    with app.app_context():
        inc = Incident(score=88.0, events='["HIGH ZONE BREACH"]', status='New')
        db.session.add(inc)
        db.session.commit()
        inc_id = inc.id

    # Operator should succeed (200)
    res_o = operator_client.post(f'/api/incidents/{inc_id}/resolve', json={'notes': 'Operator ok'})
    assert res_o.status_code == 200

def test_list_cameras_endpoint(operator_client):
    res = operator_client.get('/list_cameras')
    assert res.status_code == 200
    data = res.get_json()
    assert 'cameras' in data

def test_list_evidence_endpoint(operator_client):
    res = operator_client.get('/list_evidence')
    assert res.status_code == 200
    data = res.get_json()
    assert data is not None



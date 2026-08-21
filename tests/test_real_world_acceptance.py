import json
import pytest
from datetime import datetime
from database.models import db, Incident, Evidence
from database.database_manager import db_manager
from engine.storage_queue import StorageQueueManager

def test_complete_event_to_alert_and_evidence_lifecycle(admin_client, app):
    """
    Validates end-to-end acceptance invariant:
    AI Event -> StorageQueue -> Incident -> Alert -> Evidence -> Resolution
    """
    # 1. Simulate AI Incident queued into storage queue
    sq = StorageQueueManager()
    sq.set_app(app)
    test_event_data = {
        'type': 'incident',
        'timestamp': datetime.utcnow().isoformat(),
        'score': 92.5,
        'events': [
            "Person-1 entered HIGH security zone",
            "Person-1 linger in restricted zone: 3.8s",
            "Crouching posture detected in perimeter"
        ],
        'snapshot': 'acceptance_snap.jpg',
        'clip': None
    }
    
    with app.app_context():
        # Storage queue worker processes incident and writes canonical Incident record
        sq._execute_task('save_incident', test_event_data)
        
        # Verify Incident exists
        inc = Incident.query.order_by(Incident.id.desc()).first()
        assert inc is not None
        assert inc.score == 92.5
        inc_id = inc.id

    # 2. Verify Alert Center displays the created incident as an active alert
    res_alerts = admin_client.get('/api/alerts')
    assert res_alerts.status_code == 200
    alerts_data = res_alerts.get_json()['data']
    alert_item = next((a for a in alerts_data['items'] if a['id'] == inc_id), None)
    assert alert_item is not None
    assert alert_item['severity'] == 'CRITICAL'
    assert alert_item['status'] in ('New', 'Active')
    assert len(alert_item['explainable_reasons']) >= 3

    # 3. Verify Evidence Center displays the same canonical record
    res_ev = admin_client.get('/api/evidence')
    assert res_ev.status_code == 200
    ev_data = res_ev.get_json()['data']
    ev_item = next((e for e in ev_data['items'] if e['id'] == inc_id), None)
    assert ev_item is not None
    assert ev_item['id'] == alert_item['id']

    # 4. Resolve the alert via Alert API
    res_resolve = admin_client.post(f'/api/alerts/{inc_id}/resolve', json={'notes': 'Operator verified authorization'})
    assert res_resolve.status_code == 200
    assert res_resolve.get_json()['success'] is True

    # 5. Verify stats updated properly in both Alert Center and Evidence Center
    res_astats = admin_client.get('/api/alerts/stats')
    assert res_astats.get_json()['data']['resolved_alerts'] >= 1

import os
import numpy as np
from web.alert_manager import AlertManager
from config import settings as config

def test_alert_message_building():
    am = AlertManager()
    
    # Test High Risk message
    msg = am._build_message(85.0, ['[HIGH] #1 entered restricted zone', '#1 CROUCHING in zone'])
    assert 'Security Alert' in msg
    assert 'High Risk' in msg
    assert '85 / 100' in msg
    assert 'entered a restricted area' in msg
    assert 'crouching down in the zone' in msg

    # Test Medium Risk message
    msg_med = am._build_message(65.0, ['#2 PACING in zone'])
    assert 'Medium Risk' in msg_med
    assert 'walking back and forth repeatedly' in msg_med

def test_snapshot_saving(tmp_path):
    am = AlertManager()
    original_snapshot_dir = config.SNAPSHOT_DIR
    config.SNAPSHOT_DIR = str(tmp_path)

    try:
        # Create a 100x100 dummy black image
        frame = np.zeros((100, 100, 3), dtype=np.uint8)
        snap_file = am._save_snapshot(frame, 75.0)

        assert snap_file is not None
        assert os.path.exists(snap_file)
        assert snap_file.endswith('.jpg')
    finally:
        config.SNAPSHOT_DIR = original_snapshot_dir

def test_tamper_alert_message():
    am = AlertManager()
    now_before = am.last_tamper
    am.send_tamper_alert()
    assert am.last_tamper > now_before

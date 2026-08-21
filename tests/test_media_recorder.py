import os
import cv2
import time
import numpy as np
import pytest

from engine.media_recorder import IncidentMediaRecorder

@pytest.fixture
def temp_media_recorder(tmp_path):
    snap_dir = tmp_path / "snapshots"
    snap_dir.mkdir()
    return IncidentMediaRecorder(snapshot_dir=str(snap_dir))

def test_capture_snapshot_valid(temp_media_recorder):
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    cv2.putText(frame, "TEST FRAME", (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
    
    res = temp_media_recorder.capture_snapshot(frame, incident_id=101, prefix='incident')
    assert res.valid is True
    assert os.path.exists(res.file_path)
    assert res.file_size > 0
    assert res.file_name.startswith('incident_101_')
    
    # Verify readable back
    img = cv2.imread(res.file_path)
    assert img is not None
    assert img.shape == (480, 640, 3)

def test_capture_snapshot_empty_frame(temp_media_recorder):
    empty_frame = np.array([])
    res = temp_media_recorder.capture_snapshot(empty_frame, incident_id=102)
    assert res.valid is False
    assert res.error is not None

def test_video_recording_and_finalization(temp_media_recorder):
    session_key = "zone:0:Person-1:Zone-1:BREACH"
    
    # Create 10 pre-event frames
    pre_frames = []
    for i in range(10):
        f = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(f, f"PRE {i}", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
        pre_frames.append(f)
        
    temp_media_recorder.start_video_session(session_key, incident_id=201, pre_event_frames=pre_frames)
    
    # Append 15 live frames
    for i in range(15):
        f = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.putText(f, f"LIVE {i}", (20, 20), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
        temp_media_recorder.append_frame(session_key, f)
        
    res = temp_media_recorder.finalize_video(session_key, fps=10, prefix='incident')
    assert res.valid is True
    assert os.path.exists(res.file_path)
    assert res.file_size > 0
    assert res.file_name.startswith('incident_201_')
    
    # Verify container decodability
    cap = cv2.VideoCapture(res.file_path)
    assert cap.isOpened()
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    assert frame_count == 25
    cap.release()

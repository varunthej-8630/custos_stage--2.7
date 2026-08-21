# tests/test_vision_tracking.py — Multi-Object Tracking Tests
import time
import pytest
from engine.tracking_engine import MultiObjectTracker, TrackingEngine, TrackState

def test_track_creation_and_fields():
    tracker = MultiObjectTracker(match_iou=0.3, max_unseen_sec=2.0)
    dets = [{
        'bbox': [100, 100, 200, 300],
        'confidence': 0.88,
        'class_id': 0,
        'class_name': 'person'
    }]
    tracks = tracker.update(dets)
    assert len(tracks) == 1
    t = tracks[0]
    assert t['track_id'] == 1
    assert t['cx'] == 150.0
    assert t['cy'] == 200.0
    assert t['foot_x'] == 150.0
    assert t['foot_y'] == 300.0
    assert t['age_frames'] == 1

def test_track_continuity_and_id_stability():
    tracker = MultiObjectTracker(match_iou=0.3, max_unseen_sec=2.0)
    
    # Frame 1
    tracker.update([{'bbox': [100, 100, 200, 300], 'confidence': 0.9, 'class_id': 0, 'class_name': 'person'}])
    
    # Frame 2: Slight movement
    tracks2 = tracker.update([{'bbox': [105, 102, 205, 302], 'confidence': 0.9, 'class_id': 0, 'class_name': 'person'}])
    assert len(tracks2) == 1
    assert tracks2[0]['track_id'] == 1  # ID maintained
    assert tracks2[0]['age_frames'] == 2
    
    # Frame 3: Another step
    tracks3 = tracker.update([{'bbox': [110, 104, 210, 304], 'confidence': 0.9, 'class_id': 0, 'class_name': 'person'}])
    assert len(tracks3) == 1
    assert tracks3[0]['track_id'] == 1
    assert tracks3[0]['age_frames'] == 3

def test_multi_person_tracking():
    tracker = MultiObjectTracker(match_iou=0.3, max_unseen_sec=2.0)
    
    # Two people
    dets = [
        {'bbox': [50, 50, 100, 200], 'confidence': 0.85, 'class_id': 0, 'class_name': 'person'},
        {'bbox': [300, 300, 380, 450], 'confidence': 0.92, 'class_id': 0, 'class_name': 'person'}
    ]
    tracks = tracker.update(dets)
    assert len(tracks) == 2
    ids = {t['track_id'] for t in tracks}
    assert ids == {1, 2}

def test_track_expiration():
    tracker = MultiObjectTracker(match_iou=0.3, max_unseen_sec=0.1) # 100ms expiration
    tracker.update([{'bbox': [100, 100, 200, 300], 'confidence': 0.9, 'class_id': 0, 'class_name': 'person'}])
    assert len(tracker.tracks) == 1
    
    # Sleep to expire track
    time.sleep(0.15)
    tracks_after = tracker.update([])
    assert len(tracks_after) == 0
    assert len(tracker.tracks) == 0

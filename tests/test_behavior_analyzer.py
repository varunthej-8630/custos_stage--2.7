# tests/test_behavior_analyzer.py — Behavior Analyzer & Lifecycle State Tests
import time
import pytest
from engine.behavior_analyzer import (
    BehaviorAnalyzer, BehaviorStatus, BehaviorResult,
    PostureAnalyzer, MotionAnalyzer, DwellAnalyzer, ZoneTransitionAnalyzer
)
from config import settings as config

def test_behavior_analyzer_status_rules():
    ba = BehaviorAnalyzer()
    statuses = {a.name: a.status for a in ba.analyzers}
    
    # Verify unvalidated heuristics are strictly DISABLED
    assert statuses['crouching'] == BehaviorStatus.DISABLED
    assert statuses['motion_patterns'] == BehaviorStatus.DISABLED
    
    # Verify loitering is EXPERIMENTAL
    assert statuses['loitering'] == BehaviorStatus.EXPERIMENTAL
    
    # Verify zone transitions are VALIDATED
    assert statuses['zone_entry'] == BehaviorStatus.VALIDATED

def test_disabled_behaviors_generate_no_results():
    ba = BehaviorAnalyzer()
    # Mock track with crouch/pacing features
    track = {
        'track_id': 1,
        'bbox': [100, 100, 200, 200],
        'speed': 10.0,
        'dwell_time': 0.0,
        'current_zone': None
    }
    
    output = ba.process([track], context={})
    # Must contain no crouching or motion pattern results
    b_names = [r.behavior_name for r in output['all']]
    assert 'crouching' not in b_names
    assert 'motion_patterns' not in b_names

def test_validated_zone_entry_passed_to_production():
    ba = BehaviorAnalyzer()
    track = {
        'track_id': 5,
        'bbox': [100, 100, 200, 200],
        'speed': 0.0,
        'dwell_time': 2.5,
        'current_zone': 0
    }
    context = {'zones': [[50, 50, 250, 250]], 'zone_types': ['HIGH']}
    
    output = ba.process([track], context=context)
    assert len(output['validated']) == 1
    assert output['validated'][0].behavior_name == "high_zone_entry"
    assert output['validated'][0].status == BehaviorStatus.VALIDATED

def test_dwell_analyzer_experimental_separation():
    ba = BehaviorAnalyzer()
    now = time.time()
    # Mock track staying within 20px diameter for 12 seconds
    traj = [(100 + i * 0.5, 100 + i * 0.5, now - 12 + i) for i in range(12)]
    track = {
        'track_id': 9,
        'bbox': [100, 100, 150, 200],
        'speed': 0.5,
        'dwell_time': 12.0,
        'trajectory': traj,
        'current_zone': None
    }
    
    output = ba.process([track], context={})
    # Experimental list may contain loitering
    exp_names = [r.behavior_name for r in output['experimental']]
    assert 'loitering' in exp_names
    
    # But VALIDATED list must NOT contain loitering
    val_names = [r.behavior_name for r in output['validated']]
    assert 'loitering' not in val_names

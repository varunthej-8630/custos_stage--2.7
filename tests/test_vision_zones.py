# tests/test_vision_zones.py — Zone Membership & Transition Tests
import time
import pytest
from engine.zone_monitor import ZoneMonitor, is_box_in_zone
from config import settings as config

def test_box_in_zone_foot_and_center():
    zone = [100, 100, 300, 300]
    
    # 1. Footpoint in zone
    assert is_box_in_zone([150, 50, 250, 200], zone) is True
    # 2. Centroid in zone
    assert is_box_in_zone([150, 150, 250, 250], zone) is True
    # 3. Completely outside
    assert is_box_in_zone([10, 10, 50, 50], zone) is False

def test_zone_monitor_track_evaluation():
    zm = ZoneMonitor()
    zones = [[100, 100, 300, 300], [400, 100, 600, 300]]
    zone_types = ['HIGH', 'WATCH']
    
    tracks = [
        {'track_id': 1, 'bbox': [150, 150, 250, 280]}, # inside Zone 0 (HIGH)
        {'track_id': 2, 'bbox': [10, 10, 50, 80]}      # outside all zones
    ]
    
    evaluated = zm.evaluate_tracks(tracks, zones, zone_types)
    assert evaluated[0]['current_zone'] == 0
    assert evaluated[0]['dwell_time'] >= 0.0
    assert evaluated[1]['current_zone'] is None

def test_zone_transition_and_dwell():
    zm = ZoneMonitor()
    zones = [[100, 100, 300, 300]]
    zone_types = ['WATCH']
    
    # Step 1: Outside
    t1 = [{'track_id': 10, 'bbox': [10, 10, 50, 80]}]
    res1 = zm.evaluate_tracks(t1, zones, zone_types)
    assert res1[0]['current_zone'] is None
    
    # Step 2: Enters Zone
    t2 = [{'track_id': 10, 'bbox': [150, 150, 250, 280]}]
    res2 = zm.evaluate_tracks(t2, zones, zone_types)
    assert res2[0]['current_zone'] == 0
    
    time.sleep(0.05)
    
    # Step 3: Dwell increases
    res3 = zm.evaluate_tracks(t2, zones, zone_types)
    assert res3[0]['current_zone'] == 0
    assert res3[0]['dwell_time'] > 0.0
    
    # Step 4: Exits Zone
    res4 = zm.evaluate_tracks(t1, zones, zone_types)
    assert res4[0]['current_zone'] is None
    assert res4[0]['dwell_time'] == 0.0

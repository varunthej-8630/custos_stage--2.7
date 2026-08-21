# tests/test_risk_explainability.py — Risk Engine Determinism & Explainability Tests
import time
import pytest
from engine.risk_engine import RiskEngine
from config import settings as config

def test_risk_tamper_immediate_maximum():
    re = RiskEngine()
    score, reasons, alert = re.evaluate(
        tracks=[],
        validated_behaviors=[],
        zones=[[0, 0, 100, 100]],
        zone_types=['HIGH'],
        tamper=True
    )
    assert score == 100.0
    assert alert is True
    assert "CAMERA TAMPER DETECTED" in reasons

def test_risk_high_zone_breach():
    re = RiskEngine()
    tracks = [{'track_id': 3, 'current_zone': 0, 'dwell_time': 0.5}]
    zones = [[100, 100, 300, 300]]
    zone_types = ['HIGH']
    
    score, reasons, alert = re.evaluate(
        tracks=tracks,
        validated_behaviors=[],
        zones=zones,
        zone_types=zone_types,
        tamper=False
    )
    assert score >= config.RISK_THRESHOLD
    assert any("HIGH zone breach (Track #3)" in r for r in reasons)

def test_risk_guard_mode_multiplier():
    re = RiskEngine()
    re.set_mode('GUARD')
    tracks = [{'track_id': 7, 'current_zone': 0, 'dwell_time': 0.5}]
    zones = [[100, 100, 300, 300]]
    zone_types = ['HIGH']
    
    score, reasons, alert = re.evaluate(
        tracks=tracks,
        validated_behaviors=[],
        zones=zones,
        zone_types=zone_types,
        tamper=False
    )
    assert score >= 60.0  # Guard mode breach elevates immediately
    assert any("[GUARD MODE]" in r for r in reasons)

def test_risk_decay_when_zone_cleared():
    re = RiskEngine()
    # Initially high score
    re.score = 80.0
    re.last_update = time.time() - 1.0 # 1 second elapsed
    
    # Scene empty
    score, reasons, alert = re.evaluate(
        tracks=[],
        validated_behaviors=[],
        zones=[[100, 100, 300, 300]],
        zone_types=['HIGH'],
        tamper=False
    )
    assert score < 80.0 # Decayed

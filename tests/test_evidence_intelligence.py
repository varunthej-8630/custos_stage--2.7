import pytest
import time
from engine.evidence_engine import (
    DynamicReliabilityScorer,
    IncidentReplayBuilder,
    EvidenceDeduplicator,
    EvidenceCache,
    EvidenceRetentionManager,
    EvidenceEngine
)

def test_dynamic_reliability_scorer():
    scorer = DynamicReliabilityScorer()
    
    # Base detection
    score_base = scorer.calculate(behaviors=[], dwell_seconds=0, zone_type='WATCH', track_history_len=1)
    assert 30.0 <= score_base <= 50.0

    # Multi-behavior high security breach
    score_multi = scorer.calculate(
        behaviors=['CROUCHING', 'LOITERING'],
        dwell_seconds=60.0,
        zone_type='HIGH',
        track_history_len=15
    )
    assert score_multi >= 85.0

    # False positive penalty
    score_fp = scorer.calculate(behaviors=['CROUCHING'], dwell_seconds=10.0, zone_type='HIGH', track_history_len=5, false_positive=True)
    assert score_fp == 0.0

def test_incident_replay_builder():
    timeline = IncidentReplayBuilder.build_timeline(
        first_seen_str="10:00:00 AM",
        events_list=["Person crouching", "HIGH ZONE BREACH"],
        zone_name="Restricted Vault",
        track_id=17
    )
    assert len(timeline) == 4
    assert timeline[0]['step'] == 1
    assert "Person-17" in timeline[0]['action']
    assert timeline[1]['action'] == "Person crouching"

def test_evidence_deduplicator():
    dedup = EvidenceDeduplicator(cooldown_seconds=2.0)
    subject_id = "Person-17"
    
    # Initially not merged
    assert dedup.should_merge(subject_id) is False

    # Register
    pkg = {'score': 50.0, 'events': ['Loitering'], 'timeline': []}
    dedup.register_new(subject_id, pkg)
    
    # Should merge within cooldown
    assert dedup.should_merge(subject_id) is True

    # Update
    updated = dedup.update_incident(subject_id, ['Zone Hopping'], 75.0, 30.0, {'step': 2, 'action': 'Zone Hopping'})
    assert updated['score'] == 75.0
    assert 'Zone Hopping' in updated['events']

    # Wait for cooldown expiration
    time.sleep(2.1)
    dedup.purge_stale()
    assert dedup.should_merge(subject_id) is False

def test_evidence_cache():
    cache = EvidenceCache(maxsize=3)
    cache.add({'id': 1})
    cache.add({'id': 2})
    cache.add({'id': 3})
    cache.add({'id': 4}) # Overflow

    recent = cache.get_recent()
    assert len(recent) == 3
    assert recent[0]['id'] == 4
    assert recent[2]['id'] == 2

def test_evidence_engine_process_event():
    engine = EvidenceEngine()
    pkg = engine.process_event(
        camera_id=0,
        score=85.0,
        event_log=['HIGH ZONE BREACH', 'CROUCHING'],
        zone_name='Vault A',
        subject_memory={'person_id': 'Person-99', 'dwell_seconds': 45.0, 'behaviors': {'CROUCHING': 1}, 'spatial_trajectory': [1]*12},
        snapshot_path='alert_1.jpg',
        clip_path='pretamper_1.mp4'
    )
    assert pkg['subject_id'] == 'Person-99'
    assert pkg['reliability_score'] >= 80.0
    assert pkg['camera_id'] == 0
    assert len(pkg['timeline']) >= 2

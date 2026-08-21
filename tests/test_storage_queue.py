import time
import pytest
from engine.storage_queue import storage_queue

def test_storage_queue_initialization():
    assert storage_queue is not None
    assert storage_queue.queue.maxsize == 100

def test_storage_queue_enqueuing():
    storage_queue.start()
    res = storage_queue.put_task('save_incident', {
        'camera_id': 0,
        'zone_name': 'Test Zone',
        'score': 85.0,
        'reliability_score': 90.0,
        'subject_id': 'Person-Test',
        'events': ['LOITERING']
    })
    assert res is True
    storage_queue.stop()

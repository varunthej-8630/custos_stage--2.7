import pytest
from engine.zone_store import ZoneStore

def test_zone_store_operations():
    zs = ZoneStore()
    zs.clear()

    # Default empty
    zones, types, monitoring = zs.get_zones(0)
    assert zones == []
    assert types == []
    assert monitoring is False

    # Set zones for camera 0
    test_zones = [[10, 10, 100, 100], [200, 200, 300, 300]]
    test_types = ['HIGH', 'WATCH']
    zs.set_zones(0, test_zones, test_types, monitoring=True)

    z_out, t_out, m_out = zs.get_zones(0)
    assert len(z_out) == 2
    assert z_out == test_zones
    assert t_out == test_types
    assert m_out is True
    assert zs.is_monitoring(0) is True

    # Atomic update without pipeline restart
    updated_zones = [[50, 50, 150, 150]]
    updated_types = ['HIGH']
    zs.set_zones(0, updated_zones, updated_types, monitoring=True)

    z_out2, t_out2, m_out2 = zs.get_zones(0)
    assert len(z_out2) == 1
    assert z_out2 == updated_zones
    assert t_out2 == ['HIGH']

    zs.clear(0)
    assert zs.get_zones(0) == ([], [], False)

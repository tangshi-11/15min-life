"""坐标转换与距离计算单元测试。"""

from app.core.coords import bd09_to_wgs84, haversine_m, offset_lnglat, wgs84_to_bd09


def test_bd09_wgs84_roundtrip():
    lng, lat = 102.7146, 25.0406
    b = wgs84_to_bd09(lng, lat)
    back = bd09_to_wgs84(*b)
    assert abs(back[0] - lng) < 1e-4
    assert abs(back[1] - lat) < 1e-4


def test_bd09_differs_from_wgs84():
    lng, lat = 102.7146, 25.0406
    b = wgs84_to_bd09(lng, lat)
    assert abs(b[0] - lng) > 1e-4 or abs(b[1] - lat) > 1e-4


def test_haversine_north_1km():
    d = haversine_m(102.7146, 25.0406, 102.7146, 25.0506)
    assert 1000 < d < 1200


def test_offset_lnglat_roundtrip():
    lng, lat = offset_lnglat(102.7146, 25.0406, 500.0, 300.0)
    assert abs(lng - 102.7146) > 0.004
    assert abs(lat - 25.0406) > 0.002


def test_haversine_direction_consistent():
    lng, lat = offset_lnglat(102.7146, 25.0406, 1000.0, 0.0)
    d = haversine_m(102.7146, 25.0406, lng, lat)
    assert 900 < d < 1100

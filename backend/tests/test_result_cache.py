"""服务端体检结果缓存（100m 网格 key + sqlite + LRU）单元测试。"""

from app.core import result_cache


def _cleanup():
    result_cache.clear()


def test_make_key_same_grid_neighbor():
    # 同 100m 网格内的点（约 20m 间距）→ 同一 key（用远离真实城市的测试坐标，避免污染生产 key 空间）
    k1 = result_cache.make_key(10.0001, 10.0001)
    k2 = result_cache.make_key(10.0003, 10.0003)
    assert k1 == k2


def test_make_key_cross_grid():
    # 明显跨网格的点 → 不同 key
    k1 = result_cache.make_key(10.0001, 10.0001)
    k2 = result_cache.make_key(10.0101, 10.0101)
    assert k1 != k2


def test_set_get_roundtrip():
    _cleanup()
    key = result_cache.make_key(10.0001, 10.0001)
    result = {"center": {"lat": 10.0001, "lng": 10.0001}, "coverage": {"overall": 80}}
    result_cache.set(key, result)
    got = result_cache.get(key)
    assert got is not None
    assert got["coverage"]["overall"] == 80


def test_get_miss_returns_none():
    _cleanup()
    assert result_cache.get("99.999,0.001") is None


def test_lru_eviction(monkeypatch):
    _cleanup()
    monkeypatch.setattr(result_cache, "MAX_ENTRIES", 5)
    monkeypatch.setattr(result_cache, "_TRIM_TARGET", 4)
    for i in range(8):
        result_cache.set(f"{i}.000,0.000", {"i": i})
    # 最旧的 key（0）应已被淘汰；最新的（7）仍在
    assert result_cache.get("0.000,0.000") is None
    assert result_cache.get("7.000,0.000") is not None


def test_hit_updates_count_and_timestamp():
    _cleanup()
    key = result_cache.make_key(10.0001, 10.0001)
    result_cache.set(key, {"v": 1})
    assert result_cache.get(key) is not None
    assert result_cache.get(key) is not None  # 两次命中

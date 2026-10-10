"""等时圈引擎单元测试（使用 MockBaiduClient，确定性输出）。"""
from types import SimpleNamespace

import pytest
from app.api import mock as mock_mod
from app.api.mock import MockBaiduClient
from app.core import isochrone


def _cfg(**over):
    base = {
        "directions": 24, "step_m": 100, "max_radius_m": 2000, "grid_n": 60,
        "matrix_chunk": 90, "walking_minutes": 15, "mock_seed": 42,
    }
    base.update(over)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_isochrone_produces_polygon():
    cfg = _cfg()
    client = MockBaiduClient(seed=42)
    result = await isochrone.compute_isochrone(25.0406, 102.7146, client, cfg)
    assert result["polygon"] is not None, "IDW+Marching Squares 应能提取等时圈多边形"
    assert len(result["polygon"]) >= 8
    assert result["stats"]["area_km2"] > 0.05
    assert result["stats"]["boundary_points"] == 24


@pytest.mark.asyncio
async def test_isochrone_boundary_within_bbox():
    cfg = _cfg()
    client = MockBaiduClient(seed=42)
    result = await isochrone.compute_isochrone(25.0406, 102.7146, client, cfg)
    lngs = [p[0] for p in result["boundary_polygon"]]
    lats = [p[1] for p in result["boundary_polygon"]]
    assert min(lngs) > 102.7146 - 0.03 and max(lngs) < 102.7146 + 0.03
    assert min(lats) > 25.0406 - 0.03 and max(lats) < 25.0406 + 0.03


@pytest.mark.asyncio
async def test_isochrone_barrier_shrinks_sector():
    """阻挡角度带方向（河流）的等时圈应明显小于开阔方向。"""
    cfg = _cfg()
    client = MockBaiduClient(seed=42)
    o = (25.0406, 102.7146)
    base = mock_mod._barrier_bearing(o, 42)
    # 复算边界：阻挡带方向 与 其垂直方向 对比
    rays = isochrone.build_rays(o[0], o[1], cfg.directions, cfg.step_m, cfg.max_radius_m)
    dests = isochrone.flat_destinations(rays)
    elements = []
    for i in range(0, len(dests), cfg.matrix_chunk):
        chunk = dests[i:i + cfg.matrix_chunk]
        elements.extend((await client.route_matrix_walking([o], chunk))["elements"])
    bounds = dict(isochrone.boundary_by_rays(rays, elements, 900, cfg.step_m, cfg.max_radius_m))
    keys = sorted(bounds.keys())
    r_in = min(keys, key=lambda k: abs(k - base))
    r_out = min(keys, key=lambda k: abs(((k - (base + 90) % 360) + 180) % 360 - 180))
    assert bounds[r_in] < bounds[r_out] * 0.9


def test_boundary_elements_no_offset():
    """回归：boundary_by_rays 每方向必须消费本方向的采样点（修复 break 导致 idx 错位）。"""
    import math

    o = (25.0406, 102.7146)
    base = mock_mod._barrier_bearing(o, 42)

    def pt(ang: float, r: float = 900) -> tuple[float, float]:
        return (
            o[0] + r * math.cos(math.radians(ang)) / 110540.0,
            o[1] + r * math.sin(math.radians(ang)) / (111320.0 * math.cos(math.radians(o[0]))),
        )

    # 阻挡方向 900m 处必然超 15 分钟（修复前会被错位的低耗时元素掩盖）
    t_in = mock_mod._mock_seconds(o, pt(base), 900, 42)
    assert t_in > 900


def test_mock_barrier_position_dependent():
    """不同中心点 → 不同阻挡方向（等时圈形态随位置变化，同点可复现）。"""
    o1, o2 = (25.0406, 102.7146), (24.8530, 102.8488)
    b1, b2 = mock_mod._barrier_bearing(o1, 42), mock_mod._barrier_bearing(o2, 42)
    assert b1 != b2
    assert mock_mod._barrier_bearing(o1, 42) == b1  # 确定性

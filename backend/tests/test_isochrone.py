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
    """阻挡角度带方向（河流）的耗时显著大于开阔方向 → 等时圈必然收缩。"""
    o = (25.0406, 102.7146)
    base = mock_mod._barrier_bearing(o, 42)
    import math

    def pt(ang: float, r: float = 900) -> tuple[float, float]:
        return (
            o[0] + r * math.cos(math.radians(ang)) / 110540.0,
            o[1] + r * math.sin(math.radians(ang)) / (111320.0 * math.cos(math.radians(o[0]))),
        )

    t_in = mock_mod._mock_seconds(o, pt(base), 900, 42)
    t_out = mock_mod._mock_seconds(o, pt((base + 90) % 360), 900, 42)
    assert t_in > t_out + 200, f"阻挡方向 {t_in}s 应明显慢于开阔方向 {t_out}s"
    assert t_in > 900, "阻挡方向应超出 15 分钟阈值（保证边界收缩）"


def test_mock_barrier_position_dependent():
    """不同中心点 → 不同阻挡方向（等时圈形态随位置变化，同点可复现）。"""
    o1, o2 = (25.0406, 102.7146), (24.8530, 102.8488)
    b1, b2 = mock_mod._barrier_bearing(o1, 42), mock_mod._barrier_bearing(o2, 42)
    assert b1 != b2
    assert mock_mod._barrier_bearing(o1, 42) == b1  # 确定性

"""等时圈引擎单元测试（使用 MockBaiduClient，确定性输出）。"""
from types import SimpleNamespace

import pytest

from app.api.mock import MockBaiduClient
from app.core import isochrone


def _cfg(**over):
    base = dict(
        directions=24, step_m=100, max_radius_m=2000, grid_n=60,
        matrix_chunk=90, walking_minutes=15, mock_seed=42,
    )
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
    result = await isochrone.compute_isochrone(25.0406, 102.7146, client, cfg)
    boundary = dict(result["boundary_polygon"])  # 占位，实际用角度映射
    # 直接复算边界：45°(阻挡带40-75°内) 与 0° 对比
    rays = isochrone.build_rays(25.0406, 102.7146, cfg.directions, cfg.step_m, cfg.max_radius_m)
    dests = isochrone.flat_destinations(rays)
    elements = []
    for i in range(0, len(dests), cfg.matrix_chunk):
        chunk = dests[i:i + cfg.matrix_chunk]
        elements.extend((await client.route_matrix_walking([(25.0406, 102.7146)], chunk))["elements"])
    bounds = dict(isochrone.boundary_by_rays(rays, elements, 900, cfg.step_m, cfg.max_radius_m))
    assert bounds[45.0] < bounds[0.0] * 0.9

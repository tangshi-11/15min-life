"""WaterGuard 水域仲裁单元测试。"""
import json
import tempfile
from pathlib import Path

import pytest
from app.core.water_guard import WaterGuard, point_in_polygon, wgs84_to_bd09


def test_point_in_polygon():
    poly = [(0.0, 0.0), (10.0, 0.0), (10.0, 10.0), (0.0, 10.0)]
    assert point_in_polygon(5.0, 5.0, poly) is True
    assert point_in_polygon(15.0, 5.0, poly) is False
    assert point_in_polygon(-1.0, -1.0, poly) is False


def test_wgs84_to_bd09():
    lng, lat = wgs84_to_bd09(102.69, 24.74)
    # 百度坐标相对 WGS84 有 ~0.002-0.01 量级偏移
    assert abs(lng - 102.69) < 0.02
    assert abs(lat - 24.74) < 0.02


@pytest.mark.asyncio
async def test_is_water_local_data():
    """本地水体数据：湖面点 True、绿道点 False。"""
    # 构造"滇池"近似多边形（BD-09 坐标，覆盖北侧湖面，南边界在中心点以南）
    lake = [[102.66, 24.744], [102.72, 24.744], [102.72, 24.80], [102.66, 24.80]]
    bboxes = [[102.66, 24.744, 102.72, 24.80]]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "water_polygons.json"
        f.write_text(json.dumps({"polys": [lake], "bboxes": bboxes}), encoding="utf-8")
        wg = WaterGuard(session=None, cache_path=None, enabled=True, local_geojson=str(f))
        center = (24.741355, 102.694037)
        # 北侧 500m（距多边形南边界 ~220m < 300m 岸边缓冲）→ 陆地（岸边步道保留）
        assert await wg.is_water(center, (24.7460, 102.6940)) is False
        # 北侧 1500m / 2500m（距边界 > 300m 开阔水面）→ 水域
        assert await wg.is_water(center, (24.7550, 102.6940)) is True
        assert await wg.is_water(center, (24.7650, 102.6940)) is True
        # 西侧绿道 500m（多边形南边界之外）→ 陆地
        assert await wg.is_water(center, (24.7413, 102.6887)) is False
        # 东侧陆地 500m → 陆地
        assert await wg.is_water(center, (24.7413, 102.7007)) is False


@pytest.mark.asyncio
async def test_is_water_no_data_conservative():
    """无本地数据且无网络 → 保守返回 True（防盖水）。"""
    wg = WaterGuard(session=None, cache_path=None, enabled=True, local_geojson=None)
    assert await wg.is_water((24.741, 102.694), (24.746, 102.694)) is True


@pytest.mark.asyncio
async def test_is_water_disabled():
    """未启用 → 一律 True（按水域保守处理）。"""
    wg = WaterGuard(enabled=False)
    assert await wg.is_water((24.741, 102.694), (24.746, 102.694)) is True


@pytest.mark.asyncio
async def test_is_water_center_point_guard():
    """中心点判水：岸边中心点（距岸<300m）允许；湖中央中心点拒绝。"""
    lake = [[102.66, 24.744], [102.72, 24.744], [102.72, 24.80], [102.66, 24.80]]
    bboxes = [[102.66, 24.744, 102.72, 24.80]]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "water_polygons.json"
        f.write_text(json.dumps({"polys": [lake], "bboxes": bboxes}), encoding="utf-8")
        wg = WaterGuard(session=None, cache_path=None, enabled=True, local_geojson=str(f))
        # 岸边中心点（距多边形南边界 ~294m < 300m 缓冲）→ 陆地，允许体检
        assert await wg.is_water((24.741355, 102.694037), (24.741355, 102.694037)) is False
        # 湖中央中心点（距边界 > 300m）→ 水域，应拒绝
        assert await wg.is_water((24.7650, 102.6900), (24.7650, 102.6900)) is True


@pytest.mark.asyncio
async def test_is_water_strict_margin_overrides_buffer():
    """margin_m=0（等时圈水域仲裁严格模式）：岸边水面也判水，蓝色=水不可过。
    默认 margin=300 时岸边 300m 内水面放行（保护绿道）→ 残留盖水；
    显式传 margin_m=0 后同一岸边点判为水域 → 内缩排除。"""
    lake = [[102.66, 24.744], [102.72, 24.744], [102.72, 24.80], [102.66, 24.80]]
    bboxes = [[102.66, 24.744, 102.72, 24.80]]
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "water_polygons.json"
        f.write_text(json.dumps({"polys": [lake], "bboxes": bboxes}), encoding="utf-8")
        wg = WaterGuard(session=None, cache_path=None, enabled=True, local_geojson=str(f))
        center = (24.741355, 102.694037)
        # 岸边水面点：距多边形南边界 ~294m < 300m
        shore = (24.7460, 102.6940)
        assert await wg.is_water(center, shore) is False          # 默认缓冲放行（绿道保护）
        assert await wg.is_water(center, shore, margin_m=0.0) is True  # 严格模式判水
        # 默认 margin 不受影响（显式传参不改实例状态）
        assert await wg.is_water(center, shore) is False

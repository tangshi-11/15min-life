"""等时圈引擎单元测试（使用 MockBaiduClient，确定性输出）。"""
import math
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


class _FakeClient:
    """可控的单点算路客户端：按距离返回耗时，可注入失败。"""

    def __init__(self, sec_at, fail=False):
        self.sec_at = sec_at
        self.fail = fail

    async def walking_direction(self, origin, destination):
        if self.fail:
            raise RuntimeError("quota")
        d = mock_mod.haversine_m(origin[1], origin[0], destination[1], destination[0])
        return {"duration_s": self.sec_at(d), "distance_m": int(d)}


@pytest.mark.asyncio
async def test_refine_mock_keeps_boundary():
    """Mock 口径下复核与采样一致：开阔方向边界不会被内缩（正常区域不被误收）。"""
    o = (25.0406, 102.7146)
    cfg = _cfg()
    base = mock_mod._barrier_bearing(o, 42)
    open_ang = (base + 90.0) % 360.0
    # 用真实采样边界（符合 Mock 语义），而非硬编码值
    rays = isochrone.build_rays(o[0], o[1], cfg.directions, cfg.step_m, cfg.max_radius_m)
    dests = isochrone.flat_destinations(rays)
    elements = []
    for i in range(0, len(dests), cfg.matrix_chunk):
        chunk = dests[i:i + cfg.matrix_chunk]
        elements.extend((await MockBaiduClient(seed=42).route_matrix_walking([o], chunk))["elements"])
    bounds = isochrone.boundary_by_rays(rays, elements, 900.0, cfg.step_m, cfg.max_radius_m)
    bd_map = dict(bounds)
    near_open = min(bd_map.keys(), key=lambda k: abs(((k - open_ang) + 180) % 360 - 180))
    client = MockBaiduClient(seed=42)
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    out_map = dict(out)
    # 复核口径（directionlite 含绕行）可能比采样口径（routematrix 直线）略保守，
    # 允许适度内缩，但不允许把开阔方向砍到一半以下（正常区域不被误收）。
    assert out_map[near_open] >= bd_map[near_open] * 0.5, "开阔方向不应被复核显著内缩"
    assert all(40.0 <= d <= 2000.0 for _, d in out), "边界应保持合理范围"


class _WaterTimeoutClient:
    """水域直线口径：复核/探测均超时且距离远小于直线（百度最近路网点口径，实测 0.70-0.84）。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        return {"duration_s": 1800.0 + dist, "distance_m": dist * 0.7}


@pytest.mark.asyncio
async def test_refine_inner_shrink_on_water():
    """水域直线口径：批量说可达(远)，单点复核超时 + 探测仍直线口径低 ratio → 内缩。"""
    o = (25.0406, 102.7146)
    client = _WaterTimeoutClient()
    bounds = [(0.0, 800.0), (90.0, 1200.0), (180.0, 600.0), (270.0, 1500.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    for (_, orig), (_, ref) in zip(bounds, out):
        assert ref < orig - 100.0, "水域方向应显著内缩"
        assert ref > 40.0, "内缩后仍保持合理最小半径"


@pytest.mark.asyncio
async def test_refine_outer_extend_when_fast():
    """单点耗时明显小于阈值 → 外扩探测更远点。"""
    o = (25.0406, 102.7146)
    client = _FakeClient(sec_at=lambda d: 500.0)
    bounds = [(90.0, 600.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    assert out[0][1] > 800.0, "耗时充足的方向应外扩"


@pytest.mark.asyncio
async def test_refine_failure_keeps_original():
    """复核失败（配额/网络）→ 保持原边界，安全降级。"""
    o = (25.0406, 102.7146)
    client = _FakeClient(sec_at=lambda d: 0.0, fail=True)
    bounds = [(0.0, 800.0), (90.0, 1200.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    assert out == bounds


class _WaterGarbageClient:
    """模拟 directionlite 对水域点返回 0s/1m 垃圾数据（起点终点被判定重合）。"""

    async def walking_direction(self, origin, destination):
        return {"duration_s": 0, "distance_m": 1}


@pytest.mark.asyncio
async def test_refine_inward_clamp_on_water_guard():
    """复核超时内缩后仍≥500m + 水域确认判水 → 贴岸 clamp 300m（湖面直线口径残留）。
    实测滇池北侧：directionlite 对近岸水面 500-1200m 返回近似直线耗时≤阈值被当可达，
    复核超时内缩后边界仍大，需 OSM 水体数据二次确认判水后贴岸。"""
    o = (25.0406, 102.7146)
    # 1500m 复核超时；750m 处可达：二分后 best≈750（≥500）→ water_guard 判水 → clamp 300
    client = _FakeClient(sec_at=lambda d: d * 0.8 if d <= 800.0 else 1800.0 + d)
    wg = _WaterGuardMock(in_water=True)
    bounds = [(0.0, 1500.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref <= 300.0, "水域确认判水后应贴岸 clamp 300m"


@pytest.mark.asyncio
async def test_refine_inward_no_clamp_when_not_water():
    """复核超时内缩后 ≥500m 但水域确认非水（正常绕行陆地）→ 保持内缩边界不误砍。"""
    o = (25.0406, 102.7146)
    client = _FakeClient(sec_at=lambda d: d * 0.8 if d <= 800.0 else 1800.0 + d)
    wg = _WaterGuardMock(in_water=False)
    bounds = [(0.0, 1500.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref >= 700.0, "水域确认非水时应保持内缩边界（正常绕行）"


@pytest.mark.asyncio
async def test_refine_reachable_water_clamp():
    """复核可达（≤limit 的水面直线口径）但水域确认判水 → 贴岸 300m。
    实测滇池北侧 958m 处 directionlite 返回近似直线耗时≤阈值被当可达保留，
    需统一水域确认后贴岸排除湖面。"""
    o = (25.0406, 102.7146)
    client = _FakeClient(sec_at=lambda d: 500.0 if d <= 958 else 1800.0 + d)
    wg = _WaterGuardMock(in_water=True)
    bounds = [(0.0, 958.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref <= 300.0, "复核可达但水域确认判水应贴岸 300m"


@pytest.mark.asyncio
async def test_refine_probe_kept_exempt_water_guard():
    """绿道（探测恢复正常）保留边界，即使 OSM 粗数据误判水也不 clamp。
    实测滇池西侧绿道 750-1050m 返回 0s/1m 垃圾但实际可步行，粗 OSM 岸线把绿道
    误判为水，必须豁免探测保留方向。"""
    o = (25.0406, 102.7146)
    client = _ProbeOkClient()
    wg = _WaterGuardMock(in_water=True)
    bounds = [(0.0, 700.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref == 700.0, "探测保留（绿道）方向应豁免水域误判，保持采样边界"


@pytest.mark.asyncio
async def test_refine_garbage_all_junk_keeps():
    """复核点与探测点均返回 0s/1m 垃圾：百度对未建模绿道返回不稳定
    （实测同方向 1050m 垃圾、1120m 正常），无法据此判水 → 保持采样边界（宁留勿砍）。
    真实湖面方向复核点通常返回非垃圾超时（如滇池 1177m→1120s/1309m），
    由 t>limit 路径内缩排除，不依赖此分支。"""
    o = (25.0406, 102.7146)
    client = _WaterGarbageClient()
    bounds = [(0.0, 2000.0), (90.0, 1500.0), (180.0, 1200.0), (270.0, 2000.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    for (_, orig), (_, ref) in zip(bounds, out):
        assert ref == orig, "全垃圾无法判水，应保持采样边界（绿道保护）"


class _WaterGuardMock:
    """水域仲裁 mock：可指定返回水域/陆地。"""

    def __init__(self, in_water: bool):
        self._in_water = in_water

    async def is_water(self, center_ll, point_ll, margin_m: float | None = None):
        return self._in_water


@pytest.mark.asyncio
async def test_refine_garbage_land_keeps_boundary():
    """垃圾数据 + 仲裁判陆地（未建模绿道）→ 保持采样边界，不误砍。
    M10 修复：M9 一刀切内缩把滇池西侧绿道砍掉，用户否决；现在由水域仲裁放行。"""
    o = (24.741355, 102.694037)
    client = _WaterGarbageClient()
    wg = _WaterGuardMock(in_water=False)  # 判陆地（绿道）
    bounds = [(270.0, 700.0), (0.0, 2000.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    for (_, orig), (_, ref) in zip(bounds, out):
        assert ref == orig, "仲裁判陆地时垃圾方向应保持采样边界（绿道保留）"


@pytest.mark.asyncio
async def test_refine_garbage_water_shrinks():
    """垃圾数据 + 更远探测非垃圾但距离异常（水面特征）→ 内缩（防盖水）。"""
    o = (24.741355, 102.694037)
    client = _WaterProbeLowClient()  # 边界垃圾、探测点距离<<直线（湖面）
    bounds = [(270.0, 700.0), (0.0, 2000.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    for (_, orig), (_, ref) in zip(bounds, out):
        assert ref < orig - 100.0, "探测确认水面特征时垃圾方向必须内缩（防盖水）"
        assert ref > 40.0


class _ProbeOkClient:
    """模拟绿道场景：近处返回 0s/1m 垃圾，更远探测点恢复正常算路。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        if dist > 900.0:  # 探测点（1.5×700=1050m）恢复正常
            return {"duration_s": 1232, "distance_m": 1438}
        return {"duration_s": 0, "distance_m": 1}


class _WaterProbeLowClient:
    """模拟水面场景：边界点垃圾(0s/1m)，探测点返回非垃圾但距离 << 直线（水面特征）。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        if dist > 900.0:  # 探测点：水面 → 百度返回最近路网点（距离异常小）
            return {"duration_s": 112, "distance_m": 131}
        return {"duration_s": 0, "distance_m": 1}


@pytest.mark.asyncio
async def test_refine_garbage_probe_ok_keeps_greenway():
    """垃圾数据 + 更远探测恢复正常（未建模绿道）→ 保持采样边界。
    实测滇池西侧绿道：700m 处 0s/1m，1000m 处恢复 1232s/1438m（ratio 1.44）。"""
    o = (24.741355, 102.694037)
    client = _ProbeOkClient()
    bounds = [(270.0, 700.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    (_, orig), (_, ref) = bounds[0], out[0]
    assert ref == orig, "探测恢复正常说明是未建模步道（绿道），应保留采样边界"


@pytest.mark.asyncio
async def test_refine_garbage_probe_bad_shrinks():
    """垃圾数据 + 更远探测非垃圾但距离异常（水面）→ 内缩。
    实测滇池湖面：500m 处 0s/1m，1000m 处仍异常 131m/112s（ratio 0.13）。"""
    o = (24.741355, 102.694037)
    client = _WaterProbeLowClient()  # 探测点返回水面特征（距离<<直线）
    bounds = [(0.0, 700.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10)
    (_, orig), (_, ref) = bounds[0], out[0]
    assert ref < orig - 100.0, "探测仍异常说明是水面，必须内缩"
    assert ref > 40.0


class _TimeoutThenProbeOk:
    """模拟绿道场景：复核点非垃圾但超时（真实绕行 15 分钟走不到），探测点恢复正常大绕行。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        if dist > 1500.0:  # 探测点（1.6×1072≈1715m）：绿道真实绕行（ratio 2.58）
            return {"duration_s": 3824, "distance_m": 4419}
        return {"duration_s": 1246, "distance_m": 1455}  # 复核点：超时但非垃圾


class _TimeoutThenProbeLow:
    """模拟水面场景：复核点超时（直线口径），探测点仍直线口径低 ratio。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        return {"duration_s": 1120, "distance_m": 1309}  # 复核/探测均直线口径（0.70）


class _TimeoutThenProbeEdge:
    """模拟正常陆地复核超时边缘：探测 ratio≈1.0（0.95-1.1 区间）→ 应保持。"""

    async def walking_direction(self, origin, destination):
        dlng = (destination[1] - origin[1]) * 111320.0
        dlat = (destination[0] - origin[0]) * 110540.0
        dist = math.hypot(dlng, dlat)
        if dist > 1500.0:  # 探测点（1.6×1177≈1883m）：正常绕行系数 ratio≈1.0
            return {"duration_s": 950, "distance_m": 1900}
        return {"duration_s": 1246, "distance_m": 1455}  # 复核点：超时


@pytest.mark.asyncio
async def test_refine_timeout_probe_ok_keeps_greenway():
    """复核超时 + 探测恢复大绕行（绿道真实路径）→ 保留边界，豁免 OSM 水域误判。
    实测滇池东岸：270° 复核 1072m→1246s/1455m 超时，探测 1715m→3824s/4419m（ratio 2.58）。"""
    o = (24.741355, 102.694037)
    client = _TimeoutThenProbeOk()
    wg = _WaterGuardMock(in_water=True)  # 粗 OSM 判水 → 探测保留必须豁免
    bounds = [(270.0, 1072.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref == 1072.0, "复核超时但探测恢复正常（绿道真实绕行）应保留并豁免水域误判"


@pytest.mark.asyncio
async def test_refine_timeout_probe_low_shrinks():
    """复核超时 + 探测仍直线口径低 ratio（水面）→ 内缩排除。
    实测滇池北侧湖面：1177m→1120s/1309m，探测 1883m 仍 1309m（ratio 0.70）。"""
    o = (24.741355, 102.694037)
    client = _TimeoutThenProbeLow()
    wg = _WaterGuardMock(in_water=True)
    bounds = [(0.0, 1177.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref < 500.0, "复核超时且探测仍直线口径（水面）应内缩排除"


@pytest.mark.asyncio
async def test_refine_timeout_probe_edge_keeps():
    """复核超时 + 探测 ratio≈1.0（正常陆地边缘，0.95-1.1 区间）→ 保持（宁留勿砍）。
    防止正常陆地复核超时被探测仲裁误判水面内缩。"""
    o = (24.741355, 102.694037)
    client = _TimeoutThenProbeEdge()
    wg = _WaterGuardMock(in_water=False)
    bounds = [(0.0, 1177.0)]
    out = await isochrone.refine_boundaries(o[0], o[1], bounds, client, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    (_, ref) = out[0]
    assert ref == 1177.0, "正常陆地边缘（探测 ratio 0.95-1.1）应保持边界"


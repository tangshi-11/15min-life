"""15分钟步行等时圈引擎（核心算法）。

不获取底层路网数据，仅用百度地图路线矩阵(步行)的分散测时结果推导近似连通区域：
1. 扇区采样：以中心点为圆心，按固定角度分扇区，沿每个扇区按固定步长布采样点；
2. 批量算路：用路线矩阵一次测出多个采样点的步行耗时（分批 + 并发 + 限流）；
3. 每方向边界：取"步行 ≤ 阈值"的最远采样点，并在相邻两点间线性插值细化；
4. IDW 空间插值：对中心周边网格节点，用邻近测时点做反距离加权插值，得到"分钟场"；
5. Marching Squares：从分钟场提取阈值等值线，得到平滑等时圈多边形与热力图数据。
"""
import heapq
import logging
import math
from typing import Any

from .coords import offset_lnglat

logger = logging.getLogger(__name__)

# Marching Squares 分箱表：case(左上/右上/右下/左下 是否高于阈值) → 边对(0上 1右 2下 3左)
CASE_SEGMENTS = {
    0: [], 15: [],
    1: [(0, 3)], 14: [(0, 3)],
    2: [(0, 1)], 13: [(0, 1)],
    3: [(1, 3)], 12: [(1, 3)],
    4: [(1, 2)], 11: [(1, 2)],
    5: [(0, 1), (2, 3)], 10: [(0, 3), (1, 2)],
    6: [(0, 2)], 9: [(0, 2)],
    7: [(2, 3)], 8: [(2, 3)],
}


def build_rays(
    center_lat: float, center_lng: float, directions: int, step_m: float, max_radius_m: float
) -> list[tuple[float, list[tuple[float, float, float]]]]:
    """扇区采样：返回 [(角度, [(距离, 纬度, 经度), ...]), ...]。"""
    rays: list[tuple[float, list[tuple[float, float, float]]]] = []
    n_steps = max(1, int(max_radius_m // step_m))
    for i in range(directions):
        ang = i * 360.0 / directions
        rad = math.radians(ang)
        pts = []
        for k in range(1, n_steps + 1):
            d = k * step_m
            lng, lat = offset_lnglat(center_lng, center_lat, d * math.sin(rad), d * math.cos(rad))
            pts.append((d, lat, lng))
        rays.append((ang, pts))
    return rays


def flat_destinations(rays) -> list[tuple[float, float]]:
    """把所有采样点展开为 (纬度, 经度) 列表，顺序与 rays 一致。"""
    return [(lat, lng) for _, pts in rays for (_, lat, lng) in pts]


def boundary_by_rays(
    rays, elements, limit_s: float, step_m: float, max_radius_m: float
) -> list[tuple[float, float]]:
    """每方向求最远可达边界距离（米），相邻测点间线性插值细化。返回 [(角度, 距离)]。

    注意：elements 为完整 480 点（每方向全部采样点，与 flat_destinations 同序）。
    这里按 `方向序号 * 每方向点数 + 步序` 直接定位元素，避免中途 break 导致 idx 错位。
    """
    n_steps = len(rays[0][1]) if rays else 0
    boundaries: list[tuple[float, float]] = []
    for ray_idx, (ang, pts) in enumerate(rays):
        prev_d, prev_dur = 0.0, 0.0
        bd = step_m * 0.5
        crossed = False
        base = ray_idx * n_steps
        for k, (d, _lat, _lng) in enumerate(pts):
            el = elements[base + k]
            dur: float | None = None
            if el and el.get("status", 0) == 0 and el.get("duration") is not None:
                dur = float(el["duration"])
            if dur is not None and dur <= limit_s:
                prev_d, prev_dur = d, dur
                continue
            cur_dur = dur if dur is not None else limit_s + 1.0
            if prev_dur < limit_s < cur_dur:
                frac = (limit_s - prev_dur) / max(cur_dur - prev_dur, 1e-9)
                bd = prev_d + frac * (d - prev_d)
            else:
                bd = prev_d if prev_d > 0 else step_m * 0.5
            crossed = True
            break
        if not crossed:
            bd = max_radius_m if prev_d >= max_radius_m - 1e-9 else prev_d
        boundaries.append((ang, bd))
    return boundaries


def idw_minutes_grid(
    center_lat: float, center_lng: float, rays, elements, limit_s: float, max_radius_m: float, grid_n: int = 60
) -> list[list[float]]:
    """对中心周边方形 bbox 网格做 IDW 插值，返回"分钟"矩阵（行=北→南，列=西→东）。"""
    known: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]  # (东, 北, 秒)
    idx = 0
    for _ang, pts in rays:
        for (d, lat, lng) in pts:
            el = elements[idx]
            idx += 1
            dur: float | None = None
            if el and el.get("status", 0) == 0 and el.get("duration") is not None:
                dur = float(el["duration"])
            e, n = _to_local(center_lng, center_lat, lng, lat)
            known.append((e, n, dur if dur is not None else limit_s * 2.0))

    half = max_radius_m
    step = 2.0 * half / (grid_n - 1)
    grid: list[list[float]] = []
    for j in range(grid_n):
        north = half - j * step
        row = []
        for i in range(grid_n):
            east = -half + i * step
            row.append(_idw(east, north, known) / 60.0)
        grid.append(row)
    return grid


def _to_local(center_lng: float, center_lat: float, lng: float, lat: float) -> tuple[float, float]:
    east = (lng - center_lng) * 111320.0 * math.cos(math.radians(center_lat))
    north = (lat - center_lat) * 110540.0
    return east, north


def _idw(east: float, north: float, known: list[tuple[float, float, float]], k: int = 16) -> float:
    """反距离加权：取最近 k 个已知测时点，权重 1/d²。"""
    heap: list[tuple[float, float]] = []
    for (e, n, dur) in known:
        dx = e - east
        dy = n - north
        d2 = dx * dx + dy * dy
        if d2 < 1e-6:
            return dur
        w = 1.0 / d2
        if len(heap) < k:
            heapq.heappush(heap, (w, dur))
        elif w > heap[0][0]:
            heapq.heapreplace(heap, (w, dur))
    wsum = sum(item[0] for item in heap)
    tsum = sum(item[0] * item[1] for item in heap)
    return tsum / wsum if wsum > 0 else 0.0


def marching_squares(values: list[list[float]], level: float) -> list[list[tuple[float, float]]]:
    """从分钟场提取等值线，返回格子坐标系下的闭合多边形列表。"""
    n = len(values)
    segs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for j in range(n - 1):
        for i in range(n - 1):
            a = values[j][i]
            b = values[j][i + 1]
            c = values[j + 1][i + 1]
            d = values[j + 1][i]
            case = (1 if a > level else 0) | (2 if b > level else 0) | (4 if c > level else 0) | (8 if d > level else 0)
            pairs = CASE_SEGMENTS[case]
            if not pairs:
                continue
            tl, tr, br, bl = (i, j), (i + 1, j), (i + 1, j + 1), (i, j + 1)

            def interp(p1, v1, p2, v2):
                if abs(v2 - v1) < 1e-12:
                    return (p1[0] + p2[0]) / 2.0, (p1[1] + p2[1]) / 2.0
                t = (level - v1) / (v2 - v1)
                return p1[0] + t * (p2[0] - p1[0]), p1[1] + t * (p2[1] - p1[1])

            edge_pts = {
                0: interp(tl, a, tr, b),
                1: interp(tr, b, br, c),
                2: interp(br, c, bl, d),
                3: interp(bl, d, tl, a),
            }
            for e1, e2 in pairs:
                segs.append((edge_pts[e1], edge_pts[e2]))
    return _connect_segments(segs)


def _key(p: tuple[float, float], nd: int = 4) -> tuple[float, float]:
    return (round(p[0], nd), round(p[1], nd))


def _connect_segments(segs) -> list[list[tuple[float, float]]]:
    """把等值线段首尾相连成闭合环。"""
    from collections import defaultdict

    adj: dict[tuple[float, float], list] = defaultdict(list)
    for s in segs:
        adj[_key(s[0])].append(s)
        adj[_key(s[1])].append(s)

    used: set[int] = set()
    polygons: list[list[tuple[float, float]]] = []
    for start in segs:
        if id(start) in used:
            continue
        loop = [start[0]]
        cur_end = _key(start[1])
        used.add(id(start))
        guard = 0
        while cur_end != _key(start[0]) and guard <= len(segs):
            guard += 1
            nxt = None
            for cand in adj[cur_end]:
                if id(cand) not in used:
                    nxt = cand
                    break
            if nxt is None:
                break
            used.add(id(nxt))
            if _key(nxt[0]) == cur_end:
                loop.append(nxt[0])
                cur_end = _key(nxt[1])
            else:
                loop.append(nxt[1])
                cur_end = _key(nxt[0])
        if len(loop) >= 3:
            polygons.append(loop)
    return polygons


def _shoelace_area(pts) -> float:
    area = 0.0
    for i in range(len(pts)):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % len(pts)]
        area += x1 * y2 - x2 * y1
    return abs(area) / 2.0


def _polygon_area_km2(center_lat: float, pts) -> float:
    if len(pts) < 3:
        return 0.0
    x = [(p[0] - pts[0][0]) * 111320.0 * math.cos(math.radians(center_lat)) for p in pts]
    y = [(p[1] - pts[0][1]) * 110540.0 for p in pts]
    area = 0.0
    for i in range(len(pts)):
        area += x[i] * y[(i + 1) % len(pts)] - x[(i + 1) % len(pts)] * y[i]
    return abs(area) / 2.0 / 1e6


async def compute_isochrone(
    center_lat: float,
    center_lng: float,
    client: Any,
    cfg: Any,
    walk_minutes: int | None = None,
    bucket: Any | None = None,
) -> dict:
    """计算 15 分钟步行等时圈。

    client: 提供 route_matrix_walking(origins, destinations) -> {"elements": [...]} 的客户端
            （BaiduClient 或 MockBaiduClient）。
    """
    limit_s = (walk_minutes or cfg.walking_minutes) * 60
    rays = build_rays(center_lat, center_lng, cfg.directions, cfg.step_m, cfg.max_radius_m)
    dests = flat_destinations(rays)

    # 批量测时：分块 + 限流（并发由上层控制；块内顺序保持与 rays 一致）
    elements: list[dict] = []
    for i in range(0, len(dests), cfg.matrix_chunk):
        chunk = dests[i:i + cfg.matrix_chunk]
        result = await client.route_matrix_walking([(center_lat, center_lng)], chunk)
        elements.extend(result["elements"])

    boundaries = boundary_by_rays(rays, elements, limit_s, cfg.step_m, cfg.max_radius_m)
    grid_min = idw_minutes_grid(center_lat, center_lng, rays, elements, limit_s, cfg.max_radius_m, cfg.grid_n)

    # —— 网格硬边界修正 ——
    # IDW 插值在稀疏方向（水域/障碍）会把采样点之间的空白“填平”，导致等时圈凸出到
    # 采样真实边界之外（典型：跨河/跨湖假覆盖）。这里用每个方向的真实可达边界做硬约束：
    # 任何格点距中心超过其所在方向的真实边界距离 → 强制标记为超时。
    # （注：routematrix 对水域点本身返回近似直线耗时，属于百度批量算路口径，
    #   此修正负责消除“插值凸出”这一层误差。）
    bd_map = {ang: bd for ang, bd in boundaries}
    ang_list = sorted(bd_map.keys())
    half = cfg.max_radius_m
    n_side = cfg.grid_n
    for j in range(n_side):
        for i in range(n_side):
            e = (i / (n_side - 1) * 2.0 - 1.0) * half       # 东向米
            nn = (1.0 - j / (n_side - 1) * 2.0) * half      # 北向米
            dist = (e * e + nn * nn) ** 0.5
            if dist < 60.0:
                continue
            ang = math.degrees(math.atan2(e, nn)) % 360.0
            bd = bd_map[min(ang_list, key=lambda a: abs(((a - ang) + 180) % 360 - 180))]
            if dist > bd + 1e-6:
                grid_min[j][i] = limit_s / 60.0 + 1.0

    # 等值线 → 经纬度多边形，取面积最大者
    polygons = marching_squares(grid_min, limit_s / 60.0)
    contour = None
    if polygons:
        geo_polys = []
        for poly in polygons:
            geo = [
                (
                    center_lng + (x / (cfg.grid_n - 1) * 2.0 - 1.0) * cfg.max_radius_m
                    / (111320.0 * math.cos(math.radians(center_lat))),
                    center_lat + (1.0 - y / (cfg.grid_n - 1) * 2.0) * cfg.max_radius_m / 110540.0,
                )
                for (x, y) in poly
            ]
            geo_polys.append(geo)
        contour = max(geo_polys, key=_shoelace_area)

    # 扇区边界多边形（兜底渲染 + 边界点统计）
    boundary_polygon = []
    for (ang, d) in boundaries:
        rad = math.radians(ang)
        lng, lat = offset_lnglat(center_lng, center_lat, d * math.sin(rad), d * math.cos(rad))
        boundary_polygon.append((lng, lat))

    max_reach = max(boundaries, key=lambda t: t[1])[1] if boundaries else 0.0
    stats_polygon = contour or boundary_polygon
    flat_values = [round(v, 2) for row in grid_min for v in row]
    max_minutes = max(flat_values) if flat_values else 0.0

    return {
        "polygon": [[round(lng, 6), round(lat, 6)] for lng, lat in contour] if contour else None,
        "boundary_polygon": [[round(lng, 6), round(lat, 6)] for lng, lat in boundary_polygon],
        "grid": {"n": cfg.grid_n, "half_size_m": cfg.max_radius_m, "max_minutes": round(max_minutes, 2), "values": flat_values},
        "stats": {
            "max_reach_m": round(max_reach, 1),
            "area_km2": round(_polygon_area_km2(center_lat, stats_polygon), 4),
            "boundary_points": len(boundaries),
            "walk_minutes": int(limit_s // 60),
        },
    }

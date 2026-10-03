"""服务盲区识别（命中 40% 功能正确性）。

规则：中心点周边 1km 内没有"菜市场、药店、小学"中任一类的点位判定为服务盲区。
实现：1km 方形区域网格化 → 逐格检查 1km 缓冲区内三类关键设施是否齐备 →
      连通的无覆盖格网合并为簇 → 凸包多边形即"灰色区域"。
"""
import math

from .coords import haversine_m

REQUIRED_CATEGORIES = ["菜市场", "药店", "小学"]


def detect_blind_spots(
    center_lat: float,
    center_lng: float,
    pois: list[dict],
    radius_m: float = 1000.0,
    cell_m: float = 200.0,
    required: list[str] | None = None,
) -> dict:
    required = required or REQUIRED_CATEGORIES
    n = max(3, math.ceil(2 * radius_m / cell_m))
    half = n * cell_m / 2.0

    # 按格索引 POI，加速缓冲查询
    grid_index: dict[tuple[int, int], list[dict]] = {}
    for p in pois:
        e = (p["lng"] - center_lng) * 111320.0 * math.cos(math.radians(center_lat))
        nn = (p["lat"] - center_lat) * 110540.0
        gx = int((e + half) // cell_m)
        gy = int((nn + half) // cell_m)
        grid_index.setdefault((gx, gy), []).append(p)

    blind_cells = []
    for j in range(n):
        for i in range(n):
            cx_lng, cx_lat = _cell_center(center_lng, center_lat, i, j, cell_m, half)
            missing = []
            for cat in required:
                if not _has_in_radius(grid_index, i, j, cx_lng, cx_lat, radius_m, cat, cell_m):
                    missing.append(cat)
            if missing:
                blind_cells.append({
                    "i": i, "j": j,
                    "lng": round(cx_lng, 6), "lat": round(cx_lat, 6),
                    "missing": missing,
                })

    clusters = _cluster_cells(blind_cells)
    polygons = []
    for cluster in clusters:
        corners = []
        for c in cluster:
            corners.extend(_cell_rect(center_lng, center_lat, c["i"], c["j"], cell_m, half))
        hull = _convex_hull(corners)
        if len(hull) >= 3:
            polygons.append([[round(lng, 6), round(lat, 6)] for (lng, lat) in hull])

    return {
        "required": required,
        "cell_m": cell_m,
        "radius_m": radius_m,
        "blind_cells": blind_cells,
        "cluster_count": len(clusters),
        "polygons": polygons,
        "summary": _summarize(blind_cells, clusters),
    }


def _cell_center(center_lng, center_lat, i, j, cell_m, half) -> tuple[float, float]:
    e = -half + (i + 0.5) * cell_m
    nn = -half + (j + 0.5) * cell_m
    lng = center_lng + e / (111320.0 * math.cos(math.radians(center_lat)))
    lat = center_lat + nn / 110540.0
    return lng, lat


def _cell_rect(center_lng, center_lat, i, j, cell_m, half) -> list[tuple[float, float]]:
    e0 = -half + i * cell_m
    e1 = e0 + cell_m
    n0 = -half + j * cell_m
    n1 = n0 + cell_m
    k = 111320.0 * math.cos(math.radians(center_lat))
    return [
        (center_lng + e0 / k, center_lat + n0 / 110540.0),
        (center_lng + e1 / k, center_lat + n0 / 110540.0),
        (center_lng + e1 / k, center_lat + n1 / 110540.0),
        (center_lng + e0 / k, center_lat + n1 / 110540.0),
    ]


def _has_in_radius(grid_index, i, j, lng, lat, radius_m, cat, cell_m) -> bool:
    """检查 (i,j) 格中心 radius_m 缓冲区内是否存在某类 POI。"""
    span = math.ceil(radius_m / cell_m) + 1
    for dx in range(-span, span + 1):
        for dy in range(-span, span + 1):
            for p in grid_index.get((i + dx, j + dy), []):
                key = p.get("search_key") or p.get("category")
                if key == cat and haversine_m(lng, lat, p["lng"], p["lat"]) <= radius_m:
                    return True
    return False


def _cluster_cells(cells: list[dict]) -> list[list[dict]]:
    """8 邻域连通聚类。"""
    by_pos = {(c["i"], c["j"]): c for c in cells}
    visited: set[tuple[int, int]] = set()
    clusters: list[list[dict]] = []
    for (i, j) in by_pos:
        if (i, j) in visited:
            continue
        stack = [(i, j)]
        visited.add((i, j))
        cluster: list[dict] = []
        while stack:
            x, y = stack.pop()
            cluster.append(by_pos[(x, y)])
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx == 0 and dy == 0:
                        continue
                    nb = (x + dx, y + dy)
                    if nb in by_pos and nb not in visited:
                        visited.add(nb)
                        stack.append(nb)
        clusters.append(cluster)
    return clusters


def _convex_hull(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Andrew 单调链凸包。"""
    pts = sorted({(round(p[0], 6), round(p[1], 6)) for p in points})
    if len(pts) <= 2:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _summarize(cells: list[dict], clusters: list[list[dict]]) -> str:
    if not cells:
        return "中心点 1km 范围内菜市场、药店、小学三类设施覆盖齐全，未发现服务盲区。"
    missing_set = sorted({m for c in cells for m in c["missing"]})
    return (
        f"检测到 {len(clusters)} 处服务盲区（灰色区域），共 {len(cells)} 个网格单元，"
        f"缺失设施：{'、'.join(missing_set)}。"
    )

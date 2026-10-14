"""从 geo-maps/earth-waterbodies-10m 重新生成昆明区域水体多边形。
解决 100m 版漏掉草海/岸线精度不足导致的"等时圈盖到水面"残留。
输入：data/tmp_waterbodies_10m/package/map.geo.json（WGS-84，OSM ODbL）
输出：data/water_polygons.json（BD-09，polys/bboxes 结构，与 WaterGuard 兼容）
用法：backend/.venv/Scripts/python.exe scripts/gen_water_polygons.py
"""
import json
import math
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "tmp_waterbodies_10m" / "package" / "map.geo.json"
OUT = ROOT / "data" / "water_polygons.json"
# 昆明主城 + 滇池 + 草海（WGS-84 经纬度）
BBOX = (102.50, 24.60, 103.10, 25.35)
AREA_MIN_KM2 = 0.01  # 过滤 1 公顷以下碎小水塘，保留滇池/草海/主要湖库

# 手工补充：OSM 水体源漏标的水面（BD-09 坐标）。
# 草海：滇池北端湖湾（海埂大坝以北），OSM/geo-maps 未完整标注，实测 15 分钟圈会盖到其蓝色水面，
# 故按昆明草海湖湾范围手工补充（宁多勿漏；复核成功的绿道/陆地仍由探测保留豁免）。
MANUAL_POLYS_BD09 = [
    [  # 草海核心湖湾
        (102.655, 24.955), (102.655, 24.948), (102.685, 24.945),
        (102.710, 24.945), (102.715, 24.950), (102.712, 24.958),
        (102.700, 24.963), (102.680, 24.965), (102.662, 24.962),
    ],
]

X_PI = 3.14159265358979324 * 3000.0 / 180.0
_PI = math.pi
_A = 6378245.0
_EE = 0.00669342162296594323


def _transform_lat(lng: float, lat: float) -> float:
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + 0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * _PI) + 40.0 * math.sin(lat / 3.0 * _PI)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * _PI) + 320 * math.sin(lat * _PI / 30.0)) * 2.0 / 3.0
    return ret


def _transform_lng(lng: float, lat: float) -> float:
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + 0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * _PI) + 20.0 * math.sin(2.0 * lng * _PI)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * _PI) + 40.0 * math.sin(lng / 3.0 * _PI)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * _PI) + 300.0 * math.sin(lng / 30.0 * _PI)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    dlat = _transform_lat(lng - 105.0, lat - 35.0)
    dlng = _transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * _PI
    magic = math.sin(radlat)
    magic = 1 - _EE * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((_A * (1 - _EE)) / (magic * sqrtmagic) * _PI)
    dlng = (dlng * 180.0) / (_A / sqrtmagic * math.cos(radlat) * _PI)
    return lng + dlng, lat + dlat


def gcj02_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    z = math.sqrt(lng * lng + lat * lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * X_PI)
    return z * math.cos(theta) + 0.0065, z * math.sin(theta) + 0.006


def wgs84_to_bd09(lng: float, lat: float) -> tuple[float, float]:
    return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))


def ring_area_km2(ring: list[tuple[float, float]]) -> float:
    """BD-09 平面 shoelace 面积（km²）。"""
    n = len(ring)
    if n < 3:
        return 0.0
    s = 0.0
    j = n - 1
    for i in range(n):
        xi, yi = ring[i]
        xj, yj = ring[j]
        s += xj * yi - xi * yj
        j = i
    mid_lat = sum(p[1] for p in ring) / n
    m_per_deg = 111320.0 * math.cos(math.radians(mid_lat))
    return abs(s) / 2.0 * m_per_deg * 110540.0 / 1e6


def simplify(ring: list[tuple[float, float]], tol_deg: float = 0.0004) -> list[tuple[float, float]]:
    """Douglas-Peucker 简化（~40m 精度，足够判水，控制文件体积）。"""
    if len(ring) <= 8:
        return ring
    keep = [0]
    stack = [(0, len(ring) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        x1, y1 = ring[a]
        x2, y2 = ring[b]
        max_d, max_i = 0.0, a
        for i in range(a + 1, b):
            x, y = ring[i]
            d = abs((x2 - x1) * (y1 - y) - (x1 - x) * (y2 - y1)) / (math.hypot(x2 - x1, y2 - y1) or 1e-12)
            if d > max_d:
                max_d, max_i = d, i
        if max_d > tol_deg:
            keep.append(max_i)
            stack.append((a, max_i))
            stack.append((max_i, b))
    keep.append(len(ring) - 1)
    keep.sort()
    out = [ring[i] for i in keep]
    return out if len(out) >= 4 else ring


def main() -> None:
    t0 = time.time()
    data = json.loads(SRC.read_text(encoding="utf-8"))
    geometries = data.get("geometries", data.get("features", []))
    print(f"loaded {SRC.name}: {len(geometries)} geometries in {time.time()-t0:.1f}s")
    polys: list[list[tuple[float, float]]] = []
    bboxes: list[list[float]] = []
    n_skip_bbox = n_skip_area = n_skip_bad = 0
    for geom in geometries:
        if isinstance(geom, dict):
            gtype = geom.get("type")
            coords = geom.get("coordinates")
        else:
            gtype, coords = geom.type, geom.coordinates
        rings = []
        if gtype == "Polygon":
            rings = [coords[0]] if coords else []
        elif gtype == "MultiPolygon":
            rings = [r[0] for r in coords] if coords else []
        for ring in rings:
            if len(ring) < 4:
                continue
            lons = [p[0] for p in ring]
            lats = [p[1] for p in ring]
            if max(lons) < BBOX[0] or min(lons) > BBOX[2] or max(lats) < BBOX[1] or min(lats) > BBOX[3]:
                n_skip_bbox += 1
                continue
            ring_bd = [wgs84_to_bd09(float(p[0]), float(p[1])) for p in ring]
            # 坏点过滤：剔除 NaN/超大坐标（数据缺陷），剩余点数 <4 才整环丢弃
            ring_bd = [(x, y) for x, y in ring_bd
                       if -180.0 <= x <= 180.0 and -90.0 <= y <= 90.0 and math.isfinite(x) and math.isfinite(y)]
            if len(ring_bd) < 4:
                n_skip_bad = n_skip_bad + 1
                continue
            area = ring_area_km2(ring_bd)
            if area < AREA_MIN_KM2:
                n_skip_area += 1
                continue
            ring_bd = simplify(ring_bd)
            lngs = [p[0] for p in ring_bd]
            lats_bd = [p[1] for p in ring_bd]
            polys.append([(round(x, 6), round(y, 6)) for x, y in ring_bd])
            bboxes.append([min(lngs), min(lats_bd), max(lngs), max(lats_bd)])
    out = {
        "source": "geo-maps/earth-waterbodies-10m (OSM data, ODbL), cropped to Kunming, WGS->BD-09 + manual caohai",
        "polys": polys,
        "bboxes": bboxes,
    }
    for ring in MANUAL_POLYS_BD09:
        lngs = [p[0] for p in ring]
        lats_bd = [p[1] for p in ring]
        polys.append([(round(x, 6), round(y, 6)) for x, y in ring])
        bboxes.append([min(lngs), min(lats_bd), max(lngs), max(lats_bd)])
    out["polys"] = polys
    out["bboxes"] = bboxes
    OUT.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    size_mb = OUT.stat().st_size / 1e6
    print(f"wrote {OUT.name}: {len(polys)} polys ({size_mb:.1f} MB) "
          f"skipped bbox={n_skip_bbox} area={n_skip_area} bad={n_skip_bad} in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()

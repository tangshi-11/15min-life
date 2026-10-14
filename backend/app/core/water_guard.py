"""水域仲裁：区分"真水域"与"未建模陆地步道"。

背景：百度算路接口（routematrix / directionlite）对两类区域都会返回
"0s / 1m" 的垃圾数据：① 真水域（湖面/河道，确实不可步行）；② 未建模的
陆地步道（滇池绿道等，实际可步行）。两类在算路接口里无法区分，若一刀切
"内缩"会误砍绿道，若"保持采样边界"会再次把等时圈盖到水面上。

本模块用水体多边形数据作为垃圾数据方向的"裁判"：采样点落在水体多边形内 →
按水域处理（内缩）；否则按陆地处理（保留绿道/步道）。只做仲裁，不遮挡
正常算路结果。

数据优先级：
1. 本地水体数据（data/water_polygons.json，随项目分发，无网络依赖，评委
   演示也一致）——裁剪自 @geo-maps/earth-waterbodies-100m（OSM 数据，ODbL）。
   文件内多边形已转 BD-09 并建 3 位小数网格索引。
2. OpenStreetMap Overpass API（网络兜底；国内网络通常不可达，失败自动回退）。
失败/未启用时保守返回 True（按水域内缩，防盖水）。
"""
import asyncio
import json
import logging
import math
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

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
    """WGS84 -> BD-09（经 GCJ02），用于把 OSM 多边形转到百度坐标系。"""
    return gcj02_to_bd09(*wgs84_to_gcj02(lng, lat))


def point_in_polygon(lng: float, lat: float, poly: list[tuple[float, float]]) -> bool:
    """射线法判断点（BD-09）是否在多边形（BD-09）内。"""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > lat) != (yj > lat)) and (lng < (xj - xi) * (lat - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def point_edge_distance_m(lng: float, lat: float, poly: list[tuple[float, float]]) -> float:
    """点到多边形边界的最小距离（米，BD-09 平面近似）。
    用 poly 平均纬度换算度→米。"""
    n = len(poly)
    if n < 2:
        return 1e18
    mid_lat = sum(p[1] for p in poly) / n
    m_per_deg = 111320.0 * math.cos(math.radians(mid_lat))  # 经度向；纬度向 ~110540 近似同量级
    best = 1e18
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        if abs(dx) < 1e-12 and abs(dy) < 1e-12:
            d = math.hypot(lng - x1, lat - y1)
            best = min(best, d)
            continue
        t = ((lng - x1) * dx + (lat - y1) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        px, py = x1 + t * dx, y1 + t * dy
        best = min(best, math.hypot(lng - px, lat - py))
    return best * m_per_deg


class WaterGuard:
    """按中心点仲裁"采样点是否在水域内"。本地水体数据优先，Overpass 兜底。"""

    def __init__(self, session=None, radius_m: float = 3500.0,
                 overpass_url: str = "https://overpass-api.de/api/interpreter",
                 cache_path: str | None = None, enabled: bool = True,
                 local_geojson: str | None = None, margin_m: float = 300.0):
        self.session = session
        self.radius_m = radius_m
        self.overpass_url = overpass_url
        self.enabled = enabled
        self.margin_m = margin_m
        self._local_polys: list[list[tuple[float, float]]] = []
        self._local_bboxes: list[tuple[float, float, float, float]] = []
        if local_geojson and Path(local_geojson).exists():
            try:
                data = json.loads(Path(local_geojson).read_text(encoding="utf-8"))
                self._local_polys = [tuple(tuple(p) for p in poly) for poly in data.get("polys", [])]
                self._local_bboxes = [tuple(b) for b in data.get("bboxes", [])]
                logger.info("水域仲裁：已加载本地水体数据 %d 个多边形（%s）", len(self._local_polys), local_geojson)
            except Exception as exc:
                logger.warning("本地水体数据加载失败：%s", exc)
        self._mem: dict[tuple[str, str], list[int]] = {}
        self._lock = asyncio.Lock()
        self._db: sqlite3.Connection | None = None
        if cache_path:
            Path(cache_path).parent.mkdir(parents=True, exist_ok=True)
            self._db = sqlite3.connect(cache_path, check_same_thread=False)
            self._db.execute("CREATE TABLE IF NOT EXISTS water(lat3 TEXT, lng3 TEXT, payload TEXT, PRIMARY KEY(lat3, lng3))")

    @staticmethod
    def _cache_key(lat: float, lng: float) -> tuple[str, str]:
        return f"{lat:.3f}", f"{lng:.3f}"

    async def is_water(self, center_ll: tuple[float, float], point_ll: tuple[float, float],
                       margin_m: float | None = None) -> bool:
        """center_ll / point_ll 均为 BD-09。point 是否落在水体多边形内。
        margin_m：None → 用 self.margin_m（默认 300m 缓冲带，保护岸边绿道）；
        传 0 → 严格判水（等时圈水域仲裁用：岸边水面也排除，蓝色=水不可过）。
        未启用/数据不可用 → 返回 True（保守按水域处理，防盖水）。"""
        if not self.enabled:
            return True
        try:
            if self._local_polys:
                return await asyncio.to_thread(self._is_water_sync, center_ll, point_ll, margin_m)
            # 无本地数据 → Overpass 兜底（异步网络查询）
            polys = await self._polygons_overpass_cached(center_ll)
            lat, lng = point_ll
            for poly in polys:
                if point_in_polygon(lng, lat, poly):
                    return True
            return False
        except Exception as exc:
            logger.warning("水域仲裁失败，按水域保守处理：%s", exc)
            return True

    def _is_water_sync(self, center_ll: tuple[float, float], point_ll: tuple[float, float],
                       margin_m: float | None = None) -> bool:
        lat, lng = point_ll
        margin = self.margin_m if margin_m is None else margin_m
        # 环 bbox 粗筛 + 射线法直接遍历（数千个环，每点判断 < 1ms）
        for idx, bbox in enumerate(self._local_bboxes):
            if bbox[0] <= lng <= bbox[2] and bbox[1] <= lat <= bbox[3]:
                poly = self._local_polys[idx]
                if point_in_polygon(lng, lat, poly):
                    # 距岸线边界 ≥ margin 才算"开阔水面"；岸边缓冲带（绿道/步道）
                    # 判定为陆地保留（OSM 岸线常有外扩误差，默认岸边 300m 内不轻易判水）
                    return point_edge_distance_m(lng, lat, poly) >= margin
        return False

    async def _polygons_overpass_cached(self, center_ll: tuple[float, float]) -> list[list[tuple[float, float]]]:
        if self.session is None:
            raise RuntimeError("WaterGuard 无网络会话且无本地数据")
        lat3, lng3 = self._cache_key(*center_ll)
        key = (lat3, lng3)
        if key in self._mem:
            return self._mem[key]
        if self._db:
            row = self._db.execute("SELECT payload FROM water WHERE lat3=? AND lng3=?", key).fetchone()
            if row:
                polys = json.loads(row[0])
                self._mem[key] = polys
                return polys
        async with self._lock:
            if self._db:
                row = self._db.execute("SELECT payload FROM water WHERE lat3=? AND lng3=?", key).fetchone()
                if row:
                    polys = json.loads(row[0])
                    self._mem[key] = polys
                    return polys
            polys = await self._query_overpass(center_ll)
            if self._db:
                self._db.execute("INSERT OR REPLACE INTO water(lat3, lng3, payload) VALUES(?,?,?)", (key[0], key[1], json.dumps(polys)))
                self._db.commit()
            self._mem[key] = polys
            return polys

    async def _query_overpass(self, center_ll: tuple[float, float]) -> list[list[tuple[float, float]]]:
        lat, lng = center_ll
        q = (
            f'[out:json][timeout:25];'
            f'(way["natural"="water"](around:{int(self.radius_m)},{lat:.6f},{lng:.6f});'
            f'relation["natural"="water"](around:{int(self.radius_m)},{lat:.6f},{lng:.6f}););'
            f'out body geom;'
        )
        resp = await self.session.post(self.overpass_url, data={"data": q}, timeout=30)
        data = resp.json()
        polys: list[list[tuple[float, float]]] = []
        for el in data.get("elements", []):
            geom = el.get("geometry")
            if not geom or len(geom) < 3:
                continue
            poly = [wgs84_to_bd09(float(p["lon"]), float(p["lat"])) for p in geom]
            polys.append(poly)
        return polys

"""演示数据客户端：无 AK 或 API 异常时的兜底（容错降级）。

生成确定性的模拟步行耗时与 POI 分布：
- 用"河流/围墙"角度带模拟真实路网的阻挡效果，让等时圈出现收缩；
- 东北象限刻意缺少菜市场/药店/小学，制造可见的服务盲区，用于演示"灰色区域"识别。
"""
import hashlib
import math
import random

from ..core.coords import haversine_m, offset_lnglat

MOCK_CENTER = {"lng": 102.7146, "lat": 25.0406}  # 昆明市五华区翠湖片区

# 模拟路网阻挡：角度带(度, 度) → 额外耗时(秒)
BARRIERS = [(40.0, 75.0, 900.0), (200.0, 230.0, 480.0)]

# 演示 POI 生成计划：名称 / 数量 / 分布密度
POI_PLAN = [
    ("菜市场", 12, 0.006),
    ("药店", 24, 0.012),
    ("小学", 10, 0.006),
    ("医院", 6, 0.008),
    ("超市", 22, 0.015),
    ("公园", 8, 0.008),
    ("银行", 14, 0.010),
    ("养老院", 5, 0.005),
    ("餐厅", 40, 0.03),
    ("公交站", 16, 0.02),
    ("地铁站", 6, 0.008),
]

# 稀疏扇区（东北偏东 0~135°）用于展示盲区：关键设施完全不在该扇区出现
SPARSE_QUADRANT = (0.0, 135.0)
SPARSE_TARGETS = {"菜市场", "药店", "小学"}


class MockBaiduClient:
    """与 BaiduClient 同接口的演示实现，接口契约一致，便于无缝切换。"""

    def __init__(self, seed: int = 42) -> None:
        self.seed = seed

    async def geocode(self, address: str, city: str | None = None) -> dict:
        if "呈贡" in address or "大学城" in address:
            return {"lng": 102.8488, "lat": 24.8530, "level": "区县", "precise": False}
        if "北京" in address:
            return {"lng": 116.397, "lat": 39.909, "level": "兴趣点", "precise": False}
        if "上海" in address:
            return {"lng": 121.4737, "lat": 31.2304, "level": "兴趣点", "precise": False}
        return {**MOCK_CENTER, "level": "兴趣点", "precise": False}

    async def reverse_geocode(self, lat: float, lng: float) -> dict:
        return {
            "address": "云南省昆明市五华区翠湖公园附近",
            "city": "昆明市",
            "district": "五华区",
            "town": "华山街道",
            "business": "翠湖",
        }

    async def place_search(
        self,
        query: str,
        *,
        location: tuple[float, float] | None = None,
        radius: float = 2000.0,
        city: str | None = None,
        tag: str | None = None,
        page_size: int = 20,
        max_pages: int = 5,
    ) -> list[dict]:
        center = location if location is not None else (MOCK_CENTER["lat"], MOCK_CENTER["lng"])
        return _mock_pois(center, radius, query, self.seed, tag)

    async def walking_direction(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
        d = haversine_m(origin[1], origin[0], destination[1], destination[0])
        dur = _mock_seconds(origin, destination, d, self.seed)
        return {"duration_s": dur, "distance_m": int(d)}

    async def route_matrix_walking(
        self, origins: list[tuple[float, float]], destinations: list[tuple[float, float]]
    ) -> dict:
        elements = []
        for (dlat, dlng) in destinations:
            d = haversine_m(origins[0][1], origins[0][0], dlng, dlat)
            dur = _mock_seconds(origins[0], (dlat, dlng), d, self.seed)
            elements.append({"distance": int(d), "duration": dur, "status": 0})
        return {"elements": elements}

    async def batch(self, sub_urls: list[str]) -> list[dict]:
        out = []
        for u in sub_urls:
            if "/geocoding/" in u:
                out.append({"status": 0, "result": {"location": MOCK_CENTER}})
            else:
                out.append({"status": 0, "result": {}})
        return out


def _mock_seconds(origin: tuple[float, float], dest: tuple[float, float], dist_m: float, seed: int) -> int:
    """模拟步行耗时：基础速度 1.3m/s + 路网阻挡 + 确定性噪声。"""
    speed = 1.3
    t = dist_m / speed
    ang = math.degrees(math.atan2(dest[1] - origin[1], dest[0] - origin[0])) % 360.0
    for lo, hi, penalty in BARRIERS:
        if lo <= ang <= hi:
            t += penalty
    h = hashlib.md5(f"{seed}:{round(dest[0], 4)}:{round(dest[1], 4)}".encode()).hexdigest()
    noise = (int(h[:4], 16) % 41 - 20) / 100.0  # -0.2 ~ +0.2 分钟
    return max(30, round(t + noise * 60))


def _mock_pois(
    center: tuple[float, float], radius: float, query: str, seed: int, tag: str | None = None
) -> list[dict]:
    # 用稳定哈希（md5）保证跨进程可复现
    qhash = int(hashlib.md5(query.encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed + qhash % 10000)
    pois = []
    for name, count, _spread in POI_PLAN:
        if query and query not in name and name not in query and tag and tag not in name and name not in tag:
            continue
        required = name in SPARSE_TARGETS
        for _ in range(count):
            ang = rng.uniform(0, 360)
            if required:
                # 关键设施集中在中心 1km 内；东北偏东扇区留空以展示"灰色区域"
                if SPARSE_QUADRANT[0] <= ang <= SPARSE_QUADRANT[1]:
                    ang = rng.uniform(136, 360)
                dist = rng.uniform(250, min(radius, 1000))
            else:
                dist = rng.uniform(200, radius * 0.92)
            lng, lat = offset_lnglat(
                center[1], center[0],
                dist * math.sin(math.radians(ang)),
                dist * math.cos(math.radians(ang)),
            )
            if name in ("菜市场", "药店", "超市", "银行", "餐厅"):
                display = f"{name}{rng.randint(1, 99)}号店"
            else:
                display = f"{name}·{rng.randint(1, 20)}"
            pois.append({
                "name": display,
                "location": {"lng": round(lng, 6), "lat": round(lat, 6)},
                "tag": name,
                "category": name,
                "address": "演示数据(Mock)",
            })
    return pois

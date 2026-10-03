"""百度地图开放平台 Web 服务 API 封装。

支持：地理编码 / 逆地理编码、地点检索(POI)、轻量步行路线规划、
步行批量算路(路线矩阵)、批量合并服务（一次最多 20 个子请求）。
所有请求统一走令牌桶限流 + 指数退避重试。
"""
import logging
from typing import Any

import httpx

from .rate_limiter import with_retry

logger = logging.getLogger(__name__)

BASE_URL = "https://api.map.baidu.com"


def _scalar(v) -> float | None:
    """routematrix 元素中的 duration/distance 可能是数字或 {text, value}（部分接口为数组），统一取秒/米数值。"""
    if isinstance(v, dict):
        return v.get("value")
    if isinstance(v, list) and v and isinstance(v[0], dict):
        return v[0].get("value")
    return v


class BaiduApiError(Exception):
    """百度地图 API 返回的业务错误。status 为接口返回的状态码。"""

    def __init__(self, status: int, message: str = "") -> None:
        super().__init__(f"百度API错误 status={status} {message}".strip())
        self.status = status
        self.message = message


class BaiduClient:
    """真实百度地图客户端。AK 缺失时由上层切换为 MockBaiduClient。"""

    def __init__(
        self,
        ak: str,
        session: httpx.AsyncClient,
        bucket: Any | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.ak = ak
        self.session = session
        self.bucket = bucket
        self.timeout = timeout

    async def _get(self, path: str, params: dict) -> dict:
        full = {**params, "ak": self.ak, "output": "json"}

        async def _request() -> dict:
            resp = await self.session.get(BASE_URL + path, params=full, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            status = int(data.get("status", -1))
            if status != 0:
                raise BaiduApiError(status, str(data.get("message", "")))
            return data

        return await with_retry(_request, bucket=self.bucket)

    async def geocode(self, address: str, city: str | None = None) -> dict:
        """地理编码：地址 → 百度坐标(BD-09)。"""
        params: dict[str, Any] = {"address": address}
        if city:
            params["city"] = city
        data = await self._get("/geocoding/v3/", params)
        loc = data["result"]["location"]
        return {
            "lng": float(loc["lng"]),
            "lat": float(loc["lat"]),
            "level": data["result"].get("level", ""),
            "precise": bool(data["result"].get("precise", 0)),
        }

    async def reverse_geocode(self, lat: float, lng: float) -> dict:
        """逆地理编码：坐标 → 地址文本。"""
        data = await self._get("/reverse_geocoding/v3/", {"location": f"{lat},{lng}"})
        r = data["result"]
        ac = r.get("addressComponent", {})
        return {
            "address": r.get("formatted_address", ""),
            "city": ac.get("city", ""),
            "district": ac.get("district", ""),
            "business": r.get("business", ""),
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
        """POI 检索（圆形区域检索），自动分页并返回原始结果列表。"""
        pois: list[dict] = []
        for page in range(max_pages):
            params: dict[str, Any] = {"query": query, "page_size": page_size, "page_num": page, "scope": 1}
            if location is not None:
                params["location"] = f"{location[0]},{location[1]}"
                params["radius"] = int(radius)
            if tag:
                params["tag"] = tag
            if city:
                params["region"] = city
            data = await self._get("/place/v2/search", params)
            results = data.get("results") or []
            pois.extend(results)
            if len(results) < page_size:
                break
        return pois

    async def walking_direction(self, origin: tuple[float, float], destination: tuple[float, float]) -> dict:
        """轻量步行路线规划：单点对，返回耗时(秒)与距离(米)。"""
        params = {
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{destination[0]},{destination[1]}",
        }
        data = await self._get("/directionlite/v1/walking", params)
        route = data["result"]["routes"][0]
        return {"duration_s": int(route["duration"]), "distance_m": int(route["distance"])}

    async def route_matrix_walking(
        self, origins: list[tuple[float, float]], destinations: list[tuple[float, float]]
    ) -> dict:
        """步行批量算路（路线矩阵）：一次请求多组起终点，起终点个数之积 ≤100，由调用方分块。

        真实接口的 result 为元素数组，且 duration/distance 为 {text, value} 对象；
        这里归一化为与 Mock 一致的 {"elements": [{"status", "duration", "distance"}]} 扁平结构。
        """
        params = {
            "origins": "|".join(f"{la},{lo}" for la, lo in origins),
            "destinations": "|".join(f"{la},{lo}" for la, lo in destinations),
            "coord_type": "bd09ll",
        }
        data = await self._get("/routematrix/v2/walking", params)
        raw = data.get("result")
        if isinstance(raw, dict):  # 兼容 {"elements": [...]} 结构
            raw = raw.get("elements", [])
        norm: list[dict] = []
        for el in raw or []:
            norm.append({
                "status": int(el.get("status", 0) or 0),
                "duration": _scalar(el.get("duration")),
                "distance": _scalar(el.get("distance")),
            })
        return {"elements": norm}

    async def batch(self, sub_urls: list[str]) -> list[dict]:
        """批量合并服务：一次最多 20 个子请求（子 URL 不带 ak/output=json）。"""
        async def _request() -> dict:
            resp = await self.session.post(
                BASE_URL + "/batch", params={"ak": self.ak}, json={"sub_url": sub_urls}, timeout=self.timeout
            )
            resp.raise_for_status()
            data = resp.json()
            status = int(data.get("status", -1))
            if status != 0:
                raise BaiduApiError(status, str(data.get("message", "")))
            return data

        data = await with_retry(_request, bucket=self.bucket)
        return data.get("result", [])

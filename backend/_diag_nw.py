"""定位：西北方向（contour 北界 971m 来源）为什么保留——复现 refine_boundaries 单方向路径。"""
import asyncio
import sys

sys.path.insert(0, "app")
import httpx

from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.api.rate_limiter import TokenBucket
from app.core.water_guard import WaterGuard
from app.core import isochrone


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as session:
        bucket = TokenBucket(10.0)
        dbucket = TokenBucket(1.2)
        client = BaiduClient(cfg.ak_server, session, bucket=bucket, direction_bucket=dbucket)
        wg = WaterGuard(
            session, radius_m=cfg.water_guard_radius_m, overpass_url=cfg.overpass_url,
            cache_path=r"E:\上海\15min-life-circle\data\water_cache.sqlite",
            local_geojson=r"E:\上海\15min-life-circle\data\water_polygons.json",
            margin_m=cfg.water_guard_margin_m, enabled=True,
        )
        c = (24.741355, 102.694037)
        # 直接复核+探测（模拟 refine 对单个方向的处理），不传 wg，先看算路返回
        for ang in [315.0, 337.5, 345.0, 352.5, 0.0]:
            for bd in [971.0]:
                import math
                from app.core.isochrone import offset_lnglat
                rad = math.radians(ang)
                lng, lat = offset_lnglat(c[1], c[0], bd * math.sin(rad), bd * math.cos(rad))
                try:
                    info = await client.walking_direction((c[0], c[1]), (lat, lng))
                    t = float(info["duration_s"]); d = float(info.get("distance_m", 0.0))
                    print(f"ang={ang} bd={bd} -> t={t}s d={d}m")
                except Exception as e:
                    print(f"ang={ang} bd={bd} -> ERR {repr(e)[:120]}")
                # 探测 1.6x
                pd = min(bd * 1.6, 2000.0)
                plng, plat = offset_lnglat(c[1], c[0], pd * math.sin(rad), pd * math.cos(rad))
                try:
                    pinfo = await client.walking_direction((c[0], c[1]), (plat, plng))
                    pt = float(pinfo["duration_s"]); pd_ = float(pinfo.get("distance_m", 0.0))
                    print(f"   probe {pd:.0f}m -> t={pt}s d={pd_}m ratio={pd_/pd:.2f}")
                except Exception as e:
                    print(f"   probe {pd:.0f}m -> ERR {repr(e)[:120]}")
                w = await wg.is_water((c[0], c[1]), (lat, lng))
                print(f"   is_water({ang},{bd:.0f}m) = {w}")


asyncio.run(main())

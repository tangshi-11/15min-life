import asyncio, sys, math
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.core.coords import offset_lnglat
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s)
        center = (24.741355, 102.694037)
        dists = [750, 800, 850, 900, 950, 1000, 1050, 1100, 1200, 1300, 1400, 1500]
        for d in dists:
            lng, lat = offset_lnglat(center[1], center[0], d * math.sin(math.radians(270)), d * math.cos(math.radians(270)))
            info = await c.walking_direction(center, (lat, lng))
            print(f"西{d}m: {info}", flush=True)


asyncio.run(main())

import asyncio, sys, math, time
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.core.isochrone import refine_boundaries
from app.core.coords import offset_lnglat
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s)
        center = (24.741355, 102.694037)  # lat, lng
        # 手动探测 270° 700m → 1050m
        for name, d in [("西700m边界", 700.0), ("西1050m探测", 1050.0)]:
            lng, lat = offset_lnglat(center[1], center[0], d * math.sin(math.radians(270)), d * math.cos(math.radians(270)))
            info = await c.walking_direction(center, (lat, lng))
            print(f"{name}: {info}", flush=True)
        # 走 refine_boundaries（270° 单方向）
        t0 = time.time()
        out = await refine_boundaries(center[0], center[1], [(270.0, 700.0)], c, 900.0, 100.0, 2000.0, max_refines=1)
        print(f"refine(270,700) -> {out}  ({time.time()-t0:.1f}s)", flush=True)


asyncio.run(main())

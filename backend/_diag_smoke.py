import asyncio, sys
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.api.rate_limiter import TokenBucket
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s, direction_bucket=TokenBucket(1.2))
        center = (24.741355, 102.694037)
        # 3 个冒烟点（间隔由 bucket 控制）
        for d in (700.0, 1120.0, 1500.0):
            lng, lat = 102.694037 - d / 101000.0, 24.741355
            info = await c.walking_direction(center, (lat, lng))
            print(f"西{d}m: {info}", flush=True)


asyncio.run(main())

import asyncio, sys
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s)
        center = (24.741355, 102.694037)
        tests = [
            ("西1000m", (24.7413, 102.6850)),
            ("西1200m", (24.7413, 102.6832)),
            ("西1500m", (24.7413, 102.6790)),
            ("北1000m", (24.7500, 102.6940)),
            ("北1500m", (24.7550, 102.6940)),
            ("北2000m", (24.7590, 102.6940)),
            ("北2500m", (24.7650, 102.6940)),
            ("南800m", (24.7340, 102.6940)),
        ]
        for name, d in tests:
            try:
                info = await c.walking_direction(center, d)
                print(f"{name}: {info}", flush=True)
            except Exception as e:
                print(f"{name}: ERR {e!r}", flush=True)


asyncio.run(main())

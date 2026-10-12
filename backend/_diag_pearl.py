import asyncio, sys
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s)
        tests = [
            ("北500m跨珠江", (23.1085, 113.2602), (23.1142, 113.2602)),
            ("西500m沿江岸", (23.1085, 113.2602), (23.1085, 113.2520)),
            ("北1000m跨江", (23.1085, 113.2602), (23.1195, 113.2602)),
        ]
        for name, o, d in tests:
            try:
                info = await c.walking_direction(o, d)
                print(name, info, flush=True)
            except Exception as e:
                print(name, "ERR", repr(e), flush=True)


asyncio.run(main())

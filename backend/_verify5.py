# -*- coding: utf-8 -*-
"""验证：取等时圈边界上 5 个点，用 directionlite 单点算路验证是否≈900秒。"""
import asyncio
import json
import time

import httpx

AK = "JDE4ejE1vN5uw9VxveIz5UchKXdSWRZq"
BASE = "https://api.map.baidu.com"
CENTER = (25.0406, 102.7146)


async def main():
    async with httpx.AsyncClient(timeout=25) as s:
        # 1) 拿等时圈边界
        req = httpx.Request(
            "POST", "http://127.0.0.1:8000/api/inspect",
            json={"center": {"lat": CENTER[0], "lng": CENTER[1]}},
        )
        # 直接调主服务
        import urllib.request
        body = json.dumps({"center": {"lat": CENTER[0], "lng": CENTER[1]}}).encode()
        r = urllib.request.urlopen(
            urllib.request.Request("http://127.0.0.1:8000/api/inspect", data=body,
                                   headers={"Content-Type": "application/json"}),
            timeout=150,
        )
        j = json.loads(r.read())
        poly = j["isochrone"]["boundary_polygon"]
        print("boundary 点数:", len(poly))
        # 取 5 个均匀分布的点
        n = len(poly)
        picks = [poly[i * n // 5 % n] for i in range(5)]
        print("=" * 60)
        for idx, (lng, lat) in enumerate(picks, 1):
            params = {
                "origin": f"{CENTER[0]},{CENTER[1]}",
                "destination": f"{lat},{lng}",
                "ak": AK, "output": "json",
            }
            ok = False
            for attempt in range(3):
                try:
                    resp = await s.get(BASE + "/directionlite/v1/walking", params=params)
                    data = resp.json()
                    if data.get("status") == 0:
                        rt = data["result"]["routes"][0]
                        print(f"点{idx}: 边界({lng:.5f},{lat:.5f}) 距离中心 "
                              f"{int(rt['distance'])}m 耗时 {int(rt['duration'])}s "
                              f"({int(rt['duration'])/60:.1f}分钟) "
                              f"{'✓' if 810 <= int(rt['duration']) <= 990 else '✗偏差'}")
                        ok = True
                        break
                    else:
                        print(f"点{idx}: 第{attempt+1}次 err{data.get('status')}，等待重试")
                except Exception as e:
                    print(f"点{idx}: 第{attempt+1}次异常 {e}")
                await asyncio.sleep(2.0 * (attempt + 1))
            if not ok:
                print(f"点{idx}: 3 次均失败")
            await asyncio.sleep(1.2)  # 防并发配额


asyncio.run(main())

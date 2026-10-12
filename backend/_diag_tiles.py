"""诊断：高德底图瓦片的水域像素颜色特征（确定水域色阈值）。"""
import asyncio
import math
import sys
from collections import Counter
from io import BytesIO
from pathlib import Path

import httpx
from PIL import Image

sys.path.insert(0, r"E:\上海\15min-life-circle\backend")

X_PI = 3.14159265358979324 * 3000.0 / 180.0


def bd09_to_gcj02(lng, lat):
    x = lng - 0.0065
    y = lat - 0.006
    z = math.sqrt(x * x + y * y) - 0.00002 * math.sin(y * X_PI)
    theta = math.atan2(y, x) - 0.000003 * math.cos(x * X_PI)
    return z * math.cos(theta), z * math.sin(theta)


def tile_xy(lng, lat, z):
    n = 2 ** z
    x = int((lng + 180.0) / 360.0 * n)
    y = int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n)
    return x, y


def pixel_in_tile(lng, lat, z):
    n = 2 ** z
    xf = (lng + 180.0) / 360.0 * n
    yf = (1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * n
    tx, ty = int(xf), int(yf)
    px = int((xf - tx) * 256)
    py = int((yf - ty) * 256)
    return tx, ty, px, py


async def fetch_tile(session, x, y, z, cache_dir):
    cache_dir.mkdir(parents=True, exist_ok=True)
    p = cache_dir / f"{z}_{x}_{y}.png"
    if p.exists():
        return Image.open(p).convert("RGB")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36",
        "Referer": "https://ditu.amap.com/",
    }
    for s in "1234":
        try:
            url = f"https://webrd0{s}.is.autonavi.com/appmaptile?lang=zh_cn&size=1&scale=1&style=8&x={x}&y={y}&z={z}"
            resp = await session.get(url, timeout=20, headers=headers)
            if resp.status_code == 200 and len(resp.content) > 500:
                img = Image.open(BytesIO(resp.content)).convert("RGB")
                img.save(p)
                return img
            await asyncio.sleep(0.4)
        except Exception as e:
            print("tile fetch err", s, e)
            await asyncio.sleep(0.4)
    return None


def region_colors(img, cx, cy, r=24):
    w, h = img.size
    cnt = Counter()
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            x, y = cx + dx, cy + dy
            if 0 <= x < w and 0 <= y < h:
                cnt[img.getpixel((x, y))] += 1
    return cnt.most_common(12)


async def main():
    center = (24.741355, 102.694037)  # lat, lng BD09
    pts = {
        "中心点岸边": (24.741355, 102.694037),
        "北500m湿地": (24.7460, 102.6940),
        "北1500m水面": (24.7550, 102.6940),
        "北2500m水面": (24.7650, 102.6940),
        "西绿道500m": (24.7413, 102.6887),
        "东陆地500m": (24.7413, 102.7007),
    }
    cache = Path(r"E:\上海\15min-life-circle\data\tmp_tiles")
    async with httpx.AsyncClient(timeout=25) as session:
        for name, (lat, lng) in pts.items():
            glng, glat = bd09_to_gcj02(lng, lat)
            tx, ty, px, py = pixel_in_tile(glng, glat, 16)
            img = await fetch_tile(session, tx, ty, 16, cache)
            if img is None:
                print(name, "瓦片下载失败")
                continue
            colors = region_colors(img, px, py, r=20)
            top = ", ".join(f"#{r:02X}{g:02X}{b:02X}x{c}" for (r, g, b), c in colors[:6])
            total = sum(c for _, c in colors)
            print(f"{name}: pixel=({px},{py}) top={top} (n={total})", flush=True)


asyncio.run(main())

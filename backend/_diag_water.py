import asyncio, sys
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.core.water_guard import WaterGuard

DATA = r"E:\上海\15min-life-circle\data\water_polygons.json"


async def main():
    wg = WaterGuard(session=None, cache_path=None, enabled=True, local_geojson=DATA)
    center = (24.741355, 102.694037)
    pts = [
        ("中心点(岸边)", (24.741355, 102.694037)),
        ("北侧湖面500m", (24.7460, 102.6940)),
        ("北侧湖面1500m", (24.7550, 102.6940)),
        ("北侧湖面2500m", (24.7650, 102.6940)),
        ("西侧绿道300m", (24.741355, 102.6910)),
        ("西侧绿道500m", (24.7413, 102.6887)),
        ("西侧绿道700m", (24.7413, 102.6865)),
        ("东侧陆地500m", (24.7413, 102.7007)),
        ("东南陆地700m", (24.7359, 102.7000)),
        ("南侧湿地400m", (24.7378, 102.6940)),
        ("南侧湿地800m", (24.7340, 102.6940)),
        ("东侧2000m远", (24.7413, 102.7140)),
    ]
    for name, pt in pts:
        r = await wg.is_water(center, pt)
        print(f"{name}: in_water={r}", flush=True)


asyncio.run(main())

"""临时诊断：用户中心点(滇池南岸)的等时圈连通域数量。不改项目代码。"""
import asyncio, sys, math
sys.path.insert(0, ".")
from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.core import isochrone


async def main():
    import aiohttp
    cfg = Settings()
    session = aiohttp.ClientSession()
    client = BaiduClient(cfg, session)
    center = (24.741355, 102.694037)
    limit_s = 900.0
    rays = isochrone.build_rays(center[0], center[1], cfg.directions, cfg.step_m, cfg.max_radius_m)
    dests = isochrone.flat_destinations(rays)
    elements = []
    for i in range(0, len(dests), cfg.matrix_chunk):
        chunk = dests[i:i + cfg.matrix_chunk]
        res = await client.route_matrix_walking([center], chunk)
        elements.extend(res["elements"])
    boundaries = isochrone.boundary_by_rays(rays, elements, limit_s, cfg.step_m, cfg.max_radius_m)
    print("采样边界 max=%.0fm min=%.0fm" % (max(boundaries, key=lambda t: t[1])[1], min(boundaries, key=lambda t: t[1])[1]))
    boundaries = await isochrone.refine_boundaries(center[0], center[1], boundaries, client, limit_s, cfg.step_m,
                                                   cfg.max_radius_m, max_refines=cfg.review_directions)
    print("复核后边界 max=%.0fm min=%.0fm" % (max(boundaries, key=lambda t: t[1])[1], min(boundaries, key=lambda t: t[1])[1]))
    print("复核后边界分布: ", sorted(boundaries, key=lambda t: t[1])[:6])
    refined_map = {ang: bd for ang, bd in boundaries}
    adjusted = list(elements)
    idx = 0
    for ang, pts in rays:
        for (d, _lat, _lng) in pts:
            if ang in refined_map and d > refined_map[ang] and adjusted[idx] is not None:
                adjusted[idx] = dict(adjusted[idx])
                adjusted[idx]["duration"] = limit_s * 2.0
                adjusted[idx]["distance"] = int(d)
            idx += 1
    grid_min = isochrone.idw_minutes_grid(center[0], center[1], rays, adjusted, limit_s, cfg.max_radius_m, cfg.grid_n)
    n = cfg.grid_n
    reach = sum(1 for row in grid_min for v in row if v <= 15.0)
    print("网格<=15min格数=%d/%d=%.1f%%" % (reach, n * n, 100 * reach / (n * n)))
    polygons = isochrone.marching_squares(grid_min, limit_s / 60.0)
    print("marching_squares 多边形数量 =", len(polygons))
    for poly in polygons:
        geo = [
            (center[1] + (x / (n - 1) * 2 - 1) * cfg.max_radius_m / (111320 * math.cos(math.radians(center[0]))),
             center[0] + (1 - y / (n - 1) * 2) * cfg.max_radius_m / 110540)
            for (x, y) in poly
        ]
        a = isochrone._polygon_area_km2(center[0], geo)
        print("  多边形: 顶点数=%d 面积=%.4f km²" % (len(poly), a))


asyncio.run(main())

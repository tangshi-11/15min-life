import asyncio, sys, math
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.config import Settings
from app.api.baidu_client import BaiduClient
from app.api.rate_limiter import TokenBucket
from app.core.isochrone import compute_isochrone, build_rays, flat_destinations, boundary_by_rays, refine_boundaries
import httpx


async def main():
    cfg = Settings()
    async with httpx.AsyncClient(timeout=15) as s:
        c = BaiduClient(cfg.ak_server, s, direction_bucket=TokenBucket(1.2))
        center = (24.741355, 102.694037)
        limit_s = 900.0
        rays = build_rays(center[0], center[1], cfg.directions, cfg.step_m, cfg.max_radius_m)
        dests = flat_destinations(rays)
        elements = []
        for i in range(0, len(dests), cfg.matrix_chunk):
            r = await c.route_matrix_walking([(center[0], center[1])], dests[i:i + cfg.matrix_chunk])
            elements.extend(r["elements"])
        boundaries = boundary_by_rays(rays, elements, limit_s, cfg.step_m, cfg.max_radius_m)
        print("== boundary_by_rays 全部 ==", flush=True)
        for ang, bd in boundaries:
            print(f"  {ang}°: {bd:.0f}m", flush=True)
        out = await refine_boundaries(center[0], center[1], boundaries, c, limit_s, cfg.step_m, cfg.max_radius_m, max_refines=cfg.review_directions)
        print("== refine 后 全部 ==", flush=True)
        for ang, bd in out:
            print(f"  {ang}°: {bd:.0f}m", flush=True)


asyncio.run(main())

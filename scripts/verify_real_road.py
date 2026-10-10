# -*- coding: utf-8 -*-
"""验证"等时圈基于真实路网而非直线距离"：
1. 跑体检取 48 方向边界点
2. 统计边界点距中心的直线距离分布（若为直线圆，应近似相等）
3. 抽样 5 个边界点调百度单点步行算路(directionlite)，对比真实耗时 vs 直线耗时(按1.2m/s)
"""
import math, os, time, json, urllib.parse, urllib.request

AK = None
env = {}
for line in open(os.path.join(os.path.dirname(__file__), "..", ".env"), encoding="utf-8"):
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
AK = env.get("BAIDU_AK_SERVER")
assert AK, "未找到 BAIDU_AK_SERVER"

BASE = "http://127.0.0.1:8000"

def haversine_m(lng1, lat1, lng2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2 * R * math.asin(math.sqrt(a))

def wgs84_to_bd09(lng, lat):  # 保留备用（不再用于 boundary_polygon，其已是 BD-09）
    X_PI = math.pi * 3000.0 / 180.0
    z = math.sqrt(lng*lng + lat*lat) + 0.00002 * math.sin(lat * X_PI)
    theta = math.atan2(lat, lng) + 0.000003 * math.cos(lng * X_PI)
    return z*math.cos(theta) + 0.0065, z*math.sin(theta) + 0.006

def directionlite(o_lat, o_lng, d_lat, d_lng):
    url = "https://api.map.baidu.com/directionlite/v1/walking"
    params = "origin=%f,%f&destination=%f,%f&ak=%s&coord_type=bd09ll" % (o_lat, o_lng, d_lat, d_lng, AK)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url + "?" + params, timeout=15) as resp:
                r = json.loads(resp.read().decode("utf-8"))
            if r.get("status") == 0 and r.get("result", {}).get("routes"):
                rt = r["result"]["routes"][0]
                return rt.get("distance", 0), rt.get("duration", 0)
            time.sleep(1.5)
        except Exception:
            time.sleep(1.5)
    return None, None

print("== 1) 跑真实体检，取 48 方向边界点 ==")
t0 = time.time()
body = json.dumps({"center": {"lat": 25.0406, "lng": 102.7146}, "walk_minutes": 15}).encode("utf-8")
req = urllib.request.Request(BASE + "/api/inspect", data=body, headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as resp:
    r = json.loads(resp.read().decode("utf-8"))
print("mode=%s score=%s max_reach=%s area=%s elapsed=%dms" % (
    r["mode"], r["coverage"]["overall"], r["isochrone"]["stats"]["max_reach_m"],
    r["isochrone"]["stats"]["area_km2"], r["elapsed_ms"]))
bp = r["isochrone"]["boundary_polygon"]  # [[lng, lat], ...] —— 后端输出即为 BD-09
clat, clng = r["center"]["lat"], r["center"]["lng"]  # BD-09
print("boundary_points=%d" % len(bp))

print("\n== 2) 边界点直线距离分布（若为直线圆应≈相等）==")
dists = []
for lng, lat in bp:
    dists.append(haversine_m(lng, lat, clng, clat))
dists.sort()
n = len(dists)
print("min=%.0fm  p25=%.0fm  median=%.0fm  p75=%.0fm  max=%.0fm  std=%.0fm" % (
    dists[0], dists[int(n*0.25)], dists[n//2], dists[int(n*0.75)], dists[-1],
    (sum((d - sum(dists)/n)**2 for d in dists)/n) ** 0.5))
print("极差(最远-最近)=%.0fm —— 若直线圆应≈0m" % (dists[-1] - dists[0]))

print("\n== 3) 抽样 5 个边界点：直线耗时(1.2m/s) vs 百度单点算路真实耗时 ==")
# 按角度均匀抽 5 个边界点
angles = []
for lng, lat in bp:
    ang = math.degrees(math.atan2(lng - clng, lat - clat)) % 360
    angles.append((ang, lng, lat))
angles.sort()
idxs = [int(i * n / 5) for i in range(5)]
results = []
for i in idxs:
    ang, lng, lat = angles[i]
    d = haversine_m(lng, lat, clng, clat)
    straight_s = d / 1.2  # 直线步行耗时
    rd, rt = directionlite(clat, clng, lat, lng)
    time.sleep(1.0)
    results.append((ang, d, straight_s, rd, rt))
    if rd:
        print("方位角%6.1f° | 直线%.0fm→直线耗时%.0fs | 真实路径%.0fm→真实耗时%.0fs(%.1f分) | 直线/真实差异%+.1f分" % (
            ang, d, straight_s, rd, rt, rt/60.0, (rt - straight_s)/60.0))
    else:
        print("方位角%6.1f° | 直线%.0fm | 单点算路失败" % (ang, d))

print("\n== 4) 结论 ==")
if results and all(x[4] for x in results):
    diffs = [(rt - straight_s) / 60.0 for _, _, straight_s, _, rt in results]
    avg = sum(diffs) / len(diffs)
    print("5 个边界点 真实耗时-直线耗时 平均差 %+.1f 分钟；若系统按直线圆计算，边界点耗时应≈15分钟且各点一致。" % avg)
    near = sum(1 for _, _, s, _, t in results if abs(t - 900) <= 75)
    print("%d/5 个边界点真实耗时落在 13.75~16.25 分钟区间（接近 15 分钟等时线）" % near)

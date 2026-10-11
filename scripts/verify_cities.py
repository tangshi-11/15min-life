# -*- coding: utf-8 -*-
"""全国多城市真实路网实测验证：
对多个城市的市中心地标分别跑一次真实体检（等时圈+盲区+报告），
验证"真实路网等时圈 / 服务盲区识别"在全国范围内均可用且形状非直线圆。

用法（需主服务在 127.0.0.1:8000 且 BAIDU_AK_SERVER 已配置）：
    python scripts/verify_cities.py   （或在 backend 虚拟环境内运行）
"""
import json
import math
import time
import urllib.request

BASE = "http://127.0.0.1:8000"

# 代表城市（华北/华东/华南/西南）+ 市中心地标（交给后端正地理编码，无需手写坐标）
CITIES = [
    ("北京", "天安门广场"),
    ("上海", "人民广场"),
    ("广州", "花城广场"),
    ("成都", "天府广场"),
]


def haversine_m(lng1, lat1, lng2, lat2):
    R = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def inspect(address, city):
    body = json.dumps({"address": address, "city": city, "walk_minutes": 15}).encode("utf-8")
    req = urllib.request.Request(BASE + "/api/inspect", data=body,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=240) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    print("== 全国多城市真实路网实测 ==")
    print("城市      | 模式 | 评分 | 面积km² | 最远可达m | 边界极差m | POI总数 | 盲区数 | 耗时s")
    for city, landmark in CITIES:
        try:
            r = inspect(f"{city}{landmark}", city)
            iso = r.get("isochrone", {})
            stats = iso.get("stats", {})
            bp = iso.get("boundary_polygon", [])
            clat, clng = r["center"]["lat"], r["center"]["lng"]
            dists = sorted(haversine_m(lng, lat, clng, clat) for lng, lat in bp)
            spread = (dists[-1] - dists[0]) if dists else 0.0
            # 盲区/POI 字段（见 main.py inspect 响应结构）
            blinds = r.get("blind_spots", {})
            cluster = blinds.get("cluster_count", 0) if isinstance(blinds, dict) else 0
            pois = len(r.get("pois", []))
            print("%-9s | %-4s | %3s | %6.2f | %7.0f | %7.0f | %6d | %4d | %5.1f" % (
                city, r.get("mode", "?"), r.get("coverage", {}).get("overall", "?"),
                stats.get("area_km2", 0), stats.get("max_reach_m", 0), spread,
                pois, cluster, r.get("elapsed_ms", 0) / 1000.0))
        except Exception as exc:
            print("%-9s | 失败: %s" % (city, str(exc)[:120]))
        time.sleep(3.0)

    print("\n说明：极差 = 边界点直线距离最远-最近；若等时圈是直线圆，极差应≈0m；越大越说明形状由真实路网决定。")


if __name__ == "__main__":
    main()

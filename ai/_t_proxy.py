import json, time, urllib.request
data = {
  "center": {"lat": 25.0547, "lng": 102.7102, "address": "云南省昆明市五华区华山街道听莺桥"},
  "coverage": {"overall": 80, "scores": {"医疗": 100, "教育": 100, "购物": 100, "养老": 0, "文体": 100, "餐饮": 100},
               "counts": {"医疗": 26, "购物": 20, "餐饮": 18, "教育": 10, "交通": 9, "文体": 2},
               "in_polygon_pois": 240},
  "isochrone": {"stats": {"area_km2": 1.8391, "max_reach_m": 865}},
  "blind_spots": {"cluster_count": 1, "blind_cells": [{"i":0}], "summary": "检测到 1 处服务盲区（灰色区域），共 1 个网格单元，缺失设施：菜市场。"}
}
req = urllib.request.Request("http://127.0.0.1:8000/api/ai/interpret",
    data=json.dumps({"data": data}).encode("utf-8"), headers={"Content-Type": "application/json"})
t0 = time.time()
try:
    with urllib.request.urlopen(req, timeout=120) as r:
        res = json.loads(r.read().decode("utf-8"))
    print("MAIN->AI OK", round(time.time()-t0,1), "s")
    print(res.get("interpretation", "")[:300])
except urllib.error.HTTPError as e:
    print("HTTP", e.code, e.read().decode("utf-8")[:300])

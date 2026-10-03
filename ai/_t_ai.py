import json, time, urllib.request
body = {
  "instruction": "你是一名城市规划与社区生活评估专家。下面是一份“15分钟生活圈”社区体检的结构化数据（JSON）：包含综合评分、六类民生设施分项评分与数量、等时圈面积、最远可达距离、服务盲区信息。请生成一段约150-220字的中文体检解读，要求：① 先总评该社区的15分钟生活便利程度；② 指出表现最好的1-2个设施类别和短板；③ 针对服务盲区与短板给出1-2条可落地的改善/选址建议；④ 语言专业、客观、口语自然，不要罗列所有数字，挑关键数字说。",
  "input": json.dumps({
    "name": "云南省昆明市五华区华山街道听莺桥", "overall": 80,
    "scores": {"医疗": 100, "教育": 100, "购物": 100, "养老": 0, "文体": 100, "餐饮": 100},
    "counts": {"医疗": 26, "购物": 20, "餐饮": 18, "教育": 10, "交通": 9, "文体": 2},
    "in_polygon_pois": 240, "area_km2": 1.8391, "max_reach_m": 865,
    "cluster_count": 1, "blind_cells": 1, "missing": ["菜市场"]
  }, ensure_ascii=False)
}
req = urllib.request.Request("http://127.0.0.1:8010/api/ai/interpret",
    data=json.dumps(body).encode("utf-8"), headers={"Content-Type": "application/json"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=240) as r:
    res = json.loads(r.read().decode("utf-8"))
print("ELAPSED_s=", round(time.time()-t0, 1))
print("----解读----")
print(res.get("interpretation", "NO OUTPUT"))

import io
import json

p = r"E:\上海\15min-life-circle\data\tmp_waterbodies\package\map.geo.json"
with io.open(p, "r", encoding="utf-8") as f:
    data = json.load(f)
print("type=", data.get("type"))
gs = data.get("geometries", [])
print("geometries=", len(gs))
for i, g in enumerate(gs[:5]):
    print(i, "type=", g.get("type"), "ncoords=", len(g.get("coordinates") or []))
    coords = g.get("coordinates") or []
    if coords:
        poly = coords[0]
        # 找第一个真正的坐标环
        ring = None
        if poly and isinstance(poly[0], list) and poly[0] and isinstance(poly[0][0], list):
            ring = poly[0]
        if ring:
            xs = [pt[0] for pt in ring]
            ys = [pt[1] for pt in ring]
            print("   first ring len=", len(ring), "bbox=", min(xs), min(ys), max(xs), max(ys))
            print("   head3=", ring[:3])

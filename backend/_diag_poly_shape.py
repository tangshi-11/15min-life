import json, math, sys
sys.path.insert(0, r"E:\上海\15min-life-circle\backend")
from app.core.water_guard import point_in_polygon, point_edge_distance_m


def dist_deg(lng1, lng2, lat=24.74):
    return (lng1 - lng2) * 111320.0 * math.cos(math.radians(lat))


def dist_deg_y(lat1, lat2):
    return (lat1 - lat2) * 110540.0


DATA = r"E:\上海\15min-life-circle\data\water_polygons.json"
CENTER = (24.741355, 102.694037)  # (lat, lng)

data = json.load(open(DATA, encoding="utf-8"))
polys = data["polys"]
found = []
for i, poly in enumerate(polys):
    if point_in_polygon(CENTER[1], CENTER[0], poly):
        found.append((i, poly))
print(f"覆盖中心点的 polygon 数: {len(found)}")
for i, poly in found[:5]:
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    bbox = (min(xs), min(ys), max(xs), max(ys))
    d = point_edge_distance_m(CENTER[1], CENTER[0], poly)
    print(f"idx={i} n={len(poly)} bbox_lng={bbox[0]:.4f}..{bbox[2]:.4f} lat={bbox[1]:.4f}..{bbox[3]:.4f} 中心点距边界={d:.0f}m")
    print(f"   西边界={bbox[0]:.4f}(中心点西{dist_deg(bbox[0], CENTER[1]):.0f}m) 北边界={bbox[3]:.4f}(北{dist_deg_y(bbox[3], CENTER[0]):.0f}m)")

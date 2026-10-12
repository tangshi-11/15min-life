"""从 geo-maps waterbodies 全球数据中裁剪中国区域水体，转 BD-09。

输出：data/water_polygons.json
格式：
{
  "source": "@geo-maps/earth-waterbodies-100m (OpenStreetMap data, ODbL)",
  "polys": [[[lng_bd09, lat_bd09], ...], ...],
  "bboxes": [[min_lng, min_lat, max_lng, max_lat], ...]  # 与 polys 一一对应（BD-09）
}

过滤口径：与中国 bbox 相交、水体对角线 3km–~200km（剔除全球海洋轮廓）、
外环点数 > 6。运行时仲裁采用"环 bbox 粗筛 + 射线法"直接遍历（数千个环，
每点判断 < 1ms），无需网格索引。
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from app.core.water_guard import wgs84_to_bd09

CN_BBOX = (73.0, 18.0, 135.0, 54.0)
MIN_DIAG_KM = 3.0
MAX_BBOX_AREA_DEG2 = 4.0  # bbox 面积上限（平方度），剔除海洋/全球环


def bbox_of_rings(rings):
    minx, miny, maxx, maxy = 1e9, 1e9, -1e9, -1e9
    for r in rings:
        for x, y in r:
            if x < minx:
                minx = x
            if y < miny:
                miny = y
            if x > maxx:
                maxx = x
            if y > maxy:
                maxy = y
    return minx, miny, maxx, maxy


def intersects(bx, cbox):
    return not (bx[2] < cbox[0] or bx[0] > cbox[2] or bx[3] < cbox[1] or bx[1] > cbox[3])


def diag_km(bx):
    mid_lat = math.radians((bx[1] + bx[3]) / 2.0)
    return max((bx[2] - bx[0]) * 111.0 * math.cos(mid_lat), (bx[3] - bx[1]) * 111.0)


def main(geojson_path: str, out_path: str):
    data = json.loads(Path(geojson_path).read_text(encoding="utf-8"))
    features = data.get("geometries", [])
    print(f"geometries={len(features)}", flush=True)
    polys_bd09 = []
    bboxes = []
    kept = 0
    for f in features:
        g = f if f.get("type") else (f.get("geometry") or {})
        gtype = g.get("type")
        coords = g.get("coordinates")
        if not coords:
            continue
        rings = []
        if gtype == "Polygon":
            rings = [coords[0]]
        elif gtype == "MultiPolygon":
            rings = [p[0] for p in coords]
        else:
            continue
        gbx = bbox_of_rings(rings)
        if not intersects(gbx, CN_BBOX):
            continue
        for r in rings:
            if len(r) < 6:
                continue
            rb = bbox_of_rings([r])
            if not intersects(rb, CN_BBOX):
                continue
            dk = diag_km(rb)
            if dk < MIN_DIAG_KM:
                continue
            area = (rb[2] - rb[0]) * (rb[3] - rb[1])
            if area > MAX_BBOX_AREA_DEG2:
                continue  # 剔除海洋/超大型全球轮廓环
            r_bd = [wgs84_to_bd09(float(x), float(y)) for x, y in r]
            cleaned = []
            for p in r_bd:
                if not cleaned or abs(p[0] - cleaned[-1][0]) > 1e-9 or abs(p[1] - cleaned[-1][1]) > 1e-9:
                    cleaned.append(p)
            if len(cleaned) >= 3 and abs(cleaned[0][0] - cleaned[-1][0]) < 1e-6 and abs(cleaned[0][1] - cleaned[-1][1]) < 1e-6:
                cleaned = cleaned[:-1]
            if len(cleaned) >= 3:
                cb = bbox_of_rings([cleaned])
                polys_bd09.append(cleaned)
                bboxes.append([round(cb[0], 5), round(cb[1], 5), round(cb[2], 5), round(cb[3], 5)])
                kept += 1
    print(f"kept_polys={kept}", flush=True)
    out = {
        "source": "@geo-maps/earth-waterbodies-100m (OpenStreetMap contributors, ODbL 1.0)",
        "polys": polys_bd09,
        "bboxes": bboxes,
    }
    Path(out_path).write_text(json.dumps(out), encoding="utf-8")
    print(f"written {out_path} size={Path(out_path).stat().st_size / 1024 / 1024:.2f}MB", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])

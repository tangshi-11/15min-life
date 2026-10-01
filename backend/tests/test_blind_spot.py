"""盲区识别单元测试：构造已知盲区（东北象限无关键设施）验证识别结果。"""
import math

from app.api.mock import _mock_pois
from app.core.blind_spot import detect_blind_spots
from app.core.coords import offset_lnglat

CENTER = (25.0406, 102.7146)


def _make_pois_with_hole():
    """仅在西南半区(135°~315°)生成关键设施，东北象限留空 → 应识别出东北盲区。"""
    pois = []
    cats = ["菜市场", "药店", "小学", "医院", "超市"]
    for cat in cats:
        for k in range(40):
            ang = (135 + (k * 47) % 180)
            dist = 200 + (k * 173) % 600
            lng, lat = offset_lnglat(CENTER[1], CENTER[0],
                                     dist * math.cos(math.radians(ang)),
                                     dist * math.sin(math.radians(ang)))
            pois.append({"category": cat, "lng": round(lng, 6), "lat": round(lat, 6)})
    return pois


def test_detect_blind_spot_in_northeast():
    pois = _make_pois_with_hole()
    result = detect_blind_spots(CENTER[0], CENTER[1], pois, radius_m=1000, cell_m=200)
    assert result["cluster_count"] >= 1
    assert len(result["polygons"]) >= 1
    # 盲区应位于中心东北方向
    poly = result["polygons"][0]
    poly_lngs = [p[0] for p in poly]
    poly_lats = [p[1] for p in poly]
    assert (sum(poly_lngs) / len(poly_lngs)) > CENTER[1]
    assert (sum(poly_lats) / len(poly_lats)) > CENTER[0]


def test_no_blind_spot_when_covered():
    """三类关键设施在 500m 网格上全覆盖 → 不应出现盲区。"""
    pois = []
    for cat in ["菜市场", "药店", "小学"]:
        for dx in range(-900, 1000, 500):
            for dy in range(-900, 1000, 500):
                lng, lat = offset_lnglat(CENTER[1], CENTER[0], dx, dy)
                pois.append({"category": cat, "lng": round(lng, 6), "lat": round(lat, 6)})
    result = detect_blind_spots(CENTER[0], CENTER[1], pois, radius_m=1000, cell_m=200)
    assert result["cluster_count"] == 0
    assert result["polygons"] == []


def test_mock_pois_cover_all_required():
    """演示数据本身应包含三类关键设施。"""
    pois = _mock_pois(CENTER, 2500, "", 42)
    cats = {p["category"] for p in pois}
    assert {"菜市场", "药店", "小学"} <= cats

"""POI 清洗单元测试。"""
from app.core.poi_cleaner import _infer_category, clean_pois

CENTER = (25.0406, 102.7146)


def _raw(name, lng, lat, tag="", report=None):
    p = {"name": name, "location": {"lng": lng, "lat": lat}, "tag": tag}
    if report:
        p["_report_category"] = report
    return p


def test_dedupe_by_name_and_coords():
    raw = [
        _raw("菜市场1", 102.72, 25.05),
        _raw("菜市场1", 102.72, 25.05),  # 完全重复
        _raw("菜市场1", 102.720001, 25.050001),  # 坐标近似(5位小数相同) → 去重
        _raw("菜市场2", 102.72, 25.05),  # 名称不同 → 保留
    ]
    cleaned = clean_pois(raw, CENTER[0], CENTER[1], 5000)
    assert len(cleaned) == 2


def test_filter_invalid_and_out_of_radius():
    raw = [
        _raw("远点", 106.0, 26.0),  # 超出半径
        {"name": "无坐标", "location": {}},
        {"name": "非法坐标", "location": {"lng": "abc", "lat": 25.0}},
    ]
    cleaned = clean_pois(raw, CENTER[0], CENTER[1], 5000)
    assert cleaned == []


def test_report_category_override():
    raw = [_raw("任意名称", 102.72, 25.05, report="教育")]
    cleaned = clean_pois(raw, CENTER[0], CENTER[1], 5000)
    assert cleaned[0]["category"] == "教育"


def test_infer_category_by_keyword():
    assert _infer_category({"name": "某某大药房"}) == "医疗"
    assert _infer_category({"name": "幸福养老院"}) == "养老"
    assert _infer_category({"name": "社区公园"}) == "文体"


def test_infer_transit_category():
    assert _infer_category({"name": "翠湖公交站"}) == "交通"
    assert _infer_category({"name": "五一路地铁站"}) == "交通"


def test_report_category_transit_override():
    raw = [_raw("任意站点", 102.72, 25.05, report="交通")]
    cleaned = clean_pois(raw, CENTER[0], CENTER[1], 5000)
    assert cleaned[0]["category"] == "交通"
    assert cleaned[0]["search_key"] == ""

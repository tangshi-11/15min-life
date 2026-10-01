"""POI 清洗：去重、异常过滤、民生类别映射（命中 40% 功能正确性）。"""
from typing import Optional

from .coords import haversine_m

# 检索分类 → 民生类别
REPORT_CATEGORY = {
    "菜市场": "购物", "超市": "购物", "商场": "购物",
    "药店": "医疗", "医院": "医疗", "诊所": "医疗", "社区卫生": "医疗",
    "小学": "教育", "中学": "教育", "幼儿园": "教育",
    "养老院": "养老", "社区服务中心": "养老",
    "公园": "文体", "图书馆": "文体", "健身": "文体",
    "餐厅": "餐饮", "快餐": "餐饮", "咖啡": "餐饮", "奶茶": "餐饮",
    "公交站": "交通", "地铁站": "交通",
}

# 关键词兜底：从 POI 名称/标签推断民生类别（应对多源数据口径不一致）
KEYWORD_FALLBACK = [
    (["医院", "卫生院", "诊所", "药房", "药店", "社区卫生"], "医疗"),
    (["小学", "中学", "幼儿园", "学校", "学院", "大学"], "教育"),
    (["菜市场", "农贸", "超市", "便利店", "商场", "购物"], "购物"),
    (["养老", "敬老", "社区服务中心", "照料"], "养老"),
    (["公园", "广场", "图书馆", "体育馆", "健身", "影城"], "文体"),
    (["餐厅", "饭店", "美食", "小吃", "快餐", "咖啡", "奶茶", "面馆", "烧烤"], "餐饮"),
    (["公交", "地铁", "车站", "轻轨", "枢纽"], "交通"),
]


def clean_pois(
    raw_pois: list[dict],
    center_lat: float,
    center_lng: float,
    radius_m: float,
    report_category: Optional[str] = None,
) -> list[dict]:
    """去重(名称+坐标)、过滤异常点(坐标非法/超出半径)、推断民生类别。"""
    seen: set[tuple[str, str]] = set()
    cleaned: list[dict] = []
    for p in raw_pois:
        loc = p.get("location") or {}
        lng, lat = loc.get("lng"), loc.get("lat")
        if lng is None or lat is None:
            continue
        try:
            lng, lat = float(lng), float(lat)
        except (TypeError, ValueError):
            continue
        if not (-180 <= lng <= 180 and -90 <= lat <= 90):
            continue
        if haversine_m(center_lng, center_lat, lng, lat) > radius_m * 1.05:
            continue
        name = str(p.get("name", "")).strip()
        key = (name, f"{lng:.5f},{lat:.5f}")
        if key in seen:
            continue
        seen.add(key)
        cat = p.get("_report_category") or report_category or _infer_category(p)
        cleaned.append({
            "name": name or "未命名",
            "lng": round(lng, 6),
            "lat": round(lat, 6),
            "tag": str(p.get("tag", "")),
            "category": cat,
            "search_key": str(p.get("_search_key", "")),  # 原始检索类别（菜市场/药店/小学…）
        })
    return cleaned


def _infer_category(p: dict) -> str:
    text = f"{p.get('name', '')} {p.get('tag', '')} {p.get('category', '')}"
    for kws, cat in KEYWORD_FALLBACK:
        if any(k in text for k in kws):
            return cat
    return "其他"

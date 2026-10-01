"""体检报告：等时圈内设施覆盖率统计、分项评分与综合评分（命中 15% 可视化数据）。"""

# 每类民生设施在等时圈内的建议覆盖阈值（至少应达到的数量）
SCORE_THRESHOLDS = {"医疗": 2, "教育": 1, "购物": 3, "养老": 1, "文体": 1, "餐饮": 5}
SCORE_WEIGHTS = {"医疗": 0.25, "教育": 0.20, "购物": 0.20, "养老": 0.15, "文体": 0.10, "餐饮": 0.10}


def point_in_polygon(lng: float, lat: float, polygon: list[list[float]]) -> bool:
    """射线法判断点是否在多边形内。polygon: [[lng, lat], ...]"""
    n = len(polygon)
    if n < 3:
        return False
    inside = False
    x, y = lng, lat
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            x_cross = x1 + (y - y1) * (x2 - x1) / (y2 - y1)
            if x < x_cross:
                inside = not inside
    return inside


def build_report(center: dict, isochrone: dict, pois: list[dict], blind: dict, walk_minutes: int | None = None) -> dict:
    """生成体检报告：覆盖统计、分项得分、综合得分（盲区扣分）。"""
    polygon = isochrone["polygon"] or isochrone["boundary_polygon"]
    counts: dict[str, int] = {}
    in_polygon_total = 0
    for p in pois:
        cat = p.get("category", "其他")
        if point_in_polygon(p["lng"], p["lat"], polygon):
            in_polygon_total += 1
            if cat == "其他":
                continue
            counts[cat] = counts.get(cat, 0) + 1

    scores: dict[str, int] = {}
    for cat, thr in SCORE_THRESHOLDS.items():
        n = counts.get(cat, 0)
        scores[cat] = min(100, round(n / thr * 100)) if thr else 100

    total_w = sum(SCORE_WEIGHTS.values())
    overall = round(sum(scores[c] * SCORE_WEIGHTS.get(c, 0) for c in scores) / total_w)
    blind_penalty = min(20, 5 * int(blind.get("cluster_count", 0)))
    overall = max(0, overall - blind_penalty)

    return {
        "counts": dict(sorted(counts.items(), key=lambda kv: -kv[1])),
        "scores": scores,
        "overall": overall,
        "blind_penalty": blind_penalty,
        "in_polygon_pois": in_polygon_total,
        "blind_summary": blind.get("summary", ""),
        "categories": list(SCORE_THRESHOLDS.keys()),
    }

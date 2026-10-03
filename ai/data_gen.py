"""生成训练数据集：社区体检结构化结果 -> 自然语言解读+选址建议。

用项目自身的 Mock 引擎在多个真实城市坐标上跑完整体检（确定性、快、不耗配额），
把结构化体检结果转成 (instruction, input, output) 三元组，供 Qwen2.5 指令微调。

用法（在项目 backend venv 或任意可导入 app 包的 Python 中）:
    python ai/data_gen.py
输出:
    ai/data/train.json        (LLaMA-Factory alpaca 格式，全部样本)
    ai/data/dev.json          (验证集，从 train 中按比例抽取)
"""
import asyncio
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # E:\上海\15min-life-circle
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.api.mock import MockBaiduClient
from app.config import settings
from app.core import blind_spot, isochrone, poi_cleaner
from app.core import report as report_mod
from app.main import SEARCH_CATEGORIES

random.seed(42)

# 覆盖 20 个城市、40 个真实中心点（WGS84 近似即可，Mock 对坐标不敏感）
CENTERS = [
    # 昆明
    ("昆明翠湖公园", 25.0547, 102.7102), ("昆明呈贡大学城", 24.8667, 102.8486),
    ("昆明巫家坝", 24.9890, 102.7450), ("昆明白塔路", 25.0330, 102.7240),
    # 上海
    ("上海陆家嘴", 31.2397, 121.4998), ("上海五角场", 31.3000, 121.5150),
    ("上海徐家汇", 31.1950, 121.4370), ("上海虹桥枢纽", 31.1960, 121.3250),
    # 北京
    ("北京中关村", 39.9830, 116.3160), ("北京望京", 39.9970, 116.4730),
    ("北京国贸", 39.9090, 116.4600), ("北京五道口", 39.9920, 116.3370),
    # 广州 / 深圳
    ("广州珠江新城", 23.1200, 113.3220), ("广州天河城", 23.1320, 113.3300),
    ("深圳科技园", 22.5400, 113.9400), ("深圳福田中心区", 22.5350, 114.0550),
    # 成都 / 重庆
    ("成都春熙路", 30.6540, 104.0810), ("成都天府广场", 30.6580, 104.0660),
    ("重庆解放碑", 29.5570, 106.5760),
    # 杭州 / 南京 / 苏州
    ("杭州西湖", 30.2500, 120.1500), ("杭州未来科技城", 30.2790, 119.9980),
    ("南京新街口", 32.0410, 118.7850), ("苏州金鸡湖", 31.3140, 120.6950),
    # 武汉 / 西安 / 长沙
    ("武汉光谷广场", 30.5030, 114.4000), ("西安钟楼", 34.2610, 108.9420),
    ("长沙五一广场", 28.1960, 112.9790),
    # 其他城市
    ("天津和平区", 39.1170, 117.1900), ("青岛五四广场", 36.0620, 120.3830),
    ("郑州二七广场", 34.7500, 113.6650), ("合肥政务区", 31.8200, 117.2320),
    ("福州鼓楼", 26.0820, 119.2960), ("厦门思明", 24.4800, 118.0890),
    ("济南泉城广场", 36.6510, 117.0240), ("沈阳中街", 41.8030, 123.4560),
    ("大连星海广场", 38.8790, 121.5880), ("哈尔滨中央大街", 45.7800, 126.6120),
    ("兰州中心", 36.0600, 103.8300), ("贵阳喷水池", 26.5890, 106.7090),
    ("南宁朝阳广场", 22.8190, 108.3170), ("石家庄勒泰", 38.0430, 114.5140),
    # 第二批（扩充数据多样性）
    ("昆明海埂大坝", 24.9630, 102.6560), ("昆明世纪城", 24.9730, 102.7600),
    ("上海大宁", 31.2900, 121.4480), ("上海张江", 31.2050, 121.6060),
    ("北京西二旗", 40.0550, 116.3060), ("北京天通苑", 40.0770, 116.4150),
    ("广州琶洲", 23.1000, 113.3720), ("深圳龙华", 22.6600, 114.0300),
    ("成都高新区", 30.5600, 104.0660), ("杭州滨江", 30.2080, 120.2110),
    ("南京河西", 32.0230, 118.7180), ("武汉汉口", 30.6200, 114.2780),
    ("西安曲江", 34.2030, 108.9760), ("重庆观音桥", 29.5830, 106.5310),
    ("长沙梅溪湖", 28.1950, 112.8750), ("郑州郑东新区", 34.7700, 113.7350),
    ("青岛崂山", 36.1070, 120.4670), ("厦门集美", 24.5720, 118.1020),
    ("大连高新", 38.8560, 121.5240), ("福州闽侯", 26.0980, 119.1770),
]

INSTRUCTION = (
    "你是一名城市规划与社区生活评估专家。下面是一份“15分钟生活圈”社区体检的"
    "结构化数据（JSON）：包含综合评分、六类民生设施分项评分与数量、等时圈面积、"
    "最远可达距离、服务盲区信息。请生成一段约150-220字的中文体检解读，要求："
    "① 先总评该社区的15分钟生活便利程度；② 指出表现最好的1-2个设施类别和短板；"
    "③ 针对服务盲区与短板给出1-2条可落地的改善/选址建议；④ 语言专业、客观、口语自然，"
    "不要罗列所有数字，挑关键数字说。"
)


def _grade(score: int) -> tuple[str, str]:
    if score >= 90:
        return "优秀", "生活配套非常完善"
    if score >= 80:
        return "良好", "整体配套较完善"
    if score >= 70:
        return "一般", "配套基本够用但仍有短板"
    if score >= 60:
        return "偏弱", "配套存在明显不足"
    return "较差", "配套缺口较大"


def _missing_list(blind: dict, counts: dict) -> list[str]:
    """从盲区汇总与分类数量推断缺失设施。"""
    miss = []
    summary = blind.get("summary", "")
    if "缺失设施" in summary:
        part = summary.split("缺失设施：", 1)[1]
        miss = [x.strip() for x in part.replace("。", "").split("、") if x.strip()]
    return miss


def render_output(f: dict) -> str:
    """把结构化特征渲染为自然语言解读（模板+随机变体，保证训练数据多样性）。"""
    overall = f["overall"]
    grade, grade_desc = _grade(overall)
    best = sorted(f["scores"].items(), key=lambda kv: -kv[1])[:2]
    worst1 = min(f["scores"].items(), key=lambda kv: kv[1])  # 唯一最低分类，训练更聚焦
    best_txt = "、".join(f"{k}（{v}分）" for k, v in best)
    worst_name, worst_score = worst1
    if worst_score >= 100:
        worst_txt = "各项设施覆盖均衡，无明显短板"
    else:
        worst_txt = f"{worst_name}（{worst_score}分）"
    miss = f["missing"]
    blind_txt = (
        f"检测到 {f['cluster_count']} 处服务盲区、共 {f['blind_cells']} 个网格单元，"
        f"缺失设施：{'、'.join(miss) if miss else '无显著缺失'}"
    )
    miss_opt = "、".join(miss) if miss else "相应缺口设施"

    templates = [
        (
            "总体来看，该社区15分钟生活圈综合得分为{overall}分，评级为“{grade}”，{grade_desc}。"
            "其中{best_txt}表现突出，说明这部分日常需求步行可达性较好；最明显的短板是{worst_txt}，"
            "是需要优先关注的方面。{blind_txt}，等时圈覆盖面积约{area}平方公里，最远可达{reach}米。"
            "建议优先在盲区几何中心附近增设{miss_opt}，"
            "同时结合周边人口密度评估选址，可在不影响现有设施覆盖的前提下补齐短板，"
            "让更多居民在15分钟内满足日常需求。"
        ),
        (
            "该社区生活配套评级为“{grade}”（{overall}分），{grade_desc}。"
            "设施供给上，{best_txt}数量充足、分布较均匀；主要短板是{worst_txt}。"
            "{blind_txt}。整体15分钟步行可达面积约{area}平方公里，最远端点约{reach}米。"
            "建议下一步在盲区区域布点{miss_opt}，"
            "优先选择交通便利、辐射范围大的位置，并关注周边小区密度，最大化服务人群。"
        ),
        (
            "综合体检显示，该社区15分钟生活圈得分为{overall}分（{grade}）。"
            "亮点是{best_txt}，覆盖较好；相对薄弱的是{worst_txt}。"
            "{blind_txt}；等时圈面积{area}平方公里，最远可达{reach}米。"
            "从改善角度看，建议重点补齐{miss_opt}，"
            "选址时兼顾与现有设施的空间错位，避免重复覆盖，逐步消除服务盲区，提升整体便利度。"
        ),
        (
            "本社区15分钟步行生活圈综合评分{overall}，属于“{grade}”水平：{grade_desc}。"
            "各分类中{best_txt}得分最高，日常高频需求基本可满足；{worst_txt}得分偏低，"
            "与{blind_txt}相互印证，是主要短板。等时圈覆盖{area}平方公里，最远{reach}米。"
            "建议优先在盲区簇心选址新增{miss_opt}，"
            "并适当优化现有设施布局，用最小的增量补齐最大范围的缺口。"
        ),
    ]
    tpl = random.choice(templates)
    return tpl.format(
        overall=overall, grade=grade, grade_desc=grade_desc,
        best_txt=best_txt, worst_txt=worst_txt, blind_txt=blind_txt,
        area=f["area_km2"], reach=f["max_reach_m"], miss_opt=miss_opt,
    )


async def run_one(lat: float, lng: float, name: str, seed: int, walk_minutes: int = 15) -> dict:
    client = MockBaiduClient(seed=seed)
    center = {"lat": lat, "lng": lng}
    iso = await isochrone.compute_isochrone(lat, lng, client, settings, walk_minutes)
    radius = max(settings.poi_radius_m, settings.blind_radius_m * 2)
    raw: list[dict] = []
    for sc in SEARCH_CATEGORIES:
        items = await client.place_search(sc["query"], location=(lat, lng), radius=radius, tag=sc["key"])
        for it in items:
            it["_report_category"] = sc["report_category"]
            it["_search_key"] = sc["key"]
        raw.extend(items)
    cleaned = poi_cleaner.clean_pois(raw, lat, lng, radius)
    blind = blind_spot.detect_blind_spots(
        lat, lng, cleaned, radius_m=settings.blind_radius_m, cell_m=settings.blind_cell_m
    )
    rpt = report_mod.build_report(center, iso, cleaned, blind, walk_minutes)
    stats = iso["stats"]
    return {
        "name": name,
        "lat": lat, "lng": lng,
        "overall": rpt["overall"],
        "scores": rpt["scores"],
        "counts": rpt["counts"],
        "in_polygon_pois": rpt["in_polygon_pois"],
        "area_km2": stats["area_km2"],
        "max_reach_m": stats["max_reach_m"],
        "cluster_count": blind["cluster_count"],
        "blind_cells": len(blind["blind_cells"]),
        "missing": _missing_list(blind, rpt["counts"]),
    }


async def main():
    out_dir = ROOT / "ai" / "data"
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = []
    for i, (name, lat, lng) in enumerate(CENTERS, 1):
        try:
            # 不同中心点使用不同 seed：Mock 的 POI/测时分布随之变化，保证训练数据多样性
            f = await run_one(lat, lng, name, seed=42 + i)
        except Exception as exc:
            print(f"[skip] {name}: {exc}")
            continue
        inp = json.dumps(
            {k: f[k] for k in ("name", "overall", "scores", "counts", "in_polygon_pois",
                               "area_km2", "max_reach_m", "cluster_count", "blind_cells", "missing")},
            ensure_ascii=False, indent=1,
        )
        output = render_output(f)
        samples.append({"instruction": INSTRUCTION, "input": inp, "output": output})
        print(f"[{i}/{len(CENTERS)}] {name}: {f['overall']}分 盲区{f['cluster_count']}处 缺失{','.join(f['missing']) or '-'}")

    # 划分训练/验证（约 9:1），随机洗牌后按比例切
    random.shuffle(samples)
    n_dev = max(1, len(samples) // 9)
    dev, train = samples[:n_dev], samples[n_dev:]
    (out_dir / "train.json").write_text(
        json.dumps(train, ensure_ascii=False, indent=1), encoding="utf-8")
    (out_dir / "dev.json").write_text(
        json.dumps(dev, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n共 {len(samples)} 条：训练 {len(train)} 条，验证 {len(dev)} 条")
    print("输出样例：")
    print(json.dumps(samples[0], ensure_ascii=False, indent=1)[:800])


if __name__ == "__main__":
    asyncio.run(main())

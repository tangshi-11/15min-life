"""15分钟生活圈 · 智能体检与规划助手 — FastAPI 入口。

提供体检接口 /api/inspect，并托管前端静态资源。
AK 缺失或 API 异常时自动降级到演示数据（容错降级，命中 30% 工程优化）。
"""
import hashlib
import json
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .api.baidu_client import BaiduClient
from .api.mock import MockBaiduClient
from .api.rate_limiter import TokenBucket
from .config import settings
from .core import blind_spot, isochrone, poi_cleaner, result_cache
from .core import report as report_mod

logger = logging.getLogger(__name__)

# 检索分类配置：query → 民生类别
SEARCH_CATEGORIES = [
    {"key": "菜市场", "query": "菜市场", "report_category": "购物"},
    {"key": "药店", "query": "药店", "report_category": "医疗"},
    {"key": "小学", "query": "小学", "report_category": "教育"},
    {"key": "医院", "query": "医院", "report_category": "医疗"},
    {"key": "超市", "query": "超市", "report_category": "购物"},
    {"key": "公园", "query": "公园", "report_category": "文体"},
    {"key": "银行", "query": "银行", "report_category": "其他"},
    {"key": "养老院", "query": "养老院", "report_category": "养老"},
    {"key": "餐厅", "query": "美食", "report_category": "餐饮"},
    {"key": "公交站", "query": "公交站", "report_category": "交通"},
    {"key": "地铁站", "query": "地铁站", "report_category": "交通"},
]


class CenterIn(BaseModel):
    lat: float = Field(..., ge=-90, le=90)
    lng: float = Field(..., ge=-180, le=180)


class InspectRequest(BaseModel):
    center: CenterIn | None = None
    address: str | None = None
    city: str | None = None
    walk_minutes: int | None = Field(default=None, ge=5, le=60)
    radius_m: float | None = Field(default=None, ge=500, le=5000)


bucket = TokenBucket(settings.qps_limit)
# routematrix 并发配额极严（默认约 1-2 并发），独立慢桶防 401 并发超限
matrix_bucket = TokenBucket(1.0)
direction_bucket = TokenBucket(1.2)  # directionlite AK 级并发配额很紧（实测>1并发偶发401限流），可疑边界复核用更保守速率
http_session: httpx.AsyncClient | None = None

AI_SERVICE_URL = os.getenv("AI_SERVICE_URL", "http://127.0.0.1:8010")

# 与 ai/data_gen.py 保持一致的指令文本（保证训练/推理口径一致）
AI_INSTRUCTION = (
    "你是一名城市规划与社区生活评估专家。下面是一份“15分钟生活圈”社区体检的"
    "结构化数据（JSON）：包含综合评分、六类民生设施分项评分与数量、等时圈面积、"
    "最远可达距离、服务盲区信息。请生成一段约150-220字的中文体检解读，要求："
    "① 先总评该社区的15分钟生活便利程度；② 指出表现最好的1-2个设施类别和短板；"
    "③ 针对服务盲区与短板给出1-2条可落地的改善/选址建议；④ 语言专业、客观、口语自然，"
    "不要罗列所有数字，挑关键数字说。"
)


def _make_client():
    if settings.mock_mode:
        return MockBaiduClient(seed=settings.mock_seed)
    return BaiduClient(settings.ak_server, http_session, bucket=bucket, matrix_bucket=matrix_bucket, direction_bucket=direction_bucket)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global http_session
    http_session = httpx.AsyncClient(timeout=15)
    yield
    await http_session.aclose()


app = FastAPI(
    title="15分钟生活圈 · 智能体检与规划助手",
    version="1.0.0",
    lifespan=lifespan,
)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.get("/api/health")
async def health():
    return {"status": "ok", "mode": "mock" if settings.mock_mode else "live", "time": time.time()}


@app.get("/api/__probe2")
async def probe2_clamp():
    """离线验证：mock 全垃圾方向 + 真实 WaterGuard，确认服务进程内统一水域确认 clamp 生效。"""
    from .core import isochrone as _iso
    from .core.water_guard import WaterGuard

    class _AllJunk:
        async def walking_direction(self, origin, destination):
            return {"duration_s": 0, "distance_m": 1}

    wg = WaterGuard(
        http_session, radius_m=settings.water_guard_radius_m,
        overpass_url=settings.overpass_url,
        cache_path=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_cache.sqlite"),
        local_geojson=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_polygons.json"),
        margin_m=settings.water_guard_margin_m,
        enabled=True,
    )
    cl = _AllJunk()
    out = await _iso.refine_boundaries(24.741355, 102.694037, [(315.0, 971.0), (270.0, 1072.0)], cl, 900.0, 100.0, 2000.0, max_refines=10, water_guard=wg)
    return {"out": out}


@app.get("/api/__probe")
async def probe_code():
    import inspect as _inspect
    import math
    import app.core.isochrone as _iso
    import app.core.water_guard as _wg
    from .core.water_guard import WaterGuard
    src = _inspect.getsource(_iso)
    out = {
        "isochrone_file": _iso.__file__,
        "has_unified_clamp": "统一水域确认" in src,
        "has_ratio_11": ">= 1.1" in src,
        "has_log_probe": "水域确认 方向" in src,
        "water_guard_file": _wg.__file__,
    }
    try:
        wg = WaterGuard(
            http_session, radius_m=settings.water_guard_radius_m,
            overpass_url=settings.overpass_url,
            cache_path=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_cache.sqlite"),
            local_geojson=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_polygons.json"),
            margin_m=settings.water_guard_margin_m,
            enabled=True,
        )
        out["local_polys"] = len(wg._local_polys)
        out["local_bboxes"] = len(wg._local_bboxes)
        blng, blat = _iso.offset_lnglat(102.694037, 24.741355, 971.0 * math.sin(math.radians(315)), 971.0 * math.cos(math.radians(315)))
        out["is_water_315_971"] = await wg.is_water((24.741355, 102.694037), (blat, blng))
    except Exception as exc:
        out["probe_wg_err"] = repr(exc)[:200]
    return out


@app.get("/api/config")
async def config():
    return {
        "mode": "mock" if settings.mock_mode else "live",
        "walk_minutes": settings.walking_minutes,
        "qps_limit": settings.qps_limit,
        "has_ak": bool(settings.ak_server),
        "grid_n": settings.grid_n,
        "categories": [{"key": c["key"], "report_category": c["report_category"]} for c in SEARCH_CATEGORIES],
    }


@app.post("/api/inspect")
async def inspect(req: InspectRequest):
    t0 = time.time()
    if req.center is None and not req.address:
        raise HTTPException(status_code=400, detail="请提供 center 坐标或 address 地址")
    client = _make_client()
    # 水域仲裁（仅 live 模式）：百度算路对水域/未建模绿道同返 0s/1m 垃圾，
    # 用水体多边形区分"湖面(该内缩)"与"绿道(该保留)"；优先本地数据（随项目
    # 分发，无网络依赖），Overpass 仅作网络兜底。mock 模式不启用。
    water_guard = None
    if not settings.mock_mode and settings.water_guard_enabled:
        from .core.water_guard import WaterGuard
        water_guard = WaterGuard(
            http_session, radius_m=settings.water_guard_radius_m,
            overpass_url=settings.overpass_url,
            cache_path=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_cache.sqlite"),
            local_geojson=str(Path(__file__).resolve().parent.parent.parent / "data" / "water_polygons.json"),
            margin_m=settings.water_guard_margin_m,
            enabled=True,
        )
    warnings: list[str] = []
    mode = "mock" if settings.mock_mode else "live"

    # 1) 中心点解析
    center: dict | None = None
    address_label = req.address or "自定义坐标"
    if req.center:
        center = {"lat": req.center.lat, "lng": req.center.lng}
    else:
        try:
            gc = await client.geocode(req.address, req.city)
            center = {"lat": gc["lat"], "lng": gc["lng"]}
            address_label = f"{req.address}（{gc.get('level', '')}）"
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"地理编码失败：{exc}") from exc
    if center is None:
        raise HTTPException(status_code=500, detail="中心点解析失败")

    # 1.5) 中心点合法性：位于开阔水面（距岸边超过 margin）则拒绝。
    # 纯本地水体多边形判断（不消耗百度算路配额），避免"中心点定到水上 →
    # 等时圈从水上扩散覆盖湖面"。
    if water_guard is not None:
        try:
            if await water_guard.is_water((center["lat"], center["lng"]), (center["lat"], center["lng"])):
                raise HTTPException(
                    status_code=400,
                    detail="中心点位于开阔水面（距岸边超过300m），请选择陆地位置",
                )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("中心点水域检查失败，忽略：%s", exc)

    # 2) 逆地理编码（地址标签 + 所在街道/区县）
    admin = {"district": "", "town": "", "boundary": []}
    try:
        rgc = await client.reverse_geocode(center["lat"], center["lng"])
        address_label = rgc.get("address") or address_label
        admin["district"] = rgc.get("district", "")
        admin["town"] = rgc.get("town", "")
        admin["boundary"] = _community_boundary(center["lat"], center["lng"], settings.mock_seed)
    except Exception as exc:
        warnings.append(f"逆地理编码失败({exc})，已使用输入地址")

    # 2.5) 结果缓存：仅 live 模式 + 直接给定坐标 + 中心点落在居民区内时启用
    #      居民区判定：半径 200m 内小区类 POI 检索（一次轻量请求）；检索失败或非居民区 → 不查不写。
    cache_key = None
    allow_cache = False
    if not settings.mock_mode and req.center:
        cache_key = result_cache.make_key(req.center.lat, req.center.lng)
        try:
            nearby = await client.place_search(
                "小区", location=(center["lat"], center["lng"]), radius=200, page_size=10, max_pages=1
            )
            allow_cache = bool(nearby)
        except Exception:
            allow_cache = False
        if allow_cache:
            cached = result_cache.get(cache_key)
            if cached is not None:
                cached["cached"] = True
                cached["elapsed_ms"] = round((time.time() - t0) * 1000)
                return cached

    walk_minutes = req.walk_minutes or settings.walking_minutes
    radius_m = req.radius_m or max(settings.poi_radius_m, settings.blind_radius_m * 2)

    # 3) 等时圈
    try:
        iso = await isochrone.compute_isochrone(
            center["lat"], center["lng"], client, settings, walk_minutes, bucket=bucket, water_guard=water_guard
        )
    except Exception as exc:
        warnings.append(f"等时圈计算失败({exc})，已降级为演示数据")
        iso = await isochrone.compute_isochrone(
            center["lat"], center["lng"], MockBaiduClient(seed=settings.mock_seed), settings, walk_minutes
        )

    # 4) POI 采集（逐分类，失败则该分类降级）
    raw_pois: list[dict] = []
    for sc in SEARCH_CATEGORIES:
        try:
            items = await client.place_search(
                sc["query"], location=(center["lat"], center["lng"]), radius=radius_m, tag=sc["key"]
            )
        except Exception as exc:
            warnings.append(f"POI检索[{sc['key']}]失败({exc})，该分类降级为演示数据")
            items = await MockBaiduClient(seed=settings.mock_seed).place_search(
                sc["query"], location=(center["lat"], center["lng"]), radius=radius_m, tag=sc["key"]
            )
        for it in items:
            it["_report_category"] = sc["report_category"]
            it["_search_key"] = sc["key"]
        raw_pois.extend(items)

    cleaned = poi_cleaner.clean_pois(raw_pois, center["lat"], center["lng"], radius_m)

    # 5) 盲区识别
    blind = blind_spot.detect_blind_spots(
        center["lat"], center["lng"], cleaned,
        radius_m=settings.blind_radius_m, cell_m=settings.blind_cell_m,
    )

    # 6) 体检报告
    rpt = report_mod.build_report(center, iso, cleaned, blind, walk_minutes)

    resp = {
        "center": {"lat": center["lat"], "lng": center["lng"], "address": address_label},
        "mode": mode,
        "warnings": warnings,
        "admin": admin,
        "isochrone": iso,
        "pois": cleaned,
        "coverage": rpt,
        "blind_spots": blind,
        "cached": False,
        "elapsed_ms": round((time.time() - t0) * 1000),
    }
    if allow_cache:
        result_cache.set(cache_key, resp)
    return resp


def _community_boundary(center_lat: float, center_lng: float, seed: int) -> list[list[float]]:
    """生成确定性"街道/社区"示意边界（BD-09 多边形，约 1.3~1.9km 半径）。

    百度开放平台不提供街道/社区级行政边界，此处用中心点坐标哈希生成
    稳定、位置相关的模拟社区轮廓，用于前端色块演示；接入真实行政区划
    接口后可替换为官方边界。
    """
    pts: list[list[float]] = []
    for k in range(24):
        ang = math.radians(k * 15.0)
        h = hashlib.md5(f"cb:{seed}:{round(center_lat, 4)}:{round(center_lng, 4)}:{k}".encode()).hexdigest()
        r = 1300 + (int(h[:4], 16) % 600)  # 1300 ~ 1900 m
        dlat = r * math.sin(ang) / 110540.0
        dlng = r * math.cos(ang) / (111320.0 * math.cos(math.radians(center_lat)))
        pts.append([round(center_lng + dlng, 6), round(center_lat + dlat, 6)])
    return pts


def _extract_missing(summary: str) -> list[str]:
    """从盲区汇总（如“检测到 1 处服务盲区（灰色区域），共 1 个网格单元，缺失设施：菜市场。”）解析缺失设施。"""
    if "缺失设施" not in summary:
        return []
    part = summary.split("缺失设施：", 1)[1]
    return [x.strip() for x in part.replace("。", "").split("、") if x.strip()]


class InterpretRequest(BaseModel):
    data: dict


@app.post("/api/ai/interpret")
async def ai_interpret(req: InterpretRequest):
    """把体检结果组装为指令并转发到 AI 解读服务（独立进程 :8010）；AI 服务未启动时优雅降级。"""
    d = req.data
    try:
        feature = {
            "name": d.get("center", {}).get("address", "自定义坐标"),
            "overall": d["coverage"]["overall"],
            "scores": d["coverage"]["scores"],
            "counts": d["coverage"]["counts"],
            "in_polygon_pois": d["coverage"]["in_polygon_pois"],
            "area_km2": d["isochrone"]["stats"]["area_km2"],
            "max_reach_m": d["isochrone"]["stats"]["max_reach_m"],
            "cluster_count": d["blind_spots"]["cluster_count"],
            "blind_cells": len(d["blind_spots"].get("blind_cells", [])),
            "missing": _extract_missing(d["blind_spots"].get("summary", "")),
        }
    except (KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail=f"体检数据结构不完整：{exc}") from exc

    payload = {"instruction": AI_INSTRUCTION, "input": json.dumps(feature, ensure_ascii=False, indent=1)}
    try:
        resp = await http_session.post(f"{AI_SERVICE_URL}/api/ai/interpret", json=payload, timeout=60)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"AI 解读服务未就绪（{exc}）。请先启动 ai/server.py（见 docs/模型训练教程.md）。",
        ) from exc


# 前端静态资源（放在最后，不遮挡 API 路由）
_FRONTEND = Path(__file__).resolve().parent.parent.parent / "frontend"
if _FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=str(_FRONTEND), html=True), name="frontend")

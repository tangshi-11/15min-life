"""服务端体检结果持久化缓存（100m 网格 key + sqlite 落盘 + LRU 淘汰）。

设计要点：
- key = 中心点经纬度四舍五入到 3 位小数（约 100m 网格）。同格内的重复/邻近点击直接命中，
  不再调用百度算路接口（省配额、秒回）；
- sqlite 落盘（项目 data/result_cache.sqlite）：服务重启、跨日仍可命中，
  真实数据不重复消耗配额；
- LRU：条目数超过 CACHE_MAX_ENTRIES（默认 500）时按最近访问时间淘汰最旧；
- 命中时由调用方在响应中标记 cached=true，前端据此展示“缓存结果”。

口径说明：不做“就近匹配”，key 为坐标取整后的网格哈希（O(1)）；同格内最大偏差约
网格对角线距离（≈79m @100m 格），对 15 分钟步行等时圈可接受，前端明示“缓存近似”。
"""
import json
import logging
import os
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

# 项目根目录下的 data 目录（与代码运行目录无关，固定相对仓库根）
_DATA_DIR = Path(__file__).resolve().parent.parent.parent.parent / "data"
DB_PATH = _DATA_DIR / "result_cache.sqlite"

ROUND_DP = 3  # 经纬度保留 3 位小数 ≈ 111m 网格（符合“100m 网格”口径）
MAX_ENTRIES = int(os.getenv("CACHE_MAX_ENTRIES", "500"))
_TRIM_TARGET = max(1, int(MAX_ENTRIES * 0.8))  # 超限时裁剪到 80%

_SCHEMA = """
CREATE TABLE IF NOT EXISTS result_cache (
    key         TEXT PRIMARY KEY,
    result      TEXT NOT NULL,
    created_at  REAL NOT NULL,
    last_access REAL NOT NULL,
    hit_count   INTEGER NOT NULL DEFAULT 0
);
"""


def _connect() -> sqlite3.Connection:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), timeout=10)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute(_SCHEMA)
    return conn


def make_key(lat: float, lng: float) -> str:
    """生成 100m 网格缓存键：经纬度各四舍五入到 3 位小数。"""
    return f"{round(lat, ROUND_DP):.3f},{round(lng, ROUND_DP):.3f}"


def get(key: str) -> dict | None:
    """按 key 取缓存；命中时刷新 last_access/hit_count。未命中返回 None。"""
    try:
        with _connect() as conn:
            row = conn.execute(
                "SELECT result FROM result_cache WHERE key = ?", (key,)
            ).fetchone()
            if row is None:
                return None
            conn.execute(
                "UPDATE result_cache SET last_access = ?, hit_count = hit_count + 1 WHERE key = ?",
                (time.time(), key),
            )
            return json.loads(row[0])
    except Exception as exc:  # 缓存异常不影响主流程，静默降级为未命中
        logger.warning("result_cache.get 失败: %s", exc)
        return None


def set(key: str, result: dict) -> None:
    """写入缓存；超出上限时按 last_access 淘汰最旧。"""
    now = time.time()
    try:
        with _connect() as conn:
            conn.execute(
                """INSERT INTO result_cache (key, result, created_at, last_access, hit_count)
                   VALUES (?, ?, ?, ?, 0)
                   ON CONFLICT(key) DO UPDATE SET result=excluded.result,
                       created_at=excluded.created_at, last_access=excluded.last_access""",
                (key, json.dumps(result, ensure_ascii=False), now, now),
            )
            n = conn.execute("SELECT COUNT(*) FROM result_cache").fetchone()[0]
            if n > MAX_ENTRIES:
                # 只保留最近访问的 _TRIM_TARGET 条
                conn.execute(
                    """DELETE FROM result_cache WHERE key NOT IN (
                           SELECT key FROM result_cache
                           ORDER BY last_access DESC LIMIT ?
                       )""",
                    (_TRIM_TARGET,),
                )
    except Exception as exc:
        logger.warning("result_cache.set 失败: %s", exc)


def clear() -> None:
    """清空缓存（测试与调试用）。"""
    try:
        with _connect() as conn:
            conn.execute("DELETE FROM result_cache")
    except Exception as exc:
        logger.warning("result_cache.clear 失败: %s", exc)

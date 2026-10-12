"""全局配置：从项目根目录 .env 读取；未配置 AK 时自动进入演示(mock)模式。"""
import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # 项目根目录
load_dotenv(BASE_DIR / ".env")


def _flag(v: str) -> bool:
    return v.strip().lower() in ("1", "true", "yes", "on")


class Settings:
    """应用配置。BAIDU_AK_SERVER 缺失或 FORCE_MOCK=1 时使用演示数据。"""

    def __init__(self) -> None:
        self.ak_server: str = os.getenv("BAIDU_AK_SERVER", "").strip()
        self.ak_browser: str = os.getenv("BAIDU_AK_BROWSER", "").strip()
        self.force_mock: bool = _flag(os.getenv("FORCE_MOCK", ""))
        self.qps_limit: float = max(1.0, float(os.getenv("BAIDU_QPS", "10")))
        self.walking_minutes: int = int(os.getenv("WALK_MINUTES", "15"))
        self.max_radius_m: float = float(os.getenv("MAX_RADIUS_M", "2000"))
        self.directions: int = int(os.getenv("SAMPLE_DIRECTIONS", "24"))
        self.step_m: float = float(os.getenv("SAMPLE_STEP_M", "100"))
        self.matrix_chunk: int = int(os.getenv("MATRIX_CHUNK", "90"))
        self.grid_n: int = int(os.getenv("GRID_N", "60"))
        self.review_directions: int = int(os.getenv("REVIEW_DIRECTIONS", "48"))
        # 复核阈值：只复核采样边界 ≥ 该距离的方向。百度 directionlite 免费 AK 并发配额极紧，
        # 48 方向全复核 + 水域探测会触发 401 限流；小边界方向（<600m）即使有水域误差也贴岸，
        # 视觉影响可忽略，跳过复核可把请求量降一半，避免配额耗尽导致方向被错误内缩。
        self.review_min_boundary_m: float = float(os.getenv("REVIEW_MIN_BOUNDARY_M", "600"))
        self.water_guard_enabled: bool = _flag(os.getenv("WATER_GUARD_ENABLED", "true"))
        self.water_guard_radius_m: float = float(os.getenv("WATER_GUARD_RADIUS_M", "3500"))
        self.water_guard_margin_m: float = float(os.getenv("WATER_GUARD_MARGIN_M", "300"))
        self.overpass_url: str = os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter")
        self.poi_radius_m: float = float(os.getenv("POI_RADIUS_M", "2500"))
        self.blind_radius_m: float = float(os.getenv("BLIND_RADIUS_M", "1000"))
        self.blind_cell_m: float = float(os.getenv("BLIND_CELL_M", "200"))
        self.mock_seed: int = int(os.getenv("MOCK_SEED", "42"))

    @property
    def mock_mode(self) -> bool:
        return self.force_mock or not self.ak_server


settings = Settings()

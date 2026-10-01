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
        self.poi_radius_m: float = float(os.getenv("POI_RADIUS_M", "2500"))
        self.blind_radius_m: float = float(os.getenv("BLIND_RADIUS_M", "1000"))
        self.blind_cell_m: float = float(os.getenv("BLIND_CELL_M", "200"))
        self.mock_seed: int = int(os.getenv("MOCK_SEED", "42"))

    @property
    def mock_mode(self) -> bool:
        return self.force_mock or not self.ak_server


settings = Settings()

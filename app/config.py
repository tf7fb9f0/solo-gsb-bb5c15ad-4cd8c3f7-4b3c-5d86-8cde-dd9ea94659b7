"""运行期配置，全部通过环境变量注入，带默认值。"""
from __future__ import annotations

import os


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    def __init__(self) -> None:
        # SQLite 数据库文件路径
        self.db_path: str = os.getenv("DB_PATH", "/data/adjudication.db")
        # 服务监听地址 / 端口
        self.host: str = os.getenv("HOST", "0.0.0.0")
        self.port: int = int(os.getenv("PORT", "8000"))
        # 默认返回候选条数（ISO 题目要求前 20）
        self.default_top_n: int = int(os.getenv("TOP_N", "20"))
        self.max_top_n: int = 20
        # 单个位置允许提交的 OCR 候选上限，防止超大请求
        self.max_candidates_per_position: int = int(
            os.getenv("MAX_CANDIDATES_PER_POSITION", "100")
        )
        # ISO 6346 设备类别代号（第 4 位）：U 集装箱 / Z 挂车底盘 / J 可拆卸设备
        category_ids = os.getenv("CATEGORY_IDS", "UJZ").upper()
        self.allowed_category_ids: str = "".join(
            dict.fromkeys(c for c in category_ids if c.isalpha())
        ) or "UJZ"
        # 是否允许按字符类别做 OCR 形近纠正（数字位的字母 / 字母位的数字）
        self.enable_category_correction: bool = _as_bool(
            os.getenv("ENABLE_CATEGORY_CORRECTION", "true"), default=True
        )
        # 形近纠正附加惩罚系数：纠正候选代价 = -ln(conf) * (1 + scale)
        self.confusion_penalty_scale: float = float(
            os.getenv("CONFUSION_PENALTY_SCALE", "1.0")
        )


settings = Settings()

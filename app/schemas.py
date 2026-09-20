"""请求 / 响应数据模型（Pydantic v2）。"""
from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from .iso6346 import CODE_LENGTH
from .config import settings


class OcrCandidate(BaseModel):
    """单个 OCR 候选字符及其置信度。"""

    char: str = Field(..., min_length=1, max_length=1, description="OCR 候选字符")
    confidence: float = Field(
        ..., gt=0.0, le=1.0, description="OCR 置信度，取值范围 (0, 1]"
    )


class PositionInput(BaseModel):
    """箱号某一位置的全部 OCR 候选，按位置从左到右排列。"""

    candidates: list[OcrCandidate] = Field(..., min_length=1)

    @field_validator("candidates")
    @classmethod
    def _limit_candidates(cls, value: list[OcrCandidate]) -> list[OcrCandidate]:
        if len(value) > settings.max_candidates_per_position:
            raise ValueError(
                f"each position accepts at most "
                f"{settings.max_candidates_per_position} candidates"
            )
        return value


class AdjudicateRequest(BaseModel):
    """裁决请求：必须包含 11 个位置（ISO 6346：4 字母 + 7 数字）。"""

    positions: list[PositionInput] = Field(
        ...,
        min_length=CODE_LENGTH,
        max_length=CODE_LENGTH,
        description="按箱号位 0-10 排列的 OCR 候选列表",
    )
    top_n: int | None = Field(
        default=None,
        ge=1,
        le=settings.max_top_n,
        description="返回前 N 项，默认与上限均为 20",
    )


class PositionDetail(BaseModel):
    position: int
    char: str
    raw_char: str
    confidence: float
    corrected: bool
    negative_log_likelihood: float


class CandidateCode(BaseModel):
    code: str
    score: float = Field(..., description="总负对数置信度 -Σln(conf)，越小越优")
    positions: list[PositionDetail]


class AdjudicateResponse(BaseModel):
    request_id: str
    status: str = Field(..., description="unique | ambiguous | invalid")
    valid_count: int = Field(..., description="通过全部约束的有效候选总数（不受截断影响）")
    admissible_count: int = Field(
        ..., description="通过字符类别与所有人/类别标识规则的候选数（未必通过校验）"
    )
    top_n: int
    results: list[CandidateCode]


class RecordSummary(BaseModel):
    request_id: str
    status: str
    valid_count: int
    best_code: str | None
    best_score: float | None
    created_at: str

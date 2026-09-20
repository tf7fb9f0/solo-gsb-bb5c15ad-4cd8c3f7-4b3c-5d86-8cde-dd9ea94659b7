"""Request/response schemas."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class OCRCandidate(BaseModel):
    """One OCR hypothesis for a single position."""
    char: str = Field(..., min_length=1, max_length=1,
                      description="候选字符（大小写字母或数字，服务端统一大写）")
    confidence: float = Field(..., gt=0.0, le=1.0,
                              description="置信度，范围 (0, 1]")

    @field_validator("char")
    @classmethod
    def _alnum_upper(cls, v: str) -> str:
        v = v.upper()
        if not ("0" <= v <= "9" or "A" <= v <= "Z"):
            raise ValueError("候选字符只能是字母或数字")
        return v


class AdjudicateRequest(BaseModel):
    """OCR candidates for the 11 ISO 6346 positions, in order."""
    positions: list[list[OCRCandidate]] = Field(
        ...,
        min_length=11,
        max_length=11,
        description="11 个位置的 OCR 候选列表，顺序为 4 字母 + 7 数字",
    )
    enforce_owner_registry: bool | None = Field(
        None,
        description="是否要求前 3 位为已注册箱主代码；缺省取服务端配置",
    )

    @field_validator("positions")
    @classmethod
    def _non_empty_positions(cls, v: list[list[OCRCandidate]]):
        for i, cands in enumerate(v, start=1):
            if len(cands) == 0:
                raise ValueError(f"第 {i} 个位置至少需要 1 个候选字符")
        return v


class RankedCandidate(BaseModel):
    code: str
    score: float = Field(..., description="总负对数置信度 sum(-log p)，越小越优")
    probability: float = Field(..., description="exp(-score)，候选联合概率")
    per_position_confidence: list[float]


class AdjudicateResponse(BaseModel):
    id: str
    status: Literal["unique", "ambiguous", "invalid"]
    total_candidates: int = Field(..., description="通过全部约束的有效候选总数")
    top: list[RankedCandidate] = Field(..., description="至多前 20 项，截断不影响总数")
    dropped: list[int] = Field(..., description="每个位置因字符类别不符被丢弃的候选数")
    empty_positions: list[int]
    owner_registry_enforced: bool


class OwnerCodeIn(BaseModel):
    code: str = Field(..., min_length=3, max_length=3,
                      description="3 位注册箱主代码（大写字母）")
    description: str = ""

    @field_validator("code")
    @classmethod
    def _three_letters(cls, v: str) -> str:
        v = v.upper()
        if not all("A" <= ch <= "Z" for ch in v):
            raise ValueError("箱主代码必须为 3 个大写字母")
        return v


class OwnerCodeOut(BaseModel):
    code: str
    description: str

"""FastAPI 入口：裁决、记录查询与健康检查。"""
from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Query, status
from sqlite3 import Connection

from . import database
from .adjudication import adjudicate
from .config import settings
from .schemas import (
    AdjudicateRequest,
    AdjudicateResponse,
    CandidateCode,
    PositionDetail,
    RecordSummary,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    database.init_db(settings.db_path)
    yield


app = FastAPI(
    title="集装箱箱号模糊识别裁决 API",
    description=(
        "接收 ISO 6346 箱号各位置的 OCR 候选字符与置信度，"
        "按字符类别、所有人代码/设备类别标识规则与模 11 校验联合搜索，"
        "返回有效候选总数、按总负对数置信度排序的前 20 项及裁决状态。"
    ),
    version="1.0.0",
    lifespan=lifespan,
)


def get_db() -> Connection:
    with database.get_conn(settings.db_path) as conn:
        yield conn


@app.get("/health", tags=["meta"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/api/v1/adjudicate",
    response_model=AdjudicateResponse,
    status_code=status.HTTP_200_OK,
    tags=["adjudication"],
    summary="对 11 个位置的 OCR 候选执行联合裁决",
)
def do_adjudicate(
    request: AdjudicateRequest,
    db: Connection = Depends(get_db),
) -> AdjudicateResponse:
    top_n = request.top_n or settings.default_top_n
    positions = [
        [(c.char, c.confidence) for c in pos.candidates]
        for pos in request.positions
    ]

    outcome = adjudicate(
        positions,
        allowed_category_ids=settings.allowed_category_ids,
        enable_correction=settings.enable_category_correction,
        penalty_scale=settings.confusion_penalty_scale,
        top_n=top_n,
    )

    results = [
        CandidateCode(
            code=item["code"],
            score=item["score"],
            positions=[PositionDetail(**p) for p in item["positions"]],
        )
        for item in outcome.results
    ]

    request_id = uuid.uuid4().hex
    best = results[0] if results else None
    response = AdjudicateResponse(
        request_id=request_id,
        status=outcome.status,
        valid_count=outcome.valid_count,
        admissible_count=outcome.admissible_count,
        top_n=top_n,
        results=results,
    )

    request_payload = request.model_dump(mode="json")
    response_payload = response.model_dump(mode="json")
    database.insert_record(
        db,
        request_id=request_id,
        status=outcome.status,
        valid_count=outcome.valid_count,
        admissible_count=outcome.admissible_count,
        best_code=best.code if best else None,
        best_score=best.score if best else None,
        request_payload=request_payload,
        response_payload=response_payload,
    )
    return response


@app.get(
    "/api/v1/records",
    tags=["records"],
    summary="分页查询裁决记录",
)
def list_records(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    status_filter: str | None = Query(
        default=None,
        alias="status",
        pattern="^(unique|ambiguous|invalid)$",
    ),
    db: Connection = Depends(get_db),
) -> dict[str, Any]:
    rows = database.list_records(
        db, limit=limit, offset=offset, status=status_filter
    )
    total = database.count_records(db, status=status_filter)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": [
            RecordSummary(
                request_id=row["request_id"],
                status=row["status"],
                valid_count=row["valid_count"],
                best_code=row["best_code"],
                best_score=row["best_score"],
                created_at=row["created_at"],
            ).model_dump()
            for row in rows
        ],
    }


@app.get(
    "/api/v1/records/{request_id}",
    tags=["records"],
    summary="按 ID 查询单条裁决记录（含原始请求与完整响应）",
)
def get_record(request_id: str, db: Connection = Depends(get_db)) -> dict[str, Any]:
    row = database.get_record(db, request_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"record {request_id!r} not found",
        )
    return {
        "request_id": row["id"],
        "status": row["status"],
        "valid_count": row["valid_count"],
        "admissible_count": row["admissible_count"],
        "best_code": row["best_code"],
        "best_score": row["best_score"],
        "created_at": row["created_at"],
        "request": json.loads(row["request_payload"]),
        "response": json.loads(row["response_payload"]),
    }

"""FastAPI application: ISO 6346 container-number fuzzy adjudication."""
from __future__ import annotations

import math
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import RedirectResponse

from . import config, db, iso6346
from .schemas import (
    AdjudicateRequest,
    AdjudicateResponse,
    OwnerCodeIn,
    OwnerCodeOut,
    RankedCandidate,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Container startup: the image already has dependencies installed;
    # here we create the schema and seed the owner registry idempotently.
    db.init_db()
    yield


app = FastAPI(
    title="ISO 6346 集装箱箱号模糊识别裁决 API",
    version="1.0.0",
    lifespan=lifespan,
)


def _normalize_positions(
    request: AdjudicateRequest,
) -> list[dict[str, float]]:
    """Deduplicate repeated candidates per position, keeping best confidence."""
    normalized: list[dict[str, float]] = []
    for cands in request.positions:
        best: dict[str, float] = {}
        for cand in cands:
            if cand.confidence > best.get(cand.char, 0.0):
                best[cand.char] = cand.confidence
        normalized.append(best)
    return normalized


def _registry_snapshot() -> frozenset[str]:
    return db.registered_owner_codes()


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/docs")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/v1/adjudicate", response_model=AdjudicateResponse,
          tags=["adjudication"])
def adjudicate(request: AdjudicateRequest) -> AdjudicateResponse:
    positions = _normalize_positions(request)
    enforced = (
        config.ENFORCE_OWNER_REGISTRY
        if request.enforce_owner_registry is None
        else request.enforce_owner_registry
    )

    result = iso6346.adjudicate(
        positions=positions,
        category_letters=config.CATEGORY_LETTERS,
        registered_owners=_registry_snapshot(),
        enforce_owner_registry=bool(enforced),
        k=config.TOP_K,
    )

    ranked = [
        RankedCandidate(
            code=code,
            score=round(score, 12),
            probability=math.exp(-score),
            per_position_confidence=[round(c, 12) for c in confs],
        )
        for code, score, confs in result.ranked
    ]

    body = {
        "status": result.status,
        "total_candidates": result.total_candidates,
        "ranked": [c.model_dump() for c in ranked],
        "dropped": result.dropped,
        "empty_positions": result.empty_positions,
    }
    adj_id = db.save_adjudication(
        request_payload=request.model_dump(),
        result=body,
        enforced=bool(enforced),
    )

    return AdjudicateResponse(
        id=adj_id,
        status=result.status,
        total_candidates=result.total_candidates,
        top=ranked,
        dropped=result.dropped,
        empty_positions=result.empty_positions,
        owner_registry_enforced=bool(enforced),
    )


@app.get("/api/v1/adjudications/{adj_id}", tags=["adjudication"])
def get_adjudication(adj_id: str):
    record = db.get_adjudication(adj_id)
    if record is None:
        raise HTTPException(status_code=404, detail="裁决记录不存在")
    return {"id": adj_id, **record}


@app.get("/api/v1/adjudications", tags=["adjudication"])
def list_adjudications(
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    status: str | None = Query(None, pattern="^(unique|ambiguous|invalid)$"),
):
    items, total = db.list_adjudications(limit, offset, status)
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@app.get("/api/v1/owner-codes", response_model=list[OwnerCodeOut],
         tags=["owner-registry"])
def list_owner_codes():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT code, description FROM owner_codes ORDER BY code"
    ).fetchall()
    return [OwnerCodeOut(code=r["code"], description=r["description"])
            for r in rows]


@app.post("/api/v1/owner-codes", response_model=OwnerCodeOut,
          status_code=201, tags=["owner-registry"])
def add_owner_code(payload: OwnerCodeIn):
    db.upsert_owner_code(payload.code, payload.description)
    return OwnerCodeOut(code=payload.code, description=payload.description)

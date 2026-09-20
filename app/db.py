"""SQLite persistence: adjudication records and the owner-code registry.

Schema is created idempotently on startup (see ``init_db``), which also seeds
a set of well-known registered BIC owner prefixes.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from typing import Any

from . import config

# Well-known registered BIC owner prefixes (first 3 letters of a BIC code;
# the 4th position is the ISO 6346 category identifier and is not part of the
# registered owner). Educational seed set — only enforced when
# ENFORCE_OWNER_REGISTRY=true.
SEED_OWNER_CODES = [
    ("CSQ", "COSCO Shipping"), ("MSC", "Mediterranean Shipping Company"),
    ("MAE", "Maersk Line"), ("TCN", "Triton Container Intl"),
    ("GES", "Genstar"), ("EAC", "Evergreen"), ("EIT", "Evergreen"),
    ("EMC", "Evergreen Marine"), ("TRI", "Triton"),
    ("TGB", "Textainer"), ("TLL", "Triton / TLL"), ("TLC", "Triton"),
    ("GLN", "Global One"), ("HLC", "Hapag-Lloyd"), ("HLB", "Hapag-Lloyd"),
    ("HLX", "Hapag-Lloyd Express"), ("MED", "MSC (MEDU prefix)"),
    ("CMA", "CMA CGM"), ("CMC", "CMA CGM"), ("ANL", "ANL Container Line"),
    ("OOL", "OOCL"), ("NYK", "NYK Line"), ("MOG", "MOL (MOGU)"),
    ("MOL", "Mitsui OSK Lines"), ("KKF", "K-Line (KKFU)"),
    ("KLF", "K Line"), ("KMT", "Korea Maritime Transport"),
    ("YML", "Yang Ming"), ("YMM", "Yang Ming"), ("WHL", "Wan Hai Lines"),
    ("PCI", "Pacific International Lines"), ("SEN", "Simatech"),
    ("DFS", "Dong Fang"), ("CBH", "Containerbruno"), ("BMO", "BMO"),
    ("PRS", "P&O"), ("PON", "P&O Nedlloyd"), ("UXX", "Uniexpress"),
    ("GVD", "Geveran"), ("CRX", "Containerships"), ("ICN", "Icon"),
    ("CAX", "CAI"), ("CAI", "CAI International"), ("FCI", "Florens"),
    ("FLO", "Florens"), ("GAT", "Gateway"), ("GST", "Gold Star"),
    ("SUD", "Hamburg Süd"), ("HAM", "Hamburg Süd"), ("ZIM", "ZIM"),
    ("ZCS", "ZIM (ZCSU)"), ("KHJ", "KHJ"),
]

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    """Process-wide connection; check_same_thread off with a write lock."""
    global _conn
    if _conn is None:
        import os
        os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
        conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _conn = conn
    return _conn


def init_db() -> None:
    """Create tables and seed the owner registry (idempotent)."""
    conn = get_conn()
    with _lock:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS adjudications (
                id              TEXT PRIMARY KEY,
                created_at      REAL NOT NULL,
                request_json    TEXT NOT NULL,
                total_candidates INTEGER NOT NULL,
                status          TEXT NOT NULL,
                ranked_json     TEXT NOT NULL,
                dropped_json    TEXT NOT NULL,
                empty_positions_json TEXT NOT NULL,
                owner_registry_enforced INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS owner_codes (
                code        TEXT PRIMARY KEY CHECK (length(code) = 3
                                                   AND code GLOB '[A-Z][A-Z][A-Z]'),
                description TEXT NOT NULL DEFAULT '',
                created_at  REAL NOT NULL
            );
            """
        )
        now = time.time()
        seen: set[str] = set()
        for code, description in SEED_OWNER_CODES:
            if code in seen:
                continue
            seen.add(code)
            conn.execute(
                "INSERT OR IGNORE INTO owner_codes (code, description, created_at)"
                " VALUES (?, ?, ?)",
                (code, description, now),
            )
        conn.commit()


def registered_owner_codes() -> frozenset[str]:
    rows = get_conn().execute("SELECT code FROM owner_codes").fetchall()
    return frozenset(r["code"] for r in rows)


def upsert_owner_code(code: str, description: str = "") -> None:
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO owner_codes (code, description, created_at)"
            " VALUES (?, ?, ?)"
            " ON CONFLICT(code) DO UPDATE SET description = excluded.description",
            (code, description, time.time()),
        )
        conn.commit()


def save_adjudication(
    request_payload: dict[str, Any],
    result: dict[str, Any],
    enforced: bool,
) -> str:
    adj_id = uuid.uuid4().hex
    with _lock:
        conn = get_conn()
        conn.execute(
            "INSERT INTO adjudications ("
            "id, created_at, request_json, total_candidates, status,"
            " ranked_json, dropped_json, empty_positions_json,"
            " owner_registry_enforced) VALUES (?,?,?,?,?,?,?,?,?)",
            (
                adj_id,
                time.time(),
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
                int(result["total_candidates"]),
                result["status"],
                json.dumps(result["ranked"], ensure_ascii=False),
                json.dumps(result["dropped"], ensure_ascii=False),
                json.dumps(result["empty_positions"], ensure_ascii=False),
                1 if enforced else 0,
            ),
        )
        conn.commit()
    return adj_id


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "request": json.loads(row["request_json"]),
        "total_candidates": row["total_candidates"],
        "status": row["status"],
        "ranked": json.loads(row["ranked_json"]),
        "dropped": json.loads(row["dropped_json"]),
        "empty_positions": json.loads(row["empty_positions_json"]),
        "owner_registry_enforced": bool(row["owner_registry_enforced"]),
    }


def get_adjudication(adj_id: str) -> dict[str, Any] | None:
    row = get_conn().execute(
        "SELECT * FROM adjudications WHERE id = ?", (adj_id,)
    ).fetchone()
    return _row_to_dict(row) if row else None


def list_adjudications(limit: int, offset: int, status: str | None):
    conn = get_conn()
    if status:
        rows = conn.execute(
            "SELECT * FROM adjudications WHERE status = ?"
            " ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
            (status, limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM adjudications WHERE status = ?",
            (status,),
        ).fetchone()["n"]
    else:
        rows = conn.execute(
            "SELECT * FROM adjudications"
            " ORDER BY created_at DESC, id LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        total = conn.execute(
            "SELECT COUNT(*) AS n FROM adjudications"
        ).fetchone()["n"]
    return [_row_to_dict(r) for r in rows], total

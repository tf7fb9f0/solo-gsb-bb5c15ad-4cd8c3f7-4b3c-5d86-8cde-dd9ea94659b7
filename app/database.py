"""SQLite 持久化：裁决记录的建库、写入与查询。"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from typing import Iterator

_SCHEMA = """
CREATE TABLE IF NOT EXISTS adjudication_records (
    id               TEXT PRIMARY KEY,
    status           TEXT NOT NULL,
    valid_count      INTEGER NOT NULL,
    admissible_count INTEGER NOT NULL,
    best_code        TEXT,
    best_score       REAL,
    request_payload  TEXT NOT NULL,
    response_payload TEXT NOT NULL,
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_records_created_at
    ON adjudication_records (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_records_status
    ON adjudication_records (status);
"""


def _connect(db_path: str) -> sqlite3.Connection:
    directory = os.path.dirname(os.path.abspath(db_path))
    os.makedirs(directory, exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db(db_path: str) -> None:
    """幂等建库，容器启动时与应用启动时各调用一次均安全。"""
    with _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


@contextmanager
def get_conn(db_path: str) -> Iterator[sqlite3.Connection]:
    conn = _connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def insert_record(
    conn: sqlite3.Connection,
    *,
    request_id: str,
    status: str,
    valid_count: int,
    admissible_count: int,
    best_code: str | None,
    best_score: float | None,
    request_payload: dict,
    response_payload: dict,
) -> None:
    conn.execute(
        """
        INSERT INTO adjudication_records (
            id, status, valid_count, admissible_count,
            best_code, best_score, request_payload, response_payload
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            request_id,
            status,
            valid_count,
            admissible_count,
            best_code,
            best_score,
            json.dumps(request_payload, ensure_ascii=False),
            json.dumps(response_payload, ensure_ascii=False),
        ),
    )


def list_records(
    conn: sqlite3.Connection, *, limit: int, offset: int, status: str | None
) -> list[sqlite3.Row]:
    sql = (
        "SELECT id AS request_id, status, valid_count, admissible_count, "
        "best_code, best_score, created_at "
        "FROM adjudication_records "
    )
    params: list = []
    if status:
        sql += "WHERE status = ? "
        params.append(status)
    sql += "ORDER BY created_at DESC, id ASC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    return list(conn.execute(sql, params).fetchall())


def count_records(conn: sqlite3.Connection, *, status: str | None) -> int:
    if status:
        row = conn.execute(
            "SELECT COUNT(*) FROM adjudication_records WHERE status = ?",
            (status,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM adjudication_records"
        ).fetchone()
    return int(row[0])


def get_record(conn: sqlite3.Connection, request_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM adjudication_records WHERE id = ?",
        (request_id,),
    ).fetchone()

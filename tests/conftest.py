"""pytest 夹具：每个测试使用独立临时数据库。"""
from __future__ import annotations

import os
import tempfile

import pytest

_TMP_DB = tempfile.NamedTemporaryFile(prefix="adj_test_", suffix=".db", delete=False)
_TMP_DB.close()
os.environ["DB_PATH"] = _TMP_DB.name
os.environ["CATEGORY_IDS"] = "UJZ"
os.environ["ENABLE_CATEGORY_CORRECTION"] = "true"

from fastapi.testclient import TestClient  # noqa: E402

from app import database  # noqa: E402
from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session")
def client() -> TestClient:
    database.init_db(settings.db_path)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def payload_factory():
    """构造 11 位置请求；override 指定位置的候选列表。"""

    def _make(overrides: dict[int, list[tuple[str, float]]] | None = None,
              top_n: int | None = None) -> dict:
        overrides = overrides or {}
        positions = []
        for pos in range(11):
            cands = overrides.get(pos, [("X", 0.99)])
            positions.append({
                "candidates": [
                    {"char": ch, "confidence": conf} for ch, conf in cands
                ]
            })
        body: dict = {"positions": positions}
        if top_n is not None:
            body["top_n"] = top_n
        return body

    return _make

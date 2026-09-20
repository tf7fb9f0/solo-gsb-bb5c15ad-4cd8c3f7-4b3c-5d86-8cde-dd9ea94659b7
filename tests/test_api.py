"""API 层测试：HTTP 状态、记录持久化与查询。"""
from __future__ import annotations


def _simple_payload(best_conf: float = 0.95, check_digit: str = "6") -> dict:
    seq = ["M", "S", "C", "U", "1", "2", "3", "4", "5", "6", check_digit]
    return {
        "positions": [
            {"candidates": [{"char": ch, "confidence": best_conf}]}
            for ch in seq
        ]
    }


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_adjudicate_unique(client):
    resp = client.post("/api/v1/adjudicate", json=_simple_payload())
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "unique"
    assert body["valid_count"] == 1
    assert body["results"][0]["code"] == "MSCU1234566"
    assert body["top_n"] == 20
    assert len(body["request_id"]) == 32


def test_adjudicate_invalid(client):
    resp = client.post("/api/v1/adjudicate",
                       json=_simple_payload(check_digit="0"))
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "invalid"
    assert body["valid_count"] == 0
    assert body["results"] == []


def test_wrong_position_count_returns_422(client, payload_factory):
    body = payload_factory()
    body["positions"] = body["positions"][:10]
    resp = client.post("/api/v1/adjudicate", json=body)
    assert resp.status_code == 422


def test_empty_candidates_returns_422(client, payload_factory):
    body = payload_factory({0: []})
    resp = client.post("/api/v1/adjudicate", json=body)
    assert resp.status_code == 422


def test_bad_confidence_returns_422(client):
    payload = _simple_payload()
    payload["positions"][0]["candidates"][0]["confidence"] = 1.5
    resp = client.post("/api/v1/adjudicate", json=payload)
    assert resp.status_code == 422


def test_records_are_saved_and_queryable(client):
    resp = client.post("/api/v1/adjudicate", json=_simple_payload())
    request_id = resp.json()["request_id"]

    listing = client.get("/api/v1/records").json()
    assert listing["total"] >= 1
    ids = [item["request_id"] for item in listing["items"]]
    assert request_id in ids

    detail = client.get(f"/api/v1/records/{request_id}")
    assert detail.status_code == 200
    detail_body = detail.json()
    assert detail_body["response"]["results"][0]["code"] == "MSCU1234566"
    assert detail_body["request"]["positions"][0]["candidates"][0]["char"] == "M"

    missing = client.get("/api/v1/records/nonexistent-id")
    assert missing.status_code == 404


def test_records_filter_by_status(client):
    client.post("/api/v1/adjudicate", json=_simple_payload())
    client.post("/api/v1/adjudicate",
                json=_simple_payload(check_digit="0"))
    invalid = client.get("/api/v1/records", params={"status": "invalid"}).json()
    assert all(item["status"] == "invalid" for item in invalid["items"])
    assert invalid["total"] >= 1


def test_ambiguous_flow_with_many_candidates(client, payload_factory):
    resp = client.post("/api/v1/adjudicate", json=payload_factory({
        0: [("A", 0.8), ("B", 0.7), ("C", 0.6)],
        1: [("A", 0.8), ("B", 0.7), ("C", 0.6)],
        2: [("A", 0.8), ("B", 0.7), ("C", 0.6)],
        3: [("U", 0.9)],
        4: [("1", 0.9)], 5: [("2", 0.9)], 6: [("3", 0.9)],
        7: [("4", 0.9)], 8: [("5", 0.9)], 9: [("6", 0.9)],
        10: [(d, 0.9) for d in "0123456789"],
    }, top_n=10))
    body = resp.json()
    assert body["status"] == "ambiguous"
    assert len(body["results"]) == min(10, body["valid_count"])
    assert body["valid_count"] > 10  # 总数不受 top_n=10 截断
    scores = [r["score"] for r in body["results"]]
    assert scores == sorted(scores)

"""Integration tests for GET /runs (T2.2 acceptance criteria)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_runs_empty_db(db_path, tmp_path) -> None:
    """Empty DB returns 200 with items=[] and total=0."""
    from plumb._http_deps import StoragePool
    from plumb.http import app

    pool = StoragePool(db_path, pool_size=1)
    app.state.pool = pool
    try:
        client = TestClient(app, raise_server_exceptions=True)
        resp = client.get("/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0
    finally:
        pool.close()


def test_list_runs_returns_items(http_client: TestClient) -> None:
    resp = http_client.get("/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 3
    assert len(data["items"]) >= 3


def test_list_runs_limit_enforced(http_client: TestClient) -> None:
    resp = http_client.get("/runs?limit=2")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) <= 2
    assert data["limit"] == 2


def test_list_runs_offset(http_client: TestClient) -> None:
    all_resp = http_client.get("/runs")
    all_ids = [r["run_id"] for r in all_resp.json()["items"]]

    page_resp = http_client.get("/runs?limit=2&offset=1")
    page_ids = [r["run_id"] for r in page_resp.json()["items"]]

    assert page_ids == all_ids[1:3]


def test_list_runs_limit_zero_returns_422(http_client: TestClient) -> None:
    resp = http_client.get("/runs?limit=0")
    assert resp.status_code == 422


def test_list_runs_limit_over_500_returns_422(http_client: TestClient) -> None:
    resp = http_client.get("/runs?limit=501")
    assert resp.status_code == 422


def test_list_runs_kind_offline_filter(http_client: TestClient) -> None:
    resp = http_client.get("/runs?kind=offline")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["kind"] == "offline" for r in data["items"])


def test_list_runs_kind_invalid_returns_422(http_client: TestClient) -> None:
    resp = http_client.get("/runs?kind=foo")
    assert resp.status_code == 422


def test_list_runs_since_relative(http_client: TestClient) -> None:
    resp = http_client.get("/runs?since=7d")
    assert resp.status_code == 200


def test_list_runs_since_iso(http_client: TestClient) -> None:
    resp = http_client.get("/runs?since=2026-01-01")
    assert resp.status_code == 200


def test_list_runs_since_garbage_returns_422(http_client: TestClient) -> None:
    resp = http_client.get("/runs?since=garbage")
    assert resp.status_code == 422
    data = resp.json()
    assert data["detail"]["error_type"] == "validation_error"


def test_list_runs_task_id_filter(http_client: TestClient) -> None:
    resp = http_client.get("/runs?task_id=test.task")
    assert resp.status_code == 200
    data = resp.json()
    assert all(r["task_id"] == "test.task" for r in data["items"])


def test_list_runs_items_have_span_and_score_counts(http_client: TestClient) -> None:
    resp = http_client.get("/runs?task_id=test.task&kind=offline")
    data = resp.json()
    run = next(r for r in data["items"] if r["run_id"] == "a" * 32)
    assert run["span_count"] == 2
    assert run["score_count"] == 1


def test_list_runs_pagination_total_independent_of_offset(http_client: TestClient) -> None:
    r1 = http_client.get("/runs?limit=1&offset=0")
    r2 = http_client.get("/runs?limit=1&offset=2")
    assert r1.json()["total"] == r2.json()["total"]

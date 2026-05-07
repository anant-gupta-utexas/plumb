"""Integration tests for GET /health (T1.3 acceptance criteria)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from plumb.http import app


def test_health_returns_200_ok(http_client: TestClient) -> None:
    resp = http_client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_health_content_type_json(http_client: TestClient) -> None:
    resp = http_client.get("/health")
    assert "application/json" in resp.headers["content-type"]


def test_app_state_pool_is_set(http_client: TestClient) -> None:
    assert app.state.pool is not None

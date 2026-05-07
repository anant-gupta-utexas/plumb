"""Integration tests for GET /examples (T2.4 acceptance criteria)."""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_list_examples_all(http_client: TestClient) -> None:
    resp = http_client.get("/examples")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 3


def test_list_examples_filter_task_id(http_client: TestClient) -> None:
    resp = http_client.get("/examples?task_id=test.task")
    assert resp.status_code == 200
    data = resp.json()
    assert all(ex["task_id"] == "test.task" for ex in data["items"])
    assert len(data["items"]) == 2


def test_list_examples_filter_active_true(http_client: TestClient) -> None:
    resp = http_client.get("/examples?active=true")
    assert resp.status_code == 200
    data = resp.json()
    assert all(ex["active"] is True for ex in data["items"])
    assert len(data["items"]) == 2


def test_list_examples_filter_active_false(http_client: TestClient) -> None:
    resp = http_client.get("/examples?active=false")
    assert resp.status_code == 200
    data = resp.json()
    assert all(ex["active"] is False for ex in data["items"])
    assert len(data["items"]) == 1


def test_list_examples_combined_filters(http_client: TestClient) -> None:
    resp = http_client.get("/examples?task_id=test.task&active=true")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["items"]) == 1
    assert data["items"][0]["task_id"] == "test.task"
    assert data["items"][0]["active"] is True


def test_list_examples_empty_task_id(http_client: TestClient) -> None:
    resp = http_client.get("/examples?task_id=nonexistent")
    assert resp.status_code == 200
    assert resp.json()["items"] == []

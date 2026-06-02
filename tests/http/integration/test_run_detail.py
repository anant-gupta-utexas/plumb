"""Integration tests for GET /runs/{run_id} (T2.3 acceptance criteria)."""

from __future__ import annotations

from fastapi.testclient import TestClient

_VALID_RUN_ID = "a" * 32
_UNKNOWN_RUN_ID = "0" * 32


def test_get_run_happy_path(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{_VALID_RUN_ID}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run"]["run_id"] == _VALID_RUN_ID
    assert isinstance(data["spans"], list)
    assert isinstance(data["scores"], list)


def test_get_run_spans_ordered_root_first(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{_VALID_RUN_ID}")
    spans = resp.json()["spans"]
    assert len(spans) == 2
    # Root span (parent_span_id=None) must come first
    assert spans[0]["parent_span_id"] is None


def test_get_run_zero_spans(http_client: TestClient) -> None:
    # run_id "c"*32 was written with no spans
    resp = http_client.get(f"/runs/{'c' * 32}")
    assert resp.status_code == 200
    assert resp.json()["spans"] == []


def test_get_run_zero_scores(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{'c' * 32}")
    assert resp.status_code == 200
    assert resp.json()["scores"] == []


def test_get_run_not_found_returns_404(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{_UNKNOWN_RUN_ID}")
    assert resp.status_code == 404
    detail = resp.json()["detail"]
    assert detail["error_type"] == "not_found"
    # Only first 8 chars exposed (information minimization)
    assert _UNKNOWN_RUN_ID[:8] in detail["detail"]
    assert _UNKNOWN_RUN_ID not in detail["detail"]


def test_get_run_bad_hex_31_chars_returns_422(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{'a' * 31}")
    assert resp.status_code == 422


def test_get_run_bad_hex_33_chars_returns_422(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{'a' * 33}")
    assert resp.status_code == 422


def test_get_run_non_hex_returns_422(http_client: TestClient) -> None:
    resp = http_client.get(f"/runs/{'z' * 32}")
    assert resp.status_code == 422


def test_get_run_hashes_are_64_char_hex(http_client: TestClient) -> None:
    """input_hash / output_hash must be 64-char hex when present, never blobs."""
    resp = http_client.get(f"/runs/{_VALID_RUN_ID}")
    spans = resp.json()["spans"]
    for span in spans:
        if span["input_hash"] is not None:
            assert len(span["input_hash"]) == 64
        if span["output_hash"] is not None:
            assert len(span["output_hash"]) == 64

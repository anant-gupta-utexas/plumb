"""Integration tests for GET /stats/task/{task_id}."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Run, RunKind, RunStatus, Score, ScorerKind


def _make_run(
    run_id: str,
    task_id: str = "test.task",
    status: RunStatus = RunStatus.SUCCESS,
    dollar_cost: float | None = 0.01,
    tokens_in: int | None = 100,
    tokens_out: int | None = 50,
) -> Run:
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = start + timedelta(seconds=10)
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.OFFLINE,
        status=status,
        start_ts=start,
        end_ts=end if status != RunStatus.PENDING else None,
        dollar_cost=dollar_cost,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


def _make_score(
    score_id: str,
    run_id: str,
    metric_name: str = "quality",
    scorer: ScorerKind = ScorerKind.JUDGE,
    value_numeric: float | None = 0.9,
    value_label: str | None = None,
) -> Score:
    return Score(
        score_id=score_id,
        run_id=run_id,
        metric_name=metric_name,
        scorer=scorer,
        scorer_version="v1",
        scored_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        value_numeric=value_numeric,
        value_label=value_label,
    )


@pytest.fixture
def stats_client(tmp_path, seeded_db) -> TestClient:  # type: ignore[no-untyped-def]
    """TestClient with seeded_db already injected via http_client fixture pattern."""
    from plumb._http_deps import StoragePool
    from plumb.http import app

    pool = StoragePool(tmp_path / "plumb.db", pool_size=1)
    app.state.pool = pool
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    pool.close()


@pytest.fixture
def stats_only_client(tmp_path):  # type: ignore[no-untyped-def]
    """TestClient with a fresh DB containing only stats-relevant seed data."""
    from pathlib import Path

    class _FakeClock:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    db_path: Path = tmp_path / "plumb.db"
    adapter = SQLiteStorageAdapter(db_path, clock=_FakeClock())

    run1 = _make_run("a" * 32, task_id="atlas.task")
    run2 = _make_run("b" * 32, task_id="atlas.task", status=RunStatus.FAILURE)
    run3 = _make_run("c" * 32, task_id="atlas.task", status=RunStatus.SUCCESS)

    adapter.write_run(run1, [])
    adapter.write_run(run2, [])
    adapter.write_run(run3, [])

    score1 = _make_score("0" * 31 + "1", run_id="a" * 32, metric_name="quality", value_numeric=0.8)
    score2 = _make_score("0" * 31 + "2", run_id="b" * 32, metric_name="quality", value_numeric=0.6)
    adapter.write_score(score1)
    adapter.write_score(score2)
    adapter.close()

    from plumb._http_deps import StoragePool
    from plumb.http import app

    pool = StoragePool(db_path, pool_size=1)
    app.state.pool = pool
    client = TestClient(app, raise_server_exceptions=False)
    yield client
    pool.close()


class TestGetTaskStats:
    def test_happy_path_returns_stats(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/atlas.task")
        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "atlas.task"
        assert body["run_count"] == 3
        # success_count=2, failure_count=1 → success_rate = 2/3
        assert abs(body["success_rate"] - 2 / 3) < 0.001
        assert body["metrics"] is not None

    def test_task_id_echoed_verbatim(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/atlas.task")
        assert resp.json()["task_id"] == "atlas.task"

    def test_all_top_level_fields_present(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/atlas.task")
        body = resp.json()
        required_fields = {
            "task_id", "since", "run_count", "success_rate",
            "intervention_rate", "latency_ms_p50", "latency_ms_p95",
            "dollar_cost_total", "tokens_in_total", "tokens_out_total",
            "tokens_per_resolved_task", "metrics",
        }
        assert required_fields <= body.keys()

    def test_404_when_no_runs_for_task(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/nonexistent.task")
        assert resp.status_code == 404
        body = resp.json()
        assert body["detail"]["error_type"] == "not_found"

    def test_404_with_since_filter_no_runs(self, stats_only_client: TestClient) -> None:
        # future date — no runs
        resp = stats_only_client.get("/stats/task/atlas.task?since=2030-01-01")
        assert resp.status_code == 404

    def test_422_on_bad_since(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/atlas.task?since=garbage")
        assert resp.status_code == 422

    def test_since_7d_relative_works(self, stats_only_client: TestClient) -> None:
        # Seed data is at 2026-01-01; 7d back from "now" (test always passes if clock is far future)
        resp = stats_only_client.get("/stats/task/atlas.task?since=7d")
        # Should 200 or 404 depending on clock — either is valid; just must not 500
        assert resp.status_code in {200, 404}

    def test_metrics_block_populated(self, stats_only_client: TestClient) -> None:
        resp = stats_only_client.get("/stats/task/atlas.task")
        metrics = resp.json()["metrics"]
        assert isinstance(metrics, list)
        assert len(metrics) > 0
        quality = next((m for m in metrics if m["metric_name"] == "quality"), None)
        assert quality is not None
        assert quality["n"] == 2
        assert quality["value_mean"] is not None

"""Shared fixtures for the plumb HTTP integration tests.

Provides a ``TestClient`` backed by a real SQLiteStorageAdapter in a
``tmp_path`` directory, with seed helpers for inserting runs, spans,
scores, and examples.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import (
    Example,
    ExampleSource,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)


class _FakeClock:
    def __init__(self, t: datetime | None = None) -> None:
        self._t = t or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._t


def _make_run(
    run_id: str,
    task_id: str = "test.task",
    kind: RunKind = RunKind.OFFLINE,
    status: RunStatus = RunStatus.SUCCESS,
    start_ts: datetime | None = None,
    end_ts: datetime | None = None,
) -> Run:
    start = start_ts or datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    end = end_ts or (start + timedelta(seconds=10))
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=kind,
        status=status,
        start_ts=start,
        end_ts=end if status != RunStatus.PENDING else None,
    )


def _make_span(span_id: str, run_id: str, parent_span_id: str | None = None) -> Span:
    return Span(
        span_id=span_id,
        run_id=run_id,
        kind=SpanKind.LLM,
        name="test-span",
        parent_span_id=parent_span_id,
        status=SpanStatus.SUCCESS,
        latency_ms=50.0,
    )


def _make_score(
    score_id: str,
    run_id: str,
    metric_name: str = "quality",
    value_numeric: float | None = 0.9,
) -> Score:
    return Score(
        score_id=score_id,
        run_id=run_id,
        metric_name=metric_name,
        scorer=ScorerKind.JUDGE,
        scorer_version="v1",
        scored_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        value_numeric=value_numeric,
    )


def _make_example(
    example_id: str,
    task_id: str = "test.task",
    active: bool = True,
) -> Example:
    return Example(
        example_id=example_id,
        task_id=task_id,
        inputs_hash="a" * 64,
        source=ExampleSource.SYNTHETIC,
        created_at=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        active=active,
    )


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """Return a path to a temp SQLite DB."""
    return tmp_path / "plumb.db"


@pytest.fixture
def seeded_db(db_path: Path) -> SQLiteStorageAdapter:
    """A real SQLiteStorageAdapter with some seed data."""
    adapter = SQLiteStorageAdapter(db_path, clock=_FakeClock())

    run1 = _make_run("a" * 32, task_id="test.task", kind=RunKind.OFFLINE)
    run2 = _make_run("b" * 32, task_id="test.task", kind=RunKind.ONLINE)
    run3 = _make_run("c" * 32, task_id="other.task", kind=RunKind.OFFLINE)

    span1 = _make_span("d" * 32, run_id="a" * 32)
    span2 = _make_span("e" * 32, run_id="a" * 32, parent_span_id="d" * 32)
    span3 = _make_span("f" * 32, run_id="b" * 32)

    score1 = _make_score("0" * 31 + "1", run_id="a" * 32, metric_name="quality")
    score2 = _make_score("0" * 31 + "2", run_id="b" * 32, metric_name="quality")

    example1 = _make_example("0" * 31 + "3", task_id="test.task", active=True)
    example2 = _make_example("0" * 31 + "4", task_id="test.task", active=False)
    example3 = _make_example("0" * 31 + "5", task_id="other.task", active=True)

    adapter.write_run(run1, [span1, span2])
    adapter.write_run(run2, [span3])
    adapter.write_run(run3, [])
    adapter.write_score(score1)
    adapter.write_score(score2)
    adapter.write_example(example1)
    adapter.write_example(example2)
    adapter.write_example(example3)

    return adapter


@pytest.fixture
def http_client(db_path: Path, seeded_db: SQLiteStorageAdapter) -> TestClient:
    """A TestClient backed by the seeded DB via a real StoragePool."""
    from plumb._http_deps import StoragePool
    from plumb.http import app

    pool = StoragePool(db_path, pool_size=1)
    app.state.pool = pool

    client = TestClient(app, raise_server_exceptions=True)
    yield client
    pool.close()

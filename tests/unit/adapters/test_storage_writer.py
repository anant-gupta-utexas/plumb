"""Tests for write_run, write_score, write_example (Tasks 3.2-3.4)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

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
)
from plumb.core.errors import StorageError


class _FixedClock:
    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def now(self) -> datetime:
        return self._dt


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_CLOCK = _FixedClock(_NOW)


def _make_run(run_id: str = "a" * 32, task_id: str = "task1") -> Run:
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.ONLINE,
        status=RunStatus.SUCCESS,
        start_ts=_NOW,
        end_ts=_NOW,
    )


def _make_span(span_id: str, run_id: str = "a" * 32) -> Span:
    return Span(
        span_id=span_id,
        run_id=run_id,
        kind=SpanKind.LLM,
        name="generate",
    )


def _make_score(score_id: str, run_id: str = "a" * 32) -> Score:
    return Score(
        score_id=score_id,
        run_id=run_id,
        metric_name="accuracy",
        scorer=ScorerKind.DETERMINISTIC,
        scorer_version="v1",
        scored_at=_NOW,
        value_numeric=0.95,
    )


def _make_example(example_id: str) -> Example:
    return Example(
        example_id=example_id,
        task_id="task1",
        inputs_hash="b" * 64,
        source=ExampleSource.SYNTHETIC,
        created_at=_NOW,
    )


# ---------------------------------------------------------------------------
# write_run
# ---------------------------------------------------------------------------


def test_write_run_no_spans(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        count = adapter._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        assert count == 1
        span_count = adapter._conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        assert span_count == 0


def test_write_run_with_100_spans(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        spans = [_make_span(f"{i:032x}") for i in range(1, 101)]
        adapter.write_run(run, spans)
        run_count = adapter._conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        span_count = adapter._conn.execute("SELECT COUNT(*) FROM spans").fetchone()[0]
        assert run_count == 1
        assert span_count == 100


def test_write_run_duplicate_raises_storage_error(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        with pytest.raises(StorageError):
            adapter.write_run(run, [])


def test_write_run_datetime_serializes_as_iso_utc(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        row = adapter._conn.execute("SELECT start_ts, end_ts FROM runs").fetchone()
        assert "+00:00" in row[0]
        assert "+00:00" in row[1]


def test_write_run_enum_values_stored_as_strings(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        row = adapter._conn.execute("SELECT kind, status FROM runs").fetchone()
        assert row[0] == "online"
        assert row[1] == "success"


def test_write_run_nullable_columns_stored_as_null(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        row = adapter._conn.execute(
            "SELECT parent_run_id, orchestrator_model, error_type FROM runs"
        ).fetchone()
        assert row[0] is None
        assert row[1] is None
        assert row[2] is None


# ---------------------------------------------------------------------------
# write_score
# ---------------------------------------------------------------------------


def test_write_score_numeric(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        score = _make_score("c" * 32)
        adapter.write_score(score)
        count = adapter._conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
        assert count == 1


def test_write_score_label_only(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        score = Score(
            score_id="d" * 32,
            run_id="a" * 32,
            metric_name="quality",
            scorer=ScorerKind.HUMAN,
            scorer_version="v1",
            scored_at=_NOW,
            value_label="good",
        )
        adapter.write_score(score)
        row = adapter._conn.execute(
            "SELECT value_numeric, value_label FROM scores"
        ).fetchone()
        assert row[0] is None
        assert row[1] == "good"


def test_write_score_scorer_value_stored(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        adapter.write_score(_make_score("c" * 32))
        row = adapter._conn.execute("SELECT scorer FROM scores").fetchone()
        assert row[0] == "deterministic"


# ---------------------------------------------------------------------------
# write_example (Task 3.4)
# ---------------------------------------------------------------------------


def test_write_example_valid(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32))
        count = adapter._conn.execute("SELECT COUNT(*) FROM examples").fetchone()[0]
        assert count == 1


def test_write_example_inactive(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        ex = Example(
            example_id="f" * 32,
            task_id="task1",
            inputs_hash="b" * 64,
            source=ExampleSource.HUMAN_AUTHORED,
            created_at=_NOW,
            active=False,
        )
        adapter.write_example(ex)
        row = adapter._conn.execute("SELECT active FROM examples").fetchone()
        assert row[0] == 0


def test_write_example_source_value_stored(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32))
        row = adapter._conn.execute("SELECT source FROM examples").fetchone()
        assert row[0] == "synthetic"

"""Tests for StorageReader methods and private helpers (Phase 4 coverage)."""

from datetime import UTC, datetime, timezone
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import (
    SQLiteStorageAdapter,
    _dt_to_iso,
    _iso_to_dt,
)
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
from plumb.core.errors import StorageError, ValidationError


class _FixedClock:
    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def now(self) -> datetime:
        return self._dt


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_CLOCK = _FixedClock(_NOW)


# ---------------------------------------------------------------------------
# Helper function coverage
# ---------------------------------------------------------------------------


def test_dt_to_iso_none_returns_none() -> None:
    assert _dt_to_iso(None) is None


def test_dt_to_iso_naive_raises() -> None:
    with pytest.raises(StorageError, match="timezone-aware"):
        _dt_to_iso(datetime(2026, 1, 1, 12, 0, 0))


def test_iso_to_dt_none_returns_none() -> None:
    assert _iso_to_dt(None) is None


def test_iso_to_dt_valid_string() -> None:
    result = _iso_to_dt("2026-01-01T12:00:00+00:00")
    assert result is not None
    assert result.year == 2026


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_run(run_id: str = "a" * 32, task_id: str = "task1") -> Run:
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.ONLINE,
        status=RunStatus.SUCCESS,
        start_ts=_NOW,
        end_ts=_NOW,
    )


def _make_span(span_id: str, run_id: str = "a" * 32, *, with_tokens: bool = False, with_latency: bool = False) -> Span:
    return Span(
        span_id=span_id,
        run_id=run_id,
        kind=SpanKind.LLM,
        name="generate",
        tokens_in=10 if with_tokens else None,
        tokens_out=5 if with_tokens else None,
        latency_ms=123.4 if with_latency else None,
        status=SpanStatus.SUCCESS if with_tokens else None,
    )


def _make_score(score_id: str, run_id: str = "a" * 32, *, span_id: str | None = None) -> Score:
    return Score(
        score_id=score_id,
        run_id=run_id,
        span_id=span_id,
        metric_name="accuracy",
        scorer=ScorerKind.DETERMINISTIC,
        scorer_version="v1",
        scored_at=_NOW,
        value_numeric=0.95,
    )


def _make_example(example_id: str, task_id: str = "task1", *, active: bool = True) -> Example:
    return Example(
        example_id=example_id,
        task_id=task_id,
        inputs_hash="b" * 64,
        source=ExampleSource.SYNTHETIC,
        created_at=_NOW,
        active=active,
    )


# ---------------------------------------------------------------------------
# get_run
# ---------------------------------------------------------------------------


def test_get_run_returns_none_when_missing(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        assert adapter.get_run("z" * 32) is None


def test_get_run_returns_run(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        result = adapter.get_run(run.run_id)
        assert result is not None
        assert result.run_id == run.run_id
        assert result.kind == RunKind.ONLINE
        assert result.status == RunStatus.SUCCESS


# ---------------------------------------------------------------------------
# list_runs
# ---------------------------------------------------------------------------


def test_list_runs_empty(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        assert adapter.list_runs() == []


def test_list_runs_returns_all(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32, "task1"), [])
        adapter.write_run(_make_run("b" * 32, "task2"), [])
        results = adapter.list_runs()
        assert len(results) == 2


def test_list_runs_filter_by_task_id(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32, "task1"), [])
        adapter.write_run(_make_run("b" * 32, "task2"), [])
        results = adapter.list_runs(task_id="task1")
        assert len(results) == 1
        assert results[0].task_id == "task1"


def test_list_runs_filter_by_kind(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32), [])
        results = adapter.list_runs(kind="online")
        assert len(results) == 1


def test_list_runs_filter_by_since(tmp_path: Path) -> None:
    future = datetime(2030, 1, 1, tzinfo=UTC)
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32), [])
        results = adapter.list_runs(since=future)
        assert results == []


def test_list_runs_invalid_kind_raises(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        with pytest.raises(ValidationError, match="Invalid kind"):
            adapter.list_runs(kind="bogus")


def test_list_runs_respects_limit(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        for i in range(5):
            adapter.write_run(_make_run(f"{i:032x}"), [])
        results = adapter.list_runs(limit=2)
        assert len(results) == 2


# ---------------------------------------------------------------------------
# get_spans_for_run
# ---------------------------------------------------------------------------


def test_get_spans_for_run_empty(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run(), [])
        assert adapter.get_spans_for_run("a" * 32) == []


def test_get_spans_for_run_returns_spans(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        spans = [_make_span(f"{i:032x}") for i in range(3)]
        adapter.write_run(run, spans)
        results = adapter.get_spans_for_run(run.run_id)
        assert len(results) == 3


def test_get_spans_for_run_with_tokens_and_latency(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        span = _make_span("1" * 32, with_tokens=True, with_latency=True)
        adapter.write_run(run, [span])
        results = adapter.get_spans_for_run(run.run_id)
        assert len(results) == 1
        result = results[0]
        # DB stores tokens_in + tokens_out as a single total, surfaced as tokens_in
        assert result.tokens_in == 15
        assert result.latency_ms == 123.0


def test_get_spans_for_run_null_tokens_and_latency(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        span = _make_span("2" * 32)
        adapter.write_run(run, [span])
        results = adapter.get_spans_for_run(run.run_id)
        assert results[0].tokens_in is None
        assert results[0].latency_ms is None


# ---------------------------------------------------------------------------
# get_scores_for_run
# ---------------------------------------------------------------------------


def test_get_scores_for_run_empty(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run(), [])
        assert adapter.get_scores_for_run("a" * 32) == []


def test_get_scores_for_run_returns_scores(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        adapter.write_score(_make_score("c" * 32))
        results = adapter.get_scores_for_run(run.run_id)
        assert len(results) == 1
        assert results[0].metric_name == "accuracy"
        assert results[0].value_numeric == pytest.approx(0.95)


def test_get_scores_for_run_reconstructs_entity(tmp_path: Path) -> None:
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
        results = adapter.get_scores_for_run(run.run_id)
        assert len(results) == 1
        assert results[0].scorer == ScorerKind.HUMAN
        assert results[0].value_label == "good"
        assert results[0].value_numeric is None


# ---------------------------------------------------------------------------
# list_examples
# ---------------------------------------------------------------------------


def test_list_examples_empty(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        assert adapter.list_examples() == []


def test_list_examples_returns_all(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32, "task1"))
        adapter.write_example(_make_example("f" * 32, "task2"))
        assert len(adapter.list_examples()) == 2


def test_list_examples_filter_by_task_id(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32, "task1"))
        adapter.write_example(_make_example("f" * 32, "task2"))
        results = adapter.list_examples(task_id="task1")
        assert len(results) == 1
        assert results[0].task_id == "task1"


def test_list_examples_filter_by_active(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32, active=True))
        adapter.write_example(_make_example("f" * 32, active=False))
        active = adapter.list_examples(active=True)
        inactive = adapter.list_examples(active=False)
        assert len(active) == 1
        assert len(inactive) == 1
        assert active[0].active is True
        assert inactive[0].active is False


def test_list_examples_reconstructs_entity(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("e" * 32))
        results = adapter.list_examples()
        assert len(results) == 1
        ex = results[0]
        assert ex.source == ExampleSource.SYNTHETIC
        assert ex.inputs_hash == "b" * 64


# ---------------------------------------------------------------------------
# Error paths for write_score / write_example (sqlite.Error branch)
# ---------------------------------------------------------------------------


def test_write_score_sqlite_error_wraps_as_storage_error(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        # Writing a score with a duplicate PK triggers IntegrityError → StorageError
        run = _make_run()
        adapter.write_run(run, [])
        score = _make_score("c" * 32)
        adapter.write_score(score)
        with pytest.raises(StorageError):
            adapter.write_score(score)


def test_write_example_sqlite_error_wraps_as_storage_error(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        ex = _make_example("e" * 32)
        adapter.write_example(ex)
        with pytest.raises(StorageError):
            adapter.write_example(ex)

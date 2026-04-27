"""Tests for StorageReader methods and private helpers (Phase 4 coverage)."""

import sqlite3
from datetime import UTC, datetime, timedelta, timezone
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


# ---------------------------------------------------------------------------
# Task 4.1 — round-trip and enum rehydration
# ---------------------------------------------------------------------------


def test_get_run_datetime_round_trips_byte_identical(tmp_path: Path) -> None:
    """Tz-aware UTC datetime written and read back must be equal."""
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        result = adapter.get_run(run.run_id)
        assert result is not None
        assert result.start_ts == run.start_ts
        assert result.end_ts == run.end_ts


def test_get_run_enum_fields_rehydrate_to_enum_instances(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        result = adapter.get_run(run.run_id)
        assert result is not None
        assert isinstance(result.kind, RunKind)
        assert isinstance(result.status, RunStatus)
        assert result.kind is RunKind.ONLINE
        assert result.status is RunStatus.SUCCESS


def test_get_spans_for_run_nonexistent_returns_empty_list(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        assert adapter.get_spans_for_run("z" * 32) == []


def test_get_spans_for_run_ordered_by_span_id(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        # Insert in reverse lexicographic order; expect ascending on read
        spans = [
            Span(span_id=f"{i:032x}", run_id=run.run_id, kind=SpanKind.TOOL, name=f"s{i}")
            for i in [5, 1, 3, 2, 4]
        ]
        adapter.write_run(run, spans)
        results = adapter.get_spans_for_run(run.run_id)
        ids = [r.span_id for r in results]
        assert ids == sorted(ids)


def test_get_scores_for_run_xor_numeric_field(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        score = _make_score("c" * 32)  # value_numeric only
        adapter.write_score(score)
        results = adapter.get_scores_for_run(run.run_id)
        assert len(results) == 1
        assert results[0].value_numeric is not None
        assert results[0].value_label is None


def test_get_scores_for_run_xor_label_field(tmp_path: Path) -> None:
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
            value_label="pass",
        )
        adapter.write_score(score)
        results = adapter.get_scores_for_run(run.run_id)
        assert len(results) == 1
        assert results[0].value_label is not None
        assert results[0].value_numeric is None


def test_get_run_full_round_trip_all_optional_fields(tmp_path: Path) -> None:
    """All optional Run fields survive a write+read cycle."""
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        parent = Run(
            run_id="b" * 32,
            task_id="task-parent",
            kind=RunKind.ONLINE,
            status=RunStatus.SUCCESS,
            start_ts=_NOW,
            end_ts=_NOW,
        )
        adapter.write_run(parent, [])
        run = Run(
            run_id="a" * 32,
            task_id="task-full",
            kind=RunKind.OFFLINE,
            status=RunStatus.FAILURE,
            start_ts=_NOW,
            end_ts=_NOW,
            parent_run_id="b" * 32,
            orchestrator_model="gpt-4",
            sub_agent_model="claude-3",
            prompt_version="v2",
            tool_schema_version="ts1",
            git_sha="abc123",
            error_type="TimeoutError",
            tokens_in=100,
            tokens_out=50,
            dollar_cost=0.05,
        )
        adapter.write_run(run, [])
        result = adapter.get_run(run.run_id)
        assert result is not None
        assert result.parent_run_id == run.parent_run_id
        assert result.orchestrator_model == run.orchestrator_model
        assert result.sub_agent_model == run.sub_agent_model
        assert result.prompt_version == run.prompt_version
        assert result.tool_schema_version == run.tool_schema_version
        assert result.git_sha == run.git_sha
        assert result.error_type == run.error_type
        assert result.tokens_in == run.tokens_in
        assert result.tokens_out == run.tokens_out
        assert result.dollar_cost == pytest.approx(run.dollar_cost)  # type: ignore[arg-type]
        assert result.kind is RunKind.OFFLINE
        assert result.status is RunStatus.FAILURE


def test_get_span_enum_field_rehydrates(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        run = _make_run()
        span = Span(span_id="1" * 32, run_id=run.run_id, kind=SpanKind.SUBAGENT, name="delegate")
        adapter.write_run(run, [span])
        results = adapter.get_spans_for_run(run.run_id)
        assert len(results) == 1
        assert isinstance(results[0].kind, SpanKind)
        assert results[0].kind is SpanKind.SUBAGENT


# Property-style round-trip tests (covers multiple entity variants without hypothesis)
@pytest.mark.parametrize(
    "run_kind,run_status",
    [
        (RunKind.ONLINE, RunStatus.SUCCESS),
        (RunKind.ONLINE, RunStatus.FAILURE),
        (RunKind.OFFLINE, RunStatus.ABORTED),
        (RunKind.OFFLINE, RunStatus.STALLED),
    ],
)
def test_run_round_trip_enum_variants(
    tmp_path: Path, run_kind: RunKind, run_status: RunStatus
) -> None:
    run_id = f"{hash((run_kind, run_status)) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:032x}"
    run = Run(
        run_id=run_id,
        task_id="task-param",
        kind=run_kind,
        status=run_status,
        start_ts=_NOW,
    )
    with SQLiteStorageAdapter(tmp_path / f"test_{run_kind}_{run_status}.db", clock=_CLOCK) as adapter:
        adapter.write_run(run, [])
        result = adapter.get_run(run.run_id)
        assert result is not None
        assert result.kind == run_kind
        assert result.status == run_status


@pytest.mark.parametrize("span_kind", list(SpanKind))
def test_span_round_trip_kind_variants(tmp_path: Path, span_kind: SpanKind) -> None:
    with SQLiteStorageAdapter(tmp_path / f"test_{span_kind}.db", clock=_CLOCK) as adapter:
        run = _make_run()
        span = Span(span_id="1" * 32, run_id=run.run_id, kind=span_kind, name="test-span")
        adapter.write_run(run, [span])
        results = adapter.get_spans_for_run(run.run_id)
        assert results[0].kind == span_kind


@pytest.mark.parametrize("scorer_kind", list(ScorerKind))
def test_score_round_trip_scorer_variants(tmp_path: Path, scorer_kind: ScorerKind) -> None:
    score_id = f"{hash(scorer_kind) & 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF:032x}"
    with SQLiteStorageAdapter(tmp_path / f"test_{scorer_kind}.db", clock=_CLOCK) as adapter:
        run = _make_run()
        adapter.write_run(run, [])
        score = Score(
            score_id=score_id,
            run_id=run.run_id,
            metric_name="metric",
            scorer=scorer_kind,
            scorer_version="v1",
            scored_at=_NOW,
            value_numeric=1.0,
        )
        adapter.write_score(score)
        results = adapter.get_scores_for_run(run.run_id)
        assert results[0].scorer == scorer_kind


# ---------------------------------------------------------------------------
# Task 4.2 — list ordering, combinator composition, SQL injection guard
# ---------------------------------------------------------------------------


def test_list_runs_ordered_by_start_ts_desc(tmp_path: Path) -> None:
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        for i in range(5):
            run = Run(
                run_id=f"{i:032x}",
                task_id="task",
                kind=RunKind.ONLINE,
                status=RunStatus.SUCCESS,
                start_ts=base + timedelta(minutes=i),
                end_ts=base + timedelta(minutes=i),
            )
            adapter.write_run(run, [])
        results = adapter.list_runs()
        timestamps = [r.start_ts for r in results]
        assert timestamps == sorted(timestamps, reverse=True)


def test_list_runs_combined_filters(tmp_path: Path) -> None:
    """task_id + kind filters compose with AND — only matching rows returned."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(
            Run(run_id="a" * 32, task_id="T1", kind=RunKind.ONLINE, status=RunStatus.SUCCESS, start_ts=base),
            [],
        )
        adapter.write_run(
            Run(run_id="b" * 32, task_id="T1", kind=RunKind.OFFLINE, status=RunStatus.SUCCESS, start_ts=base),
            [],
        )
        adapter.write_run(
            Run(run_id="c" * 32, task_id="T2", kind=RunKind.ONLINE, status=RunStatus.SUCCESS, start_ts=base),
            [],
        )
        results = adapter.list_runs(task_id="T1", kind="online")
        assert len(results) == 1
        assert results[0].run_id == "a" * 32


def test_list_runs_since_task_id_and_kind_combined(tmp_path: Path) -> None:
    """All three filters compose with AND correctly."""
    base = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    later = base + timedelta(hours=1)
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(
            Run(run_id="a" * 32, task_id="T1", kind=RunKind.ONLINE, status=RunStatus.SUCCESS, start_ts=base),
            [],
        )
        adapter.write_run(
            Run(run_id="b" * 32, task_id="T1", kind=RunKind.ONLINE, status=RunStatus.SUCCESS, start_ts=later),
            [],
        )
        # Only the later run satisfies all three filters
        results = adapter.list_runs(task_id="T1", kind="online", since=later)
        assert len(results) == 1
        assert results[0].run_id == "b" * 32


def test_list_runs_kind_rehydrates_to_enum(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32), [])
        results = adapter.list_runs(kind="online")
        assert len(results) == 1
        assert isinstance(results[0].kind, RunKind)
        assert results[0].kind is RunKind.ONLINE


def test_list_examples_active_and_task_combined(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_example(_make_example("a" * 32, "T1", active=True))
        adapter.write_example(_make_example("b" * 32, "T1", active=False))
        adapter.write_example(_make_example("c" * 32, "T2", active=True))
        results = adapter.list_examples(task_id="T1", active=True)
        assert len(results) == 1
        assert results[0].example_id == "a" * 32


def test_list_runs_hostile_task_id_returns_empty(tmp_path: Path) -> None:
    """SQL injection via task_id must not leak rows — parameterization must hold."""
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32, "safe_task"), [])
        # A naive string-concat query would return the run; parameterized query returns nothing
        results = adapter.list_runs(task_id="x' OR 1=1 --")
        assert results == []


def test_list_runs_hostile_kind_raises_validation_error_before_sql(tmp_path: Path) -> None:
    """Hostile kind value rejected before reaching SQL."""
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_CLOCK) as adapter:
        adapter.write_run(_make_run("a" * 32), [])
        with pytest.raises(ValidationError):
            adapter.list_runs(kind="x' OR 1=1 --")

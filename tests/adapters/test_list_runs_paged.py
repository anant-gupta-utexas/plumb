"""Tests for SQLiteStorageAdapter.list_runs_with_counts_paged (T2.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Run, RunKind, RunStatus, Score, ScorerKind, Span, SpanKind


class _Clock:
    def __init__(self, t: datetime) -> None:
        self._t = t

    def now(self) -> datetime:
        return self._t


_BASE = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _run(run_id: str, task_id: str = "t", kind: RunKind = RunKind.OFFLINE, offset_s: int = 0) -> Run:
    start = _BASE + timedelta(seconds=offset_s)
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=kind,
        status=RunStatus.SUCCESS,
        start_ts=start,
        end_ts=start + timedelta(seconds=5),
    )


def _adapter(tmp_path: Path) -> SQLiteStorageAdapter:
    return SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_Clock(_BASE))


# ---------------------------------------------------------------------------
# Basic paging
# ---------------------------------------------------------------------------


def test_paged_empty(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    rows, total = adapter.list_runs_with_counts_paged(limit=10, offset=0)
    assert rows == []
    assert total == 0


def test_paged_returns_all_on_single_page(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for i in range(5):
        adapter.write_run(_run(format(i, "032x")), [])
    rows, total = adapter.list_runs_with_counts_paged(limit=10, offset=0)
    assert len(rows) == 5
    assert total == 5


def test_paged_limit_enforced(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for i in range(10):
        adapter.write_run(_run(format(i, "032x")), [])
    rows, total = adapter.list_runs_with_counts_paged(limit=3, offset=0)
    assert len(rows) == 3
    assert total == 10


def test_paged_offset_advances(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for i in range(5):
        adapter.write_run(_run(format(i, "032x"), offset_s=i), [])
    page1, _ = adapter.list_runs_with_counts_paged(limit=2, offset=0)
    page2, _ = adapter.list_runs_with_counts_paged(limit=2, offset=2)
    ids1 = {r.run_id for r in page1}
    ids2 = {r.run_id for r in page2}
    assert ids1.isdisjoint(ids2)


def test_paged_len_leq_limit(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for i in range(10):
        adapter.write_run(_run(format(i, "032x")), [])
    for limit in (1, 3, 5, 100):
        rows, _ = adapter.list_runs_with_counts_paged(limit=limit, offset=0)
        assert len(rows) <= limit


def test_paged_len_leq_max_0_total_minus_offset(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    for i in range(7):
        adapter.write_run(_run(format(i, "032x")), [])
    rows, total = adapter.list_runs_with_counts_paged(limit=10, offset=5)
    assert len(rows) <= max(0, total - 5)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


def test_paged_kind_filter(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.write_run(_run("a" * 32, kind=RunKind.OFFLINE), [])
    adapter.write_run(_run("b" * 32, kind=RunKind.ONLINE), [])
    rows, total = adapter.list_runs_with_counts_paged(kind="offline", limit=10, offset=0)
    assert total == 1
    assert all(r.kind == "offline" for r in rows)


def test_paged_task_id_filter(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.write_run(_run("a" * 32, task_id="alpha"), [])
    adapter.write_run(_run("b" * 32, task_id="beta"), [])
    rows, total = adapter.list_runs_with_counts_paged(task_id="alpha", limit=10, offset=0)
    assert total == 1
    assert rows[0].task_id == "alpha"


def test_paged_since_filter(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    old = _run("a" * 32, offset_s=-3600)
    new = _run("b" * 32, offset_s=0)
    adapter.write_run(old, [])
    adapter.write_run(new, [])
    cutoff = _BASE - timedelta(seconds=1800)
    rows, total = adapter.list_runs_with_counts_paged(since=cutoff, limit=10, offset=0)
    assert total == 1
    assert rows[0].run_id == "b" * 32


# ---------------------------------------------------------------------------
# Count / span / score fields
# ---------------------------------------------------------------------------


def test_paged_span_and_score_counts(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    run = _run("a" * 32)
    span = Span(span_id="b" * 32, run_id="a" * 32, kind=SpanKind.LLM, name="s")
    score = Score(
        score_id="c" * 32,
        run_id="a" * 32,
        metric_name="m",
        scorer=ScorerKind.JUDGE,
        scorer_version="v1",
        scored_at=_BASE,
        value_numeric=0.5,
    )
    adapter.write_run(run, [span])
    adapter.write_score(score)
    rows, _ = adapter.list_runs_with_counts_paged(limit=10, offset=0)
    assert rows[0].span_count == 1
    assert rows[0].score_count == 1


# ---------------------------------------------------------------------------
# RunSummaryRow entity
# ---------------------------------------------------------------------------


def test_run_summary_row_fields(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    adapter.write_run(_run("a" * 32, task_id="my.task"), [])
    rows, _ = adapter.list_runs_with_counts_paged(limit=1, offset=0)
    r = rows[0]
    assert r.run_id == "a" * 32
    assert r.task_id == "my.task"
    assert r.kind == "offline"
    assert r.status == "success"
    assert r.span_count == 0
    assert r.score_count == 0

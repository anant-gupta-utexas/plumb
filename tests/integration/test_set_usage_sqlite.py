"""Integration tests for RunHandle.set_usage against real SQLite (Task 9).

Covers AC-USAGE-1/2/3, FR-USAGE-4 (resume-boundary last-wins), FR-USAGE-5
(no-op after abort + fail-degrade on storage error), and the
aggregate_runs_for_task dollar_cost_total wiring.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import RunKind, SpanKind
from plumb.core.errors import StorageError


class _FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2024, 1, 1, tzinfo=UTC)
        self._step = 0

    def now(self) -> datetime:
        ts = self._t + timedelta(seconds=self._step)
        self._step += 1
        return ts


@pytest.fixture()
def real_adapter(tmp_path: Path) -> SQLiteStorageAdapter:
    adapter = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_FakeClock())
    yield adapter
    adapter.close()


@pytest.fixture()
def configured_real_api(
    monkeypatch: pytest.MonkeyPatch,
    real_adapter: SQLiteStorageAdapter,
) -> SQLiteStorageAdapter:
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    monkeypatch.setattr(_api, "_clock", real_adapter._clock)
    yield real_adapter


def test_explicit_usage_round_trips(configured_real_api: SQLiteStorageAdapter) -> None:
    """AC-USAGE-1: explicit set_usage values land verbatim on the runs row and
    feed into the task's dollar_cost_total aggregate."""
    with _api.run(task_id="t1") as r:
        r.set_usage(tokens_in=100, tokens_out=250, dollar_cost=0.0123)

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in == 100
    assert row.tokens_out == 250
    assert row.dollar_cost == 0.0123

    agg = configured_real_api.aggregate_runs_for_task("t1")
    assert agg.dollar_cost_total == pytest.approx(0.0123)


def test_tokens_auto_fill_from_spans_dollar_cost_stays_null(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    """AC-USAGE-2: two spans (10,25) and (5,30), set_usage never called ->
    tokens_in==15, tokens_out==55 auto-filled; dollar_cost stays NULL."""
    with _api.run(task_id="t2") as r:
        r.add_span(SpanKind.LLM, "gen-1", tokens=(10, 25))
        r.add_span(SpanKind.LLM, "gen-2", tokens=(5, 30))

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in == 15
    assert row.tokens_out == 55
    assert row.dollar_cost is None


def test_explicit_set_usage_wins_no_summing(configured_real_api: SQLiteStorageAdapter) -> None:
    """AC-USAGE-3: spans totalling tokens_in=15, then set_usage(tokens_in=999)
    called before close -> runs.tokens_in==999 (explicit wins, no summing)."""
    with _api.run(task_id="t3") as r:
        r.add_span(SpanKind.LLM, "gen-1", tokens=(10, 25))
        r.add_span(SpanKind.LLM, "gen-2", tokens=(5, 30))
        r.set_usage(tokens_in=999)

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in == 999
    assert row.tokens_out is None


def test_legacy_shape_spans_excluded_from_derivation(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    """A run with only legacy-shape buffered spans (tokens_in IS NULL) and no
    set_usage closes with tokens excluded from derivation, no fabricated split."""
    with _api.run(task_id="t4") as r:
        r.add_span(SpanKind.LLM, "gen-1")  # no tokens at all

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in is None
    assert row.tokens_out is None


def test_set_usage_noop_after_abort(configured_real_api: SQLiteStorageAdapter) -> None:
    """FR-USAGE-5: set_usage is a no-op after abort()."""
    with _api.run(task_id="t5") as r:
        r.abort("stop")
        r.set_usage(tokens_in=100, tokens_out=200, dollar_cost=5.0)

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in is None
    assert row.tokens_out is None
    assert row.dollar_cost is None


def test_storage_failure_on_finalize_does_not_raise(
    configured_real_api: SQLiteStorageAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-USAGE-5: a storage failure on the usage write fail-degrades
    (never raises into caller)."""
    broken = MagicMock(spec=SQLiteStorageAdapter)
    broken.finalize_run.side_effect = StorageError("disk full")
    broken.open_run = configured_real_api.open_run
    monkeypatch.setattr(_api, "_storage_writer", broken)

    with _api.run(task_id="t6") as r:
        r.set_usage(tokens_in=1, tokens_out=2, dollar_cost=1.0)
    # no exception raised into caller — the with-block above completing is the assertion


def test_resume_boundary_last_wins_not_accumulated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR-USAGE-4: on a resume_run-resumed run, set_usage is last-wins
    overwrite (not accumulation) across the resume boundary."""
    db_path = tmp_path / "plumb.db"

    clock_a = _FakeClock()
    adapter_a = SQLiteStorageAdapter(db_path, clock=clock_a)
    monkeypatch.setattr(_api, "_storage", adapter_a)
    monkeypatch.setattr(_api, "_storage_writer", adapter_a)
    monkeypatch.setattr(_api, "_clock", clock_a)

    run_id = "a" * 32
    original_start = clock_a.now()
    adapter_a.open_run(run_id, "t7", RunKind.ONLINE, None, original_start)
    adapter_a.close()

    clock_b = _FakeClock(start=original_start + timedelta(hours=1))
    adapter_b = SQLiteStorageAdapter(db_path, clock=clock_b)
    monkeypatch.setattr(_api, "_storage", adapter_b)
    monkeypatch.setattr(_api, "_storage_writer", adapter_b)
    monkeypatch.setattr(_api, "_clock", clock_b)

    with _api.resume_run(run_id) as r:
        r.set_usage(tokens_in=10, tokens_out=20, dollar_cost=1.0)
        r.set_usage(tokens_in=999)

    row = adapter_b.get_run(run_id)
    assert row is not None
    assert row.tokens_in == 999  # last explicit call wins, not merged/accumulated
    assert row.tokens_out == 20
    assert row.dollar_cost == 1.0

    adapter_b.close()

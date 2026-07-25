"""Task 13: migrated-DB regression fixture.

Builds a v1.0-shaped DB, runs it through `_bootstrap_schema`'s 1->2
migration, and re-runs the schema-shape-relevant subset of the existing
v1.0 TRD §13 acceptance-criteria suite (AC-API-2, run-close behavior,
storage-failure swallow) against the resulting migrated file — the concrete
implementation of TRD §18 Phase 2's exit criterion "all §13 v1.0 ACs still
pass against a migrated database (no regression)."

AC-SCHEMA-1 ("no migration runs") is v1.0-specific by construction and does
not apply to a v1.1 build opening a v1.0 DB — that is exactly what Task 2's
`tests/integration/test_migration_1_to_2.py` already covers as AC-MIG-1/2.
AC-REL-2 (SIGKILL durability) spawns a subprocess against a fresh DB and
isn't schema-shape-parametrizable; it stays in
`tests/integration/test_sigkill_durability.py` unchanged. AC-PERF-*,
AC-INT-*, AC-SEC-* are judge/HTTP/perf-specific and orthogonal to the
1->2 migration; not re-run here.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import plumb.api as _api
from plumb.adapters._pragmas import apply_pragmas
from plumb.adapters._schema import DDL_STATEMENTS
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.errors import StorageError

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_v1_db(db_path: Path) -> None:
    """Build a v1.0-shaped DB: v1 DDL only, user_version=1, no migration columns."""
    conn = sqlite3.connect(str(db_path))
    apply_pragmas(conn)
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


class _FakeClock:
    def __init__(self) -> None:
        self._step = 0

    def now(self) -> datetime:
        ts = _NOW + timedelta(seconds=self._step)
        self._step += 1
        return ts


@pytest.fixture(params=["fresh", "migrated"])
def real_adapter(request: pytest.FixtureRequest, tmp_path: Path) -> SQLiteStorageAdapter:
    """A SQLiteStorageAdapter over either a brand-new v1.1 DB or a v1.0 DB
    that has just been migrated in place — the reusable fixture this task
    builds. Every test parametrized over this fixture runs twice."""
    db_path = tmp_path / "plumb.db"
    if request.param == "migrated":
        _make_v1_db(db_path)
    adapter = SQLiteStorageAdapter(db_path, clock=_FakeClock())
    yield adapter
    adapter.close()


@pytest.fixture
def configured_real_api(
    monkeypatch: pytest.MonkeyPatch,
    real_adapter: SQLiteStorageAdapter,
) -> SQLiteStorageAdapter:
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    yield real_adapter


# ---------------------------------------------------------------------------
# AC-API-2: sync + async @run / with run(...) writes correct rows
# ---------------------------------------------------------------------------


def test_sync_run_writes_run_row(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="t1") as r:
        r.add_span("llm", "generate", latency_ms=10.0)
        r.add_span("tool", "search", latency_ms=5.0)

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.task_id == "t1"
    assert row.status.value == "success"
    assert row.start_ts < row.end_ts

    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 2


@pytest.mark.asyncio
async def test_async_run_writes_run_row(configured_real_api: SQLiteStorageAdapter) -> None:
    async with _api.run(task_id="async_task") as r:
        r.add_span("llm", "async_generate")

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.task_id == "async_task"
    assert row.status.value == "success"
    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 1


def test_nested_run_both_rows_committed(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="parent_task") as parent, _api.run(task_id="child_task") as child:
        child.add_span("llm", "inner")

    parent_row = configured_real_api.get_run(parent.run_id)
    child_row = configured_real_api.get_run(child.run_id)
    assert parent_row is not None
    assert child_row is not None
    assert child_row.parent_run_id == parent.run_id


# ---------------------------------------------------------------------------
# abort() / exception -> status transitions
# ---------------------------------------------------------------------------


def test_abort_writes_aborted_status(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="abort_task") as r:
        r.add_span("llm", "partial_span")
        r.abort("something_went_wrong")

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.status.value == "aborted"
    assert row.error_type == "something_went_wrong"
    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 1


def test_exception_writes_failure_status(configured_real_api: SQLiteStorageAdapter) -> None:
    run_id_holder: list[str] = []

    with pytest.raises(ValueError), _api.run(task_id="failing_task") as r:
        run_id_holder.append(r.run_id)
        raise ValueError("boom")

    row = configured_real_api.get_run(run_id_holder[0])
    assert row is not None
    assert row.status.value == "failure"
    assert row.error_type == "ValueError"


# ---------------------------------------------------------------------------
# AC-REL-1 (partial): StorageError on finalize_run is swallowed
# ---------------------------------------------------------------------------


def test_storage_error_does_not_raise_into_caller(
    real_adapter: SQLiteStorageAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-REL-1: caller's control flow is unaffected by a storage failure,
    regardless of whether the underlying DB is fresh or migrated."""
    failing_writer = MagicMock()
    failing_writer.open_run.return_value = None
    failing_writer.finalize_run.side_effect = StorageError("disk full")

    monkeypatch.setattr(_api, "_storage", failing_writer)
    monkeypatch.setattr(_api, "_storage_writer", failing_writer)

    result_holder: list[str] = []
    with _api.run(task_id="rel1_task") as _r:
        result_holder.append("body_ran")

    assert result_holder == ["body_ran"]
    failing_writer.finalize_run.assert_called_once()


# ---------------------------------------------------------------------------
# v1.1 surface also works unchanged against a migrated DB
# ---------------------------------------------------------------------------


def test_v11_features_work_against_both_fresh_and_migrated(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    with _api.run(task_id="v11_task") as r:
        r.add_span("llm", "gen", tokens=(10, 20), attributes={"lane": "planned"})
        r.add_score("accuracy", "deterministic", value_numeric=0.9, rationale="looks right")
        r.set_usage(dollar_cost=0.005)
        r.add_example("a" * 64, source="synthetic")

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.tokens_in == 10  # auto-filled from the single span
    assert row.dollar_cost == 0.005

    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert spans[0].attributes == {"lane": "planned"}

    scores = configured_real_api.get_scores_for_run(r.run_id)
    assert scores[0].rationale == "looks right"

    examples = configured_real_api.list_examples(task_id="v11_task")
    assert len(examples) == 1

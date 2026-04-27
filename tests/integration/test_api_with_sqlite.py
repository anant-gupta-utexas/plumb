"""Integration tests: full @run / with run(...) cycle against a real SQLite DB.

Covers Task 6.3 ACs:
- sync and async @run writes 1 runs row + spans to a tmp_path DB
- nested decorator: 2 rows; child has correct parent_run_id
- r.add_score(...) writes a scores row
- r.abort("reason") flushes partial buffer with status='aborted'
- All v1 Core+API ACs (AC-API-1, AC-API-2) re-run green with real adapter
- Storage-failure path: monkeypatched adapter; caller's return value unchanged (AC-REL-1)
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.errors import StorageError

# ---------------------------------------------------------------------------
# Fixture: real adapter bound to tmp_path
# ---------------------------------------------------------------------------


class _FakeClock:
    def __init__(self) -> None:
        self._step = 0

    def now(self) -> datetime:
        from datetime import timedelta

        ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=self._step)
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
    """Wire plumb.api to use a real SQLiteStorageAdapter against tmp_path."""
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    yield real_adapter


# ---------------------------------------------------------------------------
# Sync context-manager: 1 run row + spans
# ---------------------------------------------------------------------------


def test_sync_run_writes_run_row(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="t1") as r:
        r.add_span("llm", "generate", latency_ms=10.0)
        r.add_span("tool", "search", latency_ms=5.0)

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.task_id == "t1"
    assert row.status.value == "success"

    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 2
    names = {s.name for s in spans}
    assert names == {"generate", "search"}


def test_sync_run_zero_spans(configured_real_api: SQLiteStorageAdapter) -> None:
    """FR-EDGE-3: run with 0 spans is valid."""
    with _api.run(task_id="no_spans") as r:
        pass

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert spans == []


# ---------------------------------------------------------------------------
# Async context-manager
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_run_writes_run_row(configured_real_api: SQLiteStorageAdapter) -> None:
    """AC-API-2 async variant with real adapter."""
    async with _api.run(task_id="async_task") as r:
        r.add_span("llm", "async_generate")

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.task_id == "async_task"
    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 1


# ---------------------------------------------------------------------------
# Decorator (sync)
# ---------------------------------------------------------------------------


def test_sync_decorator_writes_run_row(configured_real_api: SQLiteStorageAdapter) -> None:
    run_id_holder: list[str] = []

    @_api.run(task_id="decorated_task")
    def my_fn() -> str:
        # Capture run_id from the context
        handle = _api._active_run.get()
        assert handle is not None
        run_id_holder.append(handle.run_id)
        return "ok"

    result = my_fn()
    assert result == "ok"

    assert len(run_id_holder) == 1
    row = configured_real_api.get_run(run_id_holder[0])
    assert row is not None
    assert row.status.value == "success"


# ---------------------------------------------------------------------------
# Nested runs: FR-GRAPH-1 — both rows committed with correct parent_run_id
#
# The two-phase write (open_run at __enter__, finalize_run at __exit__) ensures
# the parent pending row is already in the DB when the child's open_run fires,
# so the self-referential FK on parent_run_id is always satisfied.
# ---------------------------------------------------------------------------


def test_nested_run_both_rows_committed(configured_real_api: SQLiteStorageAdapter) -> None:
    """FR-GRAPH-1: nested runs produce 2 rows; child.parent_run_id == parent.run_id."""
    with _api.run(task_id="parent") as parent, _api.run(task_id="child") as child:
        assert child.parent_run_id == parent.run_id

    parent_row = configured_real_api.get_run(parent.run_id)
    child_row = configured_real_api.get_run(child.run_id)

    assert parent_row is not None, "parent run row missing from DB"
    assert child_row is not None, "child run row missing — FK ordering broken"
    assert child_row.parent_run_id == parent_row.run_id
    assert parent_row.status.value == "success"
    assert child_row.status.value == "success"


def test_nested_run_three_levels(configured_real_api: SQLiteStorageAdapter) -> None:
    """Three levels of nesting: grandchild → child → parent, all rows present."""
    with _api.run(task_id="grandparent") as gp, _api.run(task_id="parent") as p:  # noqa: SIM117
        with _api.run(task_id="child") as c:
            pass

    gp_row = configured_real_api.get_run(gp.run_id)
    p_row = configured_real_api.get_run(p.run_id)
    c_row = configured_real_api.get_run(c.run_id)

    assert gp_row is not None
    assert p_row is not None
    assert c_row is not None
    assert p_row.parent_run_id == gp_row.run_id
    assert c_row.parent_run_id == p_row.run_id


# ---------------------------------------------------------------------------
# add_score → scores row
# ---------------------------------------------------------------------------


def test_add_score_writes_scores_row(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="scored_task") as r:
        r.add_score(
            "accuracy",
            "deterministic",
            value_numeric=0.95,
            scorer_version="v1",
        )

    scores = configured_real_api.get_scores_for_run(r.run_id)
    assert len(scores) == 1
    assert scores[0].metric_name == "accuracy"
    assert scores[0].value_numeric == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# abort → status='aborted', error_type set
# ---------------------------------------------------------------------------


def test_abort_writes_aborted_status(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="abort_task") as r:
        r.add_span("llm", "partial_span")
        r.abort("something_went_wrong")

    row = configured_real_api.get_run(r.run_id)
    assert row is not None
    assert row.status.value == "aborted"
    assert row.error_type == "something_went_wrong"

    # Buffered span before abort must still be persisted
    spans = configured_real_api.get_spans_for_run(r.run_id)
    assert len(spans) == 1


# ---------------------------------------------------------------------------
# Exception in body → status='failure'
# ---------------------------------------------------------------------------


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
# AC-REL-1 (partial): StorageError swallowed — return value unchanged
# ---------------------------------------------------------------------------


def test_storage_error_does_not_raise_into_caller(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Simulates StorageError on finalize_run; caller's return value unchanged (AC-REL-1)."""
    failing_writer = MagicMock()
    failing_writer.open_run.return_value = None
    failing_writer.finalize_run.side_effect = StorageError("disk full")

    monkeypatch.setattr(_api, "_storage", failing_writer)
    monkeypatch.setattr(_api, "_storage_writer", failing_writer)

    result_holder: list[str] = []

    with _api.run(task_id="rel1_task") as _r:
        result_holder.append("body_ran")

    # The with-block body must have executed
    assert result_holder == ["body_ran"]
    # finalize_run must have been attempted
    failing_writer.finalize_run.assert_called_once()


# ---------------------------------------------------------------------------
# list_runs: multiple runs queryable after writes
# ---------------------------------------------------------------------------


def test_list_runs_returns_written_rows(configured_real_api: SQLiteStorageAdapter) -> None:
    for i in range(3):
        with _api.run(task_id=f"task_{i}"):
            pass

    rows = configured_real_api.list_runs(limit=10)
    assert len(rows) >= 3
    task_ids = {r.task_id for r in rows}
    assert {"task_0", "task_1", "task_2"}.issubset(task_ids)

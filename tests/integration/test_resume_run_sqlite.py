"""Integration tests for plumb.resume_run against a real SQLite file.

Simulates cross-process resume (AC-RESUME-1) by opening two sequential
SQLiteStorageAdapter instances against the same on-disk file — process A opens
+ leaves a run pending, process B resumes it and finalizes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import RunKind, SpanKind
from plumb.core.errors import NotFoundError, ValidationError


class _FakeClock:
    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2024, 1, 1, tzinfo=UTC)
        self._step = 0

    def now(self) -> datetime:
        ts = self._t + timedelta(seconds=self._step)
        self._step += 1
        return ts


def test_cross_process_resume_adds_spans_and_preserves_start_ts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC-RESUME-1: run opened in process A with 3 spans; process B's
    resume_run adds 2 more spans; exactly one runs row, 5 spans total,
    original start_ts unchanged, end_ts reflects process-B exit time."""
    db_path = tmp_path / "plumb.db"

    # Process A: open a run, add 3 spans via the normal run() flow, but leave
    # the row pending by re-inserting it directly (run() would finalize it).
    clock_a = _FakeClock()
    adapter_a = SQLiteStorageAdapter(db_path, clock=clock_a)
    monkeypatch.setattr(_api, "_storage", adapter_a)
    monkeypatch.setattr(_api, "_storage_writer", adapter_a)
    monkeypatch.setattr(_api, "_clock", clock_a)

    run_id = "a" * 32
    original_start = clock_a.now()
    adapter_a.open_run(run_id, "task1", RunKind.ONLINE, None, original_start)
    # Simulate 3 spans already buffered by process A before it went pending —
    # write them directly since process A never reached finalize_run.
    from plumb.core.entities import Span

    for i in range(3):
        span = Span(span_id=f"{i:032x}", run_id=run_id, kind=SpanKind.LLM, name=f"span-{i}")
        adapter_a._conn.execute(
            "INSERT INTO spans (span_id, run_id, kind, name) VALUES (?, ?, ?, ?)",
            (span.span_id, span.run_id, span.kind.value, span.name),
        )
    adapter_a.close()

    # Process B: resume the same run_id, add 2 more spans, close.
    clock_b = _FakeClock(start=original_start + timedelta(hours=1))
    adapter_b = SQLiteStorageAdapter(db_path, clock=clock_b)
    monkeypatch.setattr(_api, "_storage", adapter_b)
    monkeypatch.setattr(_api, "_storage_writer", adapter_b)
    monkeypatch.setattr(_api, "_clock", clock_b)

    with _api.resume_run(run_id) as r:
        assert r.run_id == run_id
        r.add_span(SpanKind.LLM, "generate-1")
        r.add_span(SpanKind.TOOL, "search")

    # exactly one runs row
    all_runs = adapter_b.list_runs()
    assert len(all_runs) == 1

    final = adapter_b.get_run(run_id)
    assert final is not None
    assert final.status.value == "success"
    assert final.start_ts == original_start  # start_ts preserved across resume
    assert final.end_ts is not None and final.end_ts > original_start

    spans = adapter_b.get_spans_for_run(run_id)
    assert len(spans) == 5  # 3 from process A + 2 from process B

    adapter_b.close()


def test_resume_nonexistent_run_raises_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    adapter = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_FakeClock())
    monkeypatch.setattr(_api, "_storage", adapter)
    monkeypatch.setattr(_api, "_storage_writer", adapter)

    with pytest.raises(NotFoundError):
        with _api.resume_run("z" * 32):
            pass

    adapter.close()


def test_resume_terminal_run_raises_validation_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    clock = _FakeClock()
    adapter = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=clock)
    monkeypatch.setattr(_api, "_storage", adapter)
    monkeypatch.setattr(_api, "_storage_writer", adapter)
    monkeypatch.setattr(_api, "_clock", clock)

    with _api.run(task_id="t"):
        pass  # finalizes to 'success' — a real completed run

    run_id = adapter.list_runs(limit=1)[0].run_id
    with pytest.raises(ValidationError, match="already terminal"):
        with _api.resume_run(run_id):
            pass

    adapter.close()

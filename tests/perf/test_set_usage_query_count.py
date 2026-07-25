"""NFR-USAGE-1/2: set_usage introduces no additional SQL query at finalize
time — the tokens_in/tokens_out/dollar_cost fields ride the same
finalize_run UPDATE that already exists, regardless of whether set_usage was
called (Task 9).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import SpanKind


class _FakeClock:
    def __init__(self) -> None:
        self._t = datetime(2024, 1, 1, tzinfo=UTC)
        self._step = 0

    def now(self) -> datetime:
        ts = self._t + timedelta(seconds=self._step)
        self._step += 1
        return ts


def _count_statements(adapter: SQLiteStorageAdapter, run_body) -> int:
    statements: list[str] = []
    adapter._conn.set_trace_callback(statements.append)
    try:
        run_body()
    finally:
        adapter._conn.set_trace_callback(None)
    return len(statements)


@pytest.mark.perf
def test_set_usage_adds_no_extra_query(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    clock = _FakeClock()
    adapter = SQLiteStorageAdapter(tmp_path / "perf.db", clock=clock)
    monkeypatch.setattr(_api, "_storage", adapter)
    monkeypatch.setattr(_api, "_storage_writer", adapter)
    monkeypatch.setattr(_api, "_clock", clock)

    def without_set_usage() -> None:
        with _api.run(task_id="t") as r:
            r.add_span(SpanKind.LLM, "gen", tokens=(10, 20))

    def with_set_usage() -> None:
        with _api.run(task_id="t") as r:
            r.add_span(SpanKind.LLM, "gen", tokens=(10, 20))
            r.set_usage(tokens_in=999, tokens_out=888, dollar_cost=1.23)

    n_without = _count_statements(adapter, without_set_usage)
    n_with = _count_statements(adapter, with_set_usage)

    adapter.close()

    assert n_with == n_without, (
        f"set_usage changed the finalize-time statement count: without={n_without} with={n_with}"
    )

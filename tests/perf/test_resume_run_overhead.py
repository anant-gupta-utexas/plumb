"""NFR-RESUME-1: resume_run open overhead benchmark (Task 6).

resume_run's open (open_or_resume SELECT + status validation) adds <=5ms p95
over run()'s existing open path (open_run INSERT).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import RunKind


class _FakeClock:
    def __init__(self) -> None:
        self._t = datetime(2024, 1, 1, tzinfo=UTC)
        self._step = 0

    def now(self) -> datetime:
        ts = self._t + timedelta(seconds=self._step)
        self._step += 1
        return ts


@pytest.mark.perf
def test_resume_run_open_overhead_within_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    N = 200
    BUDGET_MS = 5.0

    clock = _FakeClock()
    adapter = SQLiteStorageAdapter(
        tmp_path / "perf.db", clock=clock, pragma_overrides={"synchronous": "OFF"}
    )
    monkeypatch.setattr(_api, "_storage", adapter)
    monkeypatch.setattr(_api, "_storage_writer", adapter)
    monkeypatch.setattr(_api, "_clock", clock)

    run_ids = [f"{i:032x}" for i in range(N)]
    for run_id in run_ids:
        adapter.open_run(run_id, "perf-bench", RunKind.ONLINE, None, clock.now())

    run_open_latencies_ms: list[float] = []
    for i in range(N):
        rid = f"{(N + i):032x}"
        t0 = time.perf_counter()
        adapter.open_run(rid, "perf-bench", RunKind.ONLINE, None, clock.now())
        t1 = time.perf_counter()
        run_open_latencies_ms.append((t1 - t0) * 1000.0)
        adapter.finalize_run(rid, _api.RunStatus.SUCCESS, clock.now(), [])

    resume_open_latencies_ms: list[float] = []
    for run_id in run_ids:
        t0 = time.perf_counter()
        with _api.resume_run(run_id):
            pass
        t1 = time.perf_counter()
        resume_open_latencies_ms.append((t1 - t0) * 1000.0)

    adapter.close()

    run_open_latencies_ms.sort()
    resume_open_latencies_ms.sort()
    run_p95 = run_open_latencies_ms[int(N * 0.95)]
    resume_p95 = resume_open_latencies_ms[int(N * 0.95)]
    delta_ms = resume_p95 - run_p95

    print(
        f"\nopen overhead (N={N}): run()-open p95={run_p95:.3f}ms  "
        f"resume_run p95(full open+close)={resume_p95:.3f}ms  delta={delta_ms:.3f}ms"
    )

    assert delta_ms <= BUDGET_MS, (
        f"resume_run open overhead {delta_ms:.3f}ms exceeds budget of {BUDGET_MS}ms"
    )

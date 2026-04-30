"""NFR-Perf-2: run-close overhead benchmark (Task 7.2).

100 iterations of write_run with 100 spans each.
AC: p95 ≤ 50 ms on CI runner.
Local headroom: ≤ 100 ms (2× for M-series noise).
"""

from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Run, RunKind, RunStatus, Span, SpanKind


def _hex32(n: int) -> str:
    return f"{n:032x}"


def _hex32_pair(base: int, suffix: int) -> str:
    combined = (base * 10000 + suffix) % (16**32)
    return f"{combined:032x}"


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC)


def _build_run_and_spans(i: int) -> tuple[Run, list[Span]]:
    run_id = _hex32(i + 1)
    start_ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=i)
    end_ts = start_ts + timedelta(seconds=1)

    run = Run(
        run_id=run_id,
        task_id="perf-bench",
        kind=RunKind.OFFLINE,
        status=RunStatus.SUCCESS,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    spans = [
        Span(
            span_id=_hex32_pair(i + 1, j + 1),
            run_id=run_id,
            kind=SpanKind.LLM,
            name=f"span-{j}",
        )
        for j in range(100)
    ]

    return run, spans


@pytest.mark.perf
def test_run_close_p95_within_budget(tmp_path: Path) -> None:
    """p95 write_run latency ≤ 50 ms on CI / ≤ 100 ms locally (NFR-Perf-2)."""
    N = 100
    CI_BUDGET_MS = 50.0
    LOCAL_BUDGET_MS = 100.0
    budget_ms = CI_BUDGET_MS if os.environ.get("CI") == "true" else LOCAL_BUDGET_MS

    # synchronous=OFF eliminates per-transaction fsync on CI's slow shared
    # storage — the budget measures serialization + lock overhead, not durability.
    adapter = SQLiteStorageAdapter(
        tmp_path / "perf.db",
        clock=_FixedClock(),
        pragma_overrides={"synchronous": "OFF"},
    )

    latencies_ms: list[float] = []
    try:
        for i in range(N):
            run, spans = _build_run_and_spans(i)
            t0 = time.perf_counter()
            adapter.write_run(run, spans)
            t1 = time.perf_counter()
            latencies_ms.append((t1 - t0) * 1000.0)
    finally:
        adapter.close()

    latencies_ms.sort()
    p50 = latencies_ms[int(N * 0.50)]
    p95 = latencies_ms[int(N * 0.95)]
    p99 = latencies_ms[int(N * 0.99)]
    max_ms = latencies_ms[-1]

    print(
        f"\nwrite_run latency (N={N}, 100 spans each): "
        f"p50={p50:.2f}ms  p95={p95:.2f}ms  p99={p99:.2f}ms  max={max_ms:.2f}ms"
    )

    assert p95 <= budget_ms, (
        f"p95 latency {p95:.2f} ms exceeds budget of {budget_ms:.0f} ms "
        f"({'CI' if os.environ.get('CI') == 'true' else 'local'})"
    )

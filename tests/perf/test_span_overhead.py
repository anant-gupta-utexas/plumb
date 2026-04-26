"""NFR-Perf-1: add_span overhead benchmark (Task 7.1).

10,000 add_span calls inside one `with run(...)` block backed by a FakeStorageWriter.
AC: p95 ≤ 1 ms locally (M-series); ≤ 2 ms on CI runners.
"""

from __future__ import annotations

import time
from collections.abc import Sequence

import pytest

import plumb.api as _api
from plumb.api import run
from plumb.core.entities import Run, Score, Span, SpanKind


class _NullWriter:
    """Absolute minimal writer — no list appends, no overhead."""

    def write_run(self, run: Run, spans: Sequence[Span]) -> None:
        pass

    def write_score(self, score: Score) -> None:
        pass

    def write_example(self, example: object) -> None:
        pass


@pytest.mark.perf
def test_span_overhead_p95_within_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """p95 add_span latency ≤ 1 ms (local M-series) / ≤ 2 ms (CI)."""
    N = 10_000
    CI_BUDGET_MS = 2.0

    monkeypatch.setattr(_api, "_storage_writer", _NullWriter())

    latencies_ns: list[int] = []

    with run(task_id="perf-bench") as r:
        for i in range(N):
            t0 = time.perf_counter_ns()
            r.add_span(SpanKind.LLM, f"span-{i}")
            t1 = time.perf_counter_ns()
            latencies_ns.append(t1 - t0)

    latencies_ns.sort()
    p50_ms = latencies_ns[int(N * 0.50)] / 1_000_000
    p95_ms = latencies_ns[int(N * 0.95)] / 1_000_000
    p99_ms = latencies_ns[int(N * 0.99)] / 1_000_000

    print(f"\nadd_span latency (N={N:,}): p50={p50_ms:.3f}ms  p95={p95_ms:.3f}ms  p99={p99_ms:.3f}ms")

    assert p95_ms <= CI_BUDGET_MS, (
        f"p95 latency {p95_ms:.3f} ms exceeds CI budget of {CI_BUDGET_MS} ms"
    )

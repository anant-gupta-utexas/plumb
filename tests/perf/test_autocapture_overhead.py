"""NFR-Perf-1: autocapture wrapper overhead benchmark.

The original SDK method is stubbed to sleep for 1 ms. The gate measures
10,000 captured calls and fails if autocapture adds more than 1 ms at p95.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any

import pytest

import plumb.api as _api
from plumb.api import run
from plumb.autocapture._openai import _wrap_sync
from plumb.core.entities import RunKind, RunStatus, Score, Span


class _NullWriter:
    def open_run(
        self,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: object,
    ) -> None:
        pass

    def finalize_run(
        self,
        run_id: str,
        status: RunStatus,
        end_ts: object,
        spans: Sequence[Span],
        *,
        error_type: str | None = None,
        orchestrator_model: str | None = None,
        sub_agent_model: str | None = None,
        prompt_version: str | None = None,
        tool_schema_version: str | None = None,
        git_sha: str | None = None,
    ) -> None:
        pass

    def write_score(self, score: Score) -> None:
        pass


class _Usage:
    prompt_tokens = 10
    completion_tokens = 5


class _Response:
    model = "gpt-perf"
    usage = _Usage()

    def model_dump(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "usage": {"prompt_tokens": 10, "completion_tokens": 5},
        }


def _percentiles(latencies_ms: list[float]) -> tuple[float, float, float]:
    latencies_ms.sort()
    n = len(latencies_ms)
    return (
        latencies_ms[int(n * 0.50)],
        latencies_ms[int(n * 0.95)],
        latencies_ms[int(n * 0.99)],
    )


def _measure(fn: Callable[[], object], n: int) -> tuple[float, float, float]:
    latencies_ms: list[float] = []
    for _ in range(n):
        t0 = time.perf_counter_ns()
        fn()
        t1 = time.perf_counter_ns()
        latencies_ms.append((t1 - t0) / 1_000_000.0)
    return _percentiles(latencies_ms)


@pytest.mark.perf
def test_autocapture_wrapper_p95_overhead_within_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NFR-Perf-1: p95 added overhead per captured span must stay <= 1 ms."""
    n = 10_000
    baseline_sleep_seconds = 0.001
    overhead_budget_ms = 1.0

    def original(self: object, *args: Any, **kwargs: Any) -> _Response:
        time.sleep(baseline_sleep_seconds)
        return _Response()

    wrapped = _wrap_sync(
        original,
        endpoint="chat",
        req_canon="canonicalize_openai_chat_request",
        resp_canon="canonicalize_openai_chat_response",
    )
    kwargs = {"model": "gpt-perf", "messages": [{"role": "user", "content": "hi"}]}

    monkeypatch.setattr(_api, "_storage", object())
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", _NullWriter())

    # Warm imports/caches before timing so the loop measures steady-state overhead.
    original(object(), **kwargs)
    baseline_p50, baseline_p95, baseline_p99 = _measure(lambda: original(object(), **kwargs), n)

    with run(task_id="autocapture-overhead-bench") as _r:
        wrapped(object(), **kwargs)
        wrapped_p50, wrapped_p95, wrapped_p99 = _measure(lambda: wrapped(object(), **kwargs), n)

    overhead_p95 = wrapped_p95 - baseline_p95
    print(
        "\nautocapture wrapper latency "
        f"(N={n:,}, baseline sleep={baseline_sleep_seconds * 1000:.1f}ms): "
        f"baseline p50={baseline_p50:.3f}ms p95={baseline_p95:.3f}ms "
        f"p99={baseline_p99:.3f}ms; "
        f"wrapped p50={wrapped_p50:.3f}ms p95={wrapped_p95:.3f}ms "
        f"p99={wrapped_p99:.3f}ms; "
        f"p95 overhead={overhead_p95:.3f}ms"
    )

    assert overhead_p95 <= overhead_budget_ms, (
        "NFR-Perf-1 breached: autocapture p95 overhead "
        f"{overhead_p95:.3f} ms exceeds {overhead_budget_ms:.1f} ms "
        f"(baseline p95={baseline_p95:.3f} ms, wrapped p95={wrapped_p95:.3f} ms)"
    )

"""Unit tests for plumb._http_schemas (T1.1 acceptance criteria)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from plumb._http_schemas import (
    ErrorOut,
    ExampleListOut,
    ExampleOut,
    HealthOut,
    MetricStatOut,
    RunDetailOut,
    RunListOut,
    RunOut,
    RunSummaryOut,
    ScoreOut,
    SpanOut,
    StatsOut,
)

_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_RUN_ID = "a" * 32
_SPAN_ID = "b" * 32
_SCORE_ID = "c" * 32
_EXAMPLE_ID = "d" * 32
_HASH64 = "e" * 64


# ---------------------------------------------------------------------------
# HealthOut
# ---------------------------------------------------------------------------


def test_health_ok() -> None:
    h = HealthOut(status="ok")
    assert h.status == "ok"


def test_health_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError):
        HealthOut(status="ok", extra_field="oops")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# ErrorOut
# ---------------------------------------------------------------------------


def test_error_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ErrorOut(error_type="not_found", detail="msg", surprise=1)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# RunOut
# ---------------------------------------------------------------------------


def _make_run_out(**overrides: object) -> RunOut:
    defaults: dict = {
        "run_id": _RUN_ID,
        "task_id": "my.task",
        "kind": "offline",
        "status": "success",
        "start_ts": _NOW,
        "end_ts": None,
        "parent_run_id": None,
        "orchestrator_model": None,
        "sub_agent_model": None,
        "git_sha": None,
        "tokens_in": None,
        "tokens_out": None,
        "dollar_cost": None,
        "error_type": None,
        "duration_ms": None,
    }
    defaults.update(overrides)
    return RunOut(**defaults)


def test_run_out_valid() -> None:
    r = _make_run_out(tokens_in=100, tokens_out=50, duration_ms=3000)
    assert r.run_id == _RUN_ID
    assert r.tokens_in == 100
    assert r.tokens_out == 50
    assert r.duration_ms == 3000


def test_run_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        _make_run_out(unknown="x")  # type: ignore[arg-type]


def test_run_summary_out_has_counts() -> None:
    r = RunSummaryOut(
        **{
            "run_id": _RUN_ID,
            "task_id": "t",
            "kind": "online",
            "status": "failure",
            "start_ts": _NOW,
            "end_ts": None,
            "parent_run_id": None,
            "orchestrator_model": None,
            "sub_agent_model": None,
            "git_sha": None,
            "tokens_in": None,
            "tokens_out": None,
            "dollar_cost": None,
            "error_type": None,
            "duration_ms": None,
            "span_count": 5,
            "score_count": 2,
        }
    )
    assert r.span_count == 5
    assert r.score_count == 2


# ---------------------------------------------------------------------------
# SpanOut
# ---------------------------------------------------------------------------


def test_span_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        SpanOut(
            span_id=_SPAN_ID,
            run_id=_RUN_ID,
            parent_span_id=None,
            kind="llm",
            name="call",
            input_hash=None,
            output_hash=None,
            tokens=None,
            latency_ms=None,
            status=None,
            error_type=None,
            bogus=True,  # type: ignore[call-arg]
        )


def test_span_out_valid() -> None:
    s = SpanOut(
        span_id=_SPAN_ID,
        run_id=_RUN_ID,
        parent_span_id=None,
        kind="tool",
        name="bash",
        input_hash=_HASH64,
        output_hash=None,
        tokens=10,
        latency_ms=50,
        status="success",
        error_type=None,
    )
    assert s.input_hash == _HASH64
    assert len(s.input_hash) == 64


# ---------------------------------------------------------------------------
# ScoreOut
# ---------------------------------------------------------------------------


def test_score_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ScoreOut(
            score_id=_SCORE_ID,
            run_id=_RUN_ID,
            span_id=None,
            metric_name="m",
            scorer="judge",
            scorer_version="1",
            value_numeric=0.9,
            value_label=None,
            scored_at=_NOW,
            extra=1,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# ExampleOut
# ---------------------------------------------------------------------------


def test_example_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ExampleOut(
            example_id=_EXAMPLE_ID,
            task_id="t",
            inputs_hash=_HASH64,
            expected_output_hash=None,
            rubric=None,
            source="synthetic",
            origin_run_id=None,
            active=True,
            created_at=_NOW,
            oops=1,  # type: ignore[call-arg]
        )


# ---------------------------------------------------------------------------
# RunListOut / ExampleListOut / RunDetailOut / StatsOut
# ---------------------------------------------------------------------------


def test_run_list_out_empty() -> None:
    out = RunListOut(items=[], total=0, limit=100, offset=0)
    assert out.items == []
    assert out.total == 0


def test_example_list_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        ExampleListOut(items=[], extra=1)  # type: ignore[call-arg]


def test_run_detail_out_extra_forbidden() -> None:
    run = _make_run_out()
    with pytest.raises(ValidationError):
        RunDetailOut(run=run, spans=[], scores=[], extra=True)  # type: ignore[call-arg]


def test_stats_out_has_separate_tokens() -> None:
    s = StatsOut(
        task_id="t",
        since=None,
        run_count=1,
        success_rate=1.0,
        intervention_rate=None,
        latency_ms_p50=None,
        latency_ms_p95=None,
        dollar_cost_total=None,
        tokens_in_total=100,
        tokens_out_total=50,
        tokens_per_resolved_task=None,
        metrics=[],
    )
    assert s.tokens_in_total == 100
    assert s.tokens_out_total == 50


def test_metric_stat_out_extra_forbidden() -> None:
    with pytest.raises(ValidationError):
        MetricStatOut(
            metric_name="m",
            n=0,
            value_mean=None,
            value_p50=None,
            value_p95=None,
            pass_rate=None,
            by_scorer={},
            extra=1,  # type: ignore[call-arg]
        )

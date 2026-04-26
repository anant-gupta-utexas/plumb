"""Tests for plumb/core/entities.py — enum values, invariants, and property tests."""

import dataclasses
from datetime import UTC, datetime, timedelta, timezone

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from plumb.core.entities import (
    Example,
    ExampleSource,
    JudgeResult,
    McNemarResult,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)
from plumb.core.errors import ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_TS = datetime(2024, 1, 1, tzinfo=UTC)
_HEX32 = "a" * 32
_HEX64 = "b" * 64
_HEX32_ALT = "c" * 32


def _run(**overrides: object) -> Run:
    defaults: dict[str, object] = dict(
        run_id=_HEX32,
        task_id="my-task",
        kind=RunKind.ONLINE,
        status=RunStatus.SUCCESS,
        start_ts=_TS,
    )
    defaults.update(overrides)
    return Run(**defaults)  # type: ignore[arg-type]


def _span(**overrides: object) -> Span:
    defaults: dict[str, object] = dict(
        span_id=_HEX32,
        run_id=_HEX32,
        kind=SpanKind.LLM,
        name="my-span",
    )
    defaults.update(overrides)
    return Span(**defaults)  # type: ignore[arg-type]


def _score(**overrides: object) -> Score:
    defaults: dict[str, object] = dict(
        score_id=_HEX32,
        run_id=_HEX32,
        metric_name="accuracy",
        scorer_kind=ScorerKind.DETERMINISTIC,
        scorer_version="1.0",
        scored_at=_TS,
        value_numeric=0.9,
    )
    defaults.update(overrides)
    return Score(**defaults)  # type: ignore[arg-type]


def _example(**overrides: object) -> Example:
    defaults: dict[str, object] = dict(
        example_id=_HEX32,
        task_id="my-task",
        inputs_hash=_HEX64,
        source=ExampleSource.SYNTHETIC,
        created_at=_TS,
    )
    defaults.update(overrides)
    return Example(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Enum value parity with TRD CHECK constraints
# ---------------------------------------------------------------------------


def test_enum_values_match_trd_check_constraints() -> None:
    assert RunKind.OFFLINE == "offline"
    assert RunKind.ONLINE == "online"

    assert RunStatus.SUCCESS == "success"
    assert RunStatus.FAILURE == "failure"
    assert RunStatus.ABORTED == "aborted"
    assert RunStatus.STALLED == "stalled"

    assert SpanKind.LLM == "llm"
    assert SpanKind.TOOL == "tool"
    assert SpanKind.SUBAGENT == "subagent"
    assert SpanKind.HANDOFF == "handoff"
    assert SpanKind.PLAN == "plan"
    assert SpanKind.VERIFY == "verify"

    assert SpanStatus.SUCCESS == "success"
    assert SpanStatus.FAILURE == "failure"
    assert SpanStatus.ABORTED == "aborted"

    assert ScorerKind.DETERMINISTIC == "deterministic"
    assert ScorerKind.JUDGE == "judge"
    assert ScorerKind.HUMAN == "human"
    assert ScorerKind.USER_SIGNAL == "user_signal"

    assert ExampleSource.SYNTHETIC == "synthetic"
    assert ExampleSource.PRODUCTION_PROMOTION == "production_promotion"
    assert ExampleSource.HUMAN_AUTHORED == "human_authored"


# ---------------------------------------------------------------------------
# Run invariants
# ---------------------------------------------------------------------------


def test_run_valid() -> None:
    r = _run()
    assert r.run_id == _HEX32


def test_run_invalid_run_id() -> None:
    with pytest.raises(ValidationError):
        _run(run_id="not-hex")


def test_run_empty_task_id() -> None:
    with pytest.raises(ValidationError):
        _run(task_id="")


def test_run_naive_start_ts() -> None:
    with pytest.raises(ValidationError):
        _run(start_ts=datetime(2024, 1, 1))  # no tzinfo


def test_run_end_ts_before_start_ts() -> None:
    with pytest.raises(ValidationError):
        _run(end_ts=_TS - timedelta(seconds=1))


def test_run_end_ts_equal_start_ts_ok() -> None:
    _run(end_ts=_TS)  # should not raise


def test_run_invalid_parent_run_id() -> None:
    with pytest.raises(ValidationError):
        _run(parent_run_id="ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ")


def test_run_replace_produces_new_instance() -> None:
    r = _run()
    r2 = dataclasses.replace(r, end_ts=_TS)
    assert r2.end_ts == _TS
    assert r.end_ts is None


# ---------------------------------------------------------------------------
# Span invariants
# ---------------------------------------------------------------------------


def test_span_valid() -> None:
    s = _span()
    assert s.name == "my-span"


def test_span_empty_name() -> None:
    with pytest.raises(ValidationError):
        _span(name="")


def test_span_negative_latency() -> None:
    with pytest.raises(ValidationError):
        _span(latency_ms=-1.0)


def test_span_zero_latency_ok() -> None:
    _span(latency_ms=0.0)


def test_span_invalid_input_hash() -> None:
    with pytest.raises(ValidationError):
        _span(input_hash="tooshort")


def test_span_invalid_output_hash() -> None:
    with pytest.raises(ValidationError):
        _span(output_hash="z" * 64)  # not lowercase hex


def test_span_valid_hashes() -> None:
    s = _span(input_hash=_HEX64, output_hash=_HEX64)
    assert s.input_hash == _HEX64


def test_span_invalid_parent_span_id() -> None:
    with pytest.raises(ValidationError):
        _span(parent_span_id="not-32-hex")


# ---------------------------------------------------------------------------
# Score XOR invariant
# ---------------------------------------------------------------------------


def test_score_numeric_only() -> None:
    s = _score(value_numeric=0.5, value_label=None)
    assert s.value_numeric == 0.5


def test_score_label_only() -> None:
    s = _score(value_numeric=None, value_label="pass")
    assert s.value_label == "pass"


def test_score_both_raises() -> None:
    with pytest.raises(ValidationError):
        _score(value_numeric=0.5, value_label="pass")


def test_score_neither_raises() -> None:
    with pytest.raises(ValidationError):
        _score(value_numeric=None, value_label=None)


def test_score_empty_metric_name() -> None:
    with pytest.raises(ValidationError):
        _score(metric_name="")


def test_score_empty_scorer_version() -> None:
    with pytest.raises(ValidationError):
        _score(scorer_version="")


def test_score_naive_scored_at() -> None:
    with pytest.raises(ValidationError):
        _score(scored_at=datetime(2024, 1, 1))


def test_score_invalid_span_id() -> None:
    with pytest.raises(ValidationError):
        _score(span_id="not-hex")


# ---------------------------------------------------------------------------
# Example invariants
# ---------------------------------------------------------------------------


def test_example_valid() -> None:
    e = _example()
    assert e.task_id == "my-task"


def test_example_bad_inputs_hash() -> None:
    with pytest.raises(ValidationError):
        _example(inputs_hash="short")


def test_example_bad_expected_output_hash() -> None:
    with pytest.raises(ValidationError):
        _example(expected_output_hash="short")


def test_example_empty_task_id() -> None:
    with pytest.raises(ValidationError):
        _example(task_id="")


def test_example_naive_created_at() -> None:
    with pytest.raises(ValidationError):
        _example(created_at=datetime(2024, 1, 1))


# ---------------------------------------------------------------------------
# §9.2 — no user content in ValidationError messages (log injection prevention)
# ---------------------------------------------------------------------------


def test_no_control_chars_in_validation_error_run_id() -> None:
    hostile = "foo\x1bbar" + "a" * 24
    with pytest.raises(ValidationError) as exc_info:
        _run(run_id=hostile)
    msg = str(exc_info.value)
    assert "\x1b" not in msg
    assert "\n" not in msg
    assert "\r" not in msg
    assert hostile not in msg


def test_no_control_chars_in_validation_error_task_id() -> None:
    with pytest.raises(ValidationError) as exc_info:
        _run(task_id="")
    msg = str(exc_info.value)
    assert "\x1b" not in msg
    assert "\n" not in msg


def test_no_raw_value_in_hex32_error() -> None:
    hostile = "secret\ninjected"
    with pytest.raises(ValidationError) as exc_info:
        _run(run_id=hostile)
    assert hostile not in str(exc_info.value)


def test_no_raw_value_in_hex64_error() -> None:
    hostile = "secret\ninjected"
    with pytest.raises(ValidationError) as exc_info:
        _span(input_hash=hostile)
    assert hostile not in str(exc_info.value)


# ---------------------------------------------------------------------------
# JudgeResult XOR
# ---------------------------------------------------------------------------


def test_judge_result_both_raises() -> None:
    with pytest.raises(ValidationError):
        JudgeResult(
            metric_name="q",
            scorer_version="1",
            rationale="ok",
            tokens_in=1,
            tokens_out=1,
            latency_ms=10.0,
            value_numeric=0.9,
            value_label="pass",
        )


def test_judge_result_neither_raises() -> None:
    with pytest.raises(ValidationError):
        JudgeResult(
            metric_name="q",
            scorer_version="1",
            rationale="ok",
            tokens_in=1,
            tokens_out=1,
            latency_ms=10.0,
        )


# ---------------------------------------------------------------------------
# Hypothesis property tests
# ---------------------------------------------------------------------------


_hex32_st = st.text(
    alphabet="0123456789abcdef", min_size=32, max_size=32
)
_hex64_st = st.text(
    alphabet="0123456789abcdef", min_size=64, max_size=64
)
_ts_st = st.datetimes(
    min_value=datetime(2000, 1, 1),
    max_value=datetime(2100, 1, 1),
    timezones=st.just(UTC),
)


@given(run_id=_hex32_st, task_id=st.text(min_size=1, max_size=50), ts=_ts_st)
@settings(max_examples=50)
def test_run_valid_roundtrip(run_id: str, task_id: str, ts: datetime) -> None:
    r = Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.ONLINE,
        status=RunStatus.SUCCESS,
        start_ts=ts,
    )
    r2 = dataclasses.replace(r, status=RunStatus.FAILURE)
    assert r2.run_id == r.run_id
    assert r2.status == RunStatus.FAILURE

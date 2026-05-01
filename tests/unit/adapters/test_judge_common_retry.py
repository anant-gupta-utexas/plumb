"""Tests for with_judge_retry in plumb/adapters/_judge_common.py."""

from __future__ import annotations

import time
from unittest.mock import call, patch

import pytest

from plumb.adapters._judge_common import JudgeFatalError, JudgeTransientError, with_judge_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_raising(exc_sequence: list[BaseException | None]) -> list[int]:
    """Build a side-effect list where None means return 42."""
    results: list[int] = []

    def fn() -> int:
        if exc_sequence:
            item = exc_sequence.pop(0)
            if item is not None:
                raise item
        results.append(42)
        return 42

    return fn, results  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Basic retry behaviour
# ---------------------------------------------------------------------------


def test_succeeds_on_first_attempt() -> None:
    call_count = 0

    @with_judge_retry
    def fn() -> str:
        nonlocal call_count
        call_count += 1
        return "ok"

    with patch("time.sleep"):
        result = fn()

    assert result == "ok"
    assert call_count == 1


def test_retries_on_transient_error_and_eventually_succeeds() -> None:
    attempts: list[int] = []

    @with_judge_retry
    def fn() -> str:
        attempts.append(1)
        if len(attempts) < 3:
            raise JudgeTransientError("rate limit")
        return "done"

    sleep_calls: list[float] = []
    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        result = fn()

    assert result == "done"
    assert len(attempts) == 3
    assert len(sleep_calls) == 2


def test_reraises_after_three_transient_failures() -> None:
    @with_judge_retry
    def fn() -> None:
        raise JudgeTransientError("always fails")

    with patch("time.sleep"):
        with pytest.raises(JudgeTransientError):
            fn()


def test_sdk_invoked_three_times_on_transient_failure() -> None:
    call_count = 0

    @with_judge_retry
    def fn() -> None:
        nonlocal call_count
        call_count += 1
        raise JudgeTransientError("x")

    with patch("time.sleep"):
        with pytest.raises(JudgeTransientError):
            fn()

    assert call_count == 3


def test_sleep_called_exactly_twice_on_three_failures() -> None:
    @with_judge_retry
    def fn() -> None:
        raise JudgeTransientError("x")

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(JudgeTransientError):
            fn()

    assert mock_sleep.call_count == 2


def test_sleep_durations_monotonically_nondecreasing() -> None:
    @with_judge_retry
    def fn() -> None:
        raise JudgeTransientError("x")

    sleep_args: list[float] = []
    with patch("time.sleep", side_effect=lambda s: sleep_args.append(s)):
        with pytest.raises(JudgeTransientError):
            fn()

    assert len(sleep_args) == 2
    assert sleep_args[0] <= sleep_args[1]


def test_sleep_durations_within_bounds() -> None:
    @with_judge_retry
    def fn() -> None:
        raise JudgeTransientError("x")

    sleep_args: list[float] = []
    with patch("time.sleep", side_effect=lambda s: sleep_args.append(s)):
        with pytest.raises(JudgeTransientError):
            fn()

    for s in sleep_args:
        assert 1.0 <= s <= 8.0


# ---------------------------------------------------------------------------
# Fatal error — no retry
# ---------------------------------------------------------------------------


def test_fatal_error_not_retried() -> None:
    call_count = 0

    @with_judge_retry
    def fn() -> None:
        nonlocal call_count
        call_count += 1
        raise JudgeFatalError("bad request")

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(JudgeFatalError):
            fn()

    assert call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Never-retry exceptions propagate immediately
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("exc_type", [KeyboardInterrupt, SystemExit, MemoryError])
def test_never_retry_exceptions_propagate(exc_type: type[BaseException]) -> None:
    call_count = 0

    @with_judge_retry
    def fn() -> None:
        nonlocal call_count
        call_count += 1
        raise exc_type("stop")

    with patch("time.sleep") as mock_sleep:
        with pytest.raises(exc_type):
            fn()

    assert call_count == 1
    mock_sleep.assert_not_called()


# ---------------------------------------------------------------------------
# Passthrough args / kwargs
# ---------------------------------------------------------------------------


def test_args_and_kwargs_forwarded() -> None:
    @with_judge_retry
    def fn(a: int, *, b: str) -> str:
        return f"{a}-{b}"

    with patch("time.sleep"):
        result = fn(1, b="x")

    assert result == "1-x"

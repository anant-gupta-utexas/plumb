"""Unit tests for plumb._time_utils.parse_since (T1.2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest

from plumb._time_utils import parse_since


def _frozen(ts: datetime):
    """Context manager that freezes _now_utc() to ``ts``."""
    return patch("plumb._time_utils._now_utc", return_value=ts)


_ANCHOR = datetime(2026, 4, 30, 12, 0, 0, tzinfo=UTC)


def test_parse_since_days() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("7d")
    assert result == _ANCHOR - timedelta(days=7)


def test_parse_since_weeks() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("2w")
    assert result == _ANCHOR - timedelta(weeks=2)


def test_parse_since_hours() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("1h")
    assert result == _ANCHOR - timedelta(hours=1)


def test_parse_since_minutes() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("30m")
    assert result == _ANCHOR - timedelta(minutes=30)


def test_parse_since_iso_date_naive_coerced_to_utc() -> None:
    result = parse_since("2026-01-01")
    assert result.tzinfo is not None
    assert result.year == 2026
    assert result.month == 1
    assert result.day == 1
    assert result.tzinfo == UTC


def test_parse_since_iso_datetime_with_timezone_preserved() -> None:
    result = parse_since("2026-01-01T00:00:00+05:30")
    assert result.utcoffset() is not None
    assert result.utcoffset().total_seconds() == 5.5 * 3600


def test_parse_since_invalid_string_raises() -> None:
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_since("foobar")


def test_parse_since_zero_raises() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        parse_since("0d")


def test_parse_since_zero_weeks_raises() -> None:
    with pytest.raises(ValueError, match="must be > 0"):
        parse_since("0w")


def test_parse_since_result_is_utc_aware() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("3d")
    assert result.tzinfo is not None


def test_parse_since_uppercase_unit_accepted() -> None:
    with _frozen(_ANCHOR):
        result = parse_since("7D")
    assert result == _ANCHOR - timedelta(days=7)

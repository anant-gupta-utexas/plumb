"""Time parsing helpers for the plumb CLI (parse_since)."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

_RELATIVE_RE = re.compile(r"^(\d+)([dwhmDWHM])$")
_UNIT_MAP = {
    "d": lambda n: timedelta(days=n),
    "w": lambda n: timedelta(weeks=n),
    "h": lambda n: timedelta(hours=n),
    "m": lambda n: timedelta(minutes=n),
}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def parse_since(s: str) -> datetime:
    """Parse a relative or absolute time string and return a UTC-aware datetime.

    Relative: ``7d``, ``2w``, ``1h``, ``30m`` (days / weeks / hours / minutes).
    Absolute: ISO-8601 string; naive values are coerced to UTC midnight.

    Raises:
        ValueError: if ``s`` cannot be parsed, or if the numeric value is zero.
    """
    match = _RELATIVE_RE.match(s)
    if match:
        n = int(match.group(1))
        unit = match.group(2).lower()
        if n == 0:
            raise ValueError(f"--since value must be > 0, got {s!r}")
        return _now_utc() - _UNIT_MAP[unit](n)

    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise ValueError(
            f"Cannot parse --since value: {s!r}. "
            "Use a relative value (e.g. 7d, 2w, 1h, 30m) or ISO-8601 date."
        ) from None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt

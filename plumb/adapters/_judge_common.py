"""Shared utilities for judge adapters: error types, retry, redaction, reply parsing.

Example usage::

    from plumb.adapters._judge_common import (
        JudgeFatalError,
        JudgeTransientError,
        parse_reply,
        redact_body,
        redact_headers,
        with_judge_retry,
    )
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, TypeVar

_F = TypeVar("_F", bound=Callable[..., Any])

# ---------------------------------------------------------------------------
# Exception types
# ---------------------------------------------------------------------------


class JudgeTransientError(Exception):
    """Retryable error: 429, 5xx, connection reset."""


class JudgeFatalError(Exception):
    """Non-retryable error: 4xx (non-429), auth failure, bad request."""


# ---------------------------------------------------------------------------
# Raw reply container
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawJudgeReply:
    """Holds the raw text and token counts from a single judge call."""

    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: float


# ---------------------------------------------------------------------------
# Redaction helpers
# ---------------------------------------------------------------------------

_SENSITIVE_HEADERS = re.compile(r"^(authorization|x-api-key|api-key)$", re.IGNORECASE)
_SECRET_BODY = re.compile(r"sk-[a-zA-Z0-9]{8,}")


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of *headers* with sensitive values replaced by ``<redacted>``.

    Header names matched (case-insensitively) against ``authorization``,
    ``x-api-key``, and ``api-key`` have their values replaced.

    Args:
        headers: The original HTTP headers mapping.

    Returns:
        A new ``dict[str, str]`` with sensitive values redacted.

    Example::

        safe = redact_headers({"Authorization": "Bearer sk-abc", "Content-Type": "json"})
        assert safe["Authorization"] == "<redacted>"
        assert safe["Content-Type"] == "json"
    """
    return {
        k: "<redacted>" if _SENSITIVE_HEADERS.match(k) else v
        for k, v in headers.items()
    }


def redact_body(text: str) -> str:
    """Replace ``sk-<8+ alphanum>`` substrings in *text* with ``<redacted>``.

    Patterns with fewer than 8 characters after ``sk-`` are left untouched
    (low-confidence match).

    Args:
        text: The text that may contain API key material.

    Returns:
        The sanitized string.

    Example::

        safe = redact_body("error: sk-abcd1234efgh extra")
        assert safe == "error: <redacted> extra"
    """
    return _SECRET_BODY.sub("<redacted>", text)


# ---------------------------------------------------------------------------
# Retry decorator
# ---------------------------------------------------------------------------

_RETRY_ATTEMPTS = 3
_WAIT_INITIAL = 1.0
_WAIT_MAX = 8.0
_NEVER_RETRY = (KeyboardInterrupt, SystemExit, MemoryError)


def with_judge_retry(fn: _F) -> _F:
    """Retry *fn* up to 3 attempts on :class:`JudgeTransientError`.

    Back-off: exponential with initial=1 s, cap=8 s (``min(2**attempt, 8)``).
    The last exception is re-raised after the third failed attempt.
    :class:`KeyboardInterrupt`, :class:`SystemExit`, and :class:`MemoryError`
    are never retried and propagate immediately.

    Args:
        fn: The callable to wrap.

    Returns:
        The wrapped callable with retry logic applied.

    Example::

        @with_judge_retry
        def call_api() -> str:
            ...
    """
    @wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        last_exc: BaseException | None = None
        for attempt in range(1, _RETRY_ATTEMPTS + 1):
            try:
                return fn(*args, **kwargs)
            except _NEVER_RETRY:
                raise
            except JudgeTransientError as exc:
                last_exc = exc
                if attempt < _RETRY_ATTEMPTS:
                    wait = min(_WAIT_MAX, float(2 ** attempt))
                    time.sleep(wait)
        raise last_exc  # type: ignore[misc]

    return wrapper  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# Reply parser
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"^```(?:json)?\s*\n(.*?)\n```\s*$", re.DOTALL)
_MAX_RATIONALE = 1000


def parse_reply(text: str) -> tuple[str | None, float | None, str]:
    """Parse a judge model reply into ``(label, numeric, rationale)``.

    The model is expected to return JSON (possibly code-fenced) with the shape::

        {"verdict": "pass" | "fail" | <float>, "rationale": "<text>"}

    Exactly one of *label* or *numeric* will be non-``None`` in the returned
    tuple. *rationale* is truncated to 1000 characters.

    Args:
        text: Raw text from the model response.

    Returns:
        A ``(label, numeric, rationale)`` tuple where *label* is ``"pass"`` or
        ``"fail"`` and *numeric* is a ``float``, with the other being ``None``.

    Raises:
        ValueError: The text is not valid JSON, missing the ``verdict`` key,
            or the verdict is not a recognised label or number.

    Example::

        label, num, rationale = parse_reply('{"verdict":"pass","rationale":"ok"}')
        assert label == "pass"
        assert num is None
    """
    stripped = text.strip()
    fence_match = _CODE_FENCE_RE.match(stripped)
    if fence_match:
        stripped = fence_match.group(1).strip()

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Judge reply is not valid JSON: {exc}") from exc

    if not isinstance(payload, dict):
        raise ValueError("Judge reply JSON must be an object")

    if "verdict" not in payload:
        raise ValueError("Judge reply missing 'verdict' key")

    verdict = payload["verdict"]
    rationale = str(payload.get("rationale", ""))[:_MAX_RATIONALE]

    if isinstance(verdict, bool):
        raise ValueError(f"Judge verdict must be a string or float, got bool: {verdict!r}")

    if isinstance(verdict, (int, float)):
        return None, float(verdict), rationale

    if verdict in ("pass", "fail"):
        return verdict, None, rationale

    raise ValueError(f"Judge verdict {verdict!r} is not 'pass', 'fail', or a number")

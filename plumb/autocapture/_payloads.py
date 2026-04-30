"""Canonical JSON serialization and secret redaction for autocapture payloads.

All functions are pure (no side effects, no I/O). The redaction regex is compiled
once at module load so it isn't re-compiled on every hot-path call.
"""

from __future__ import annotations

import json
import re
from typing import Any

# Compiled once; applied recursively at every dict depth before serialization.
# (?<![a-zA-Z])token(?!s) prevents matching "max_tokens" while still matching
# "token", "access_token", "refresh_token" etc.
_REDACT_RE = re.compile(
    r"(?i)(api[_-]?key|(?<![a-zA-Z])token(?!s)|secret|authorization|x-api-key|bearer)"
)
_REDACTED = "<redacted>"


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------


def _canonical_json(obj: Any) -> bytes:
    """Return canonical UTF-8 JSON bytes: sorted keys, no whitespace, non-ASCII preserved."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _redact(obj: Any) -> Any:
    """Recursively redact dict keys matching the secret pattern. Pure — never mutates input."""
    if isinstance(obj, dict):
        return {
            k: _REDACTED if _REDACT_RE.search(str(k)) else _redact(v)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_redact(item) for item in obj]
    return obj


def _response_to_dict(response: Any) -> dict[str, Any]:
    """Convert an SDK response object to a plain dict for serialization."""
    if hasattr(response, "model_dump"):
        return response.model_dump()
    if isinstance(response, dict):
        return response
    try:
        return dict(response)
    except (TypeError, ValueError):
        return {"_repr": repr(response)}


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------


def canonicalize_anthropic_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    """Canonical bytes for an anthropic Messages.create call."""
    payload: dict[str, Any] = {}
    # kwargs carries all named params (model, messages, system, tools, ...)
    payload.update(kwargs)
    # positional args are unusual for this SDK but handle defensively
    if args:
        payload["_positional_args"] = list(args)
    return _canonical_json(_redact(payload))


def canonicalize_anthropic_response(response: Any) -> bytes:
    """Canonical bytes for an anthropic Messages response."""
    return _canonical_json(_response_to_dict(response))


# ---------------------------------------------------------------------------
# OpenAI Chat Completions
# ---------------------------------------------------------------------------


def canonicalize_openai_chat_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    """Canonical bytes for an openai chat.completions.create call."""
    payload: dict[str, Any] = {}
    payload.update(kwargs)
    if args:
        payload["_positional_args"] = list(args)
    return _canonical_json(_redact(payload))


def canonicalize_openai_chat_response(response: Any) -> bytes:
    """Canonical bytes for an openai ChatCompletion response."""
    return _canonical_json(_response_to_dict(response))


# ---------------------------------------------------------------------------
# OpenAI Responses API
# ---------------------------------------------------------------------------


def canonicalize_openai_responses_request(args: tuple[Any, ...], kwargs: dict[str, Any]) -> bytes:
    """Canonical bytes for an openai responses.create call."""
    payload: dict[str, Any] = {}
    payload.update(kwargs)
    if args:
        payload["_positional_args"] = list(args)
    return _canonical_json(_redact(payload))


def canonicalize_openai_responses_response(response: Any) -> bytes:
    """Canonical bytes for an openai Response object."""
    return _canonical_json(_response_to_dict(response))

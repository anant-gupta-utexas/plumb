"""Tests for redact_headers and redact_body in plumb/adapters/_judge_common.py."""

from __future__ import annotations

import pytest

from plumb.adapters._judge_common import redact_body, redact_headers


# ---------------------------------------------------------------------------
# redact_headers
# ---------------------------------------------------------------------------


def test_authorization_header_redacted() -> None:
    result = redact_headers({"Authorization": "Bearer sk-abc12345abcde"})
    assert result["Authorization"] == "<redacted>"


def test_content_type_not_redacted() -> None:
    result = redact_headers({"Authorization": "Bearer x", "Content-Type": "application/json"})
    assert result["Content-Type"] == "application/json"


def test_x_api_key_redacted() -> None:
    result = redact_headers({"X-API-Key": "secret"})
    assert result["X-API-Key"] == "<redacted>"


def test_api_key_redacted() -> None:
    result = redact_headers({"api-key": "secret"})
    assert result["api-key"] == "<redacted>"


def test_authorization_lowercase_redacted() -> None:
    result = redact_headers({"authorization": "Bearer token"})
    assert result["authorization"] == "<redacted>"


def test_header_matching_case_insensitive_mixed() -> None:
    headers = {
        "Authorization": "x",
        "X-API-Key": "y",
        "api-key": "z",
        "Accept": "application/json",
    }
    result = redact_headers(headers)
    assert result["Authorization"] == "<redacted>"
    assert result["X-API-Key"] == "<redacted>"
    assert result["api-key"] == "<redacted>"
    assert result["Accept"] == "application/json"


def test_empty_headers_returns_empty_dict() -> None:
    assert redact_headers({}) == {}


def test_redact_headers_returns_new_dict() -> None:
    original = {"Authorization": "secret"}
    result = redact_headers(original)
    assert result is not original
    assert original["Authorization"] == "secret"


# ---------------------------------------------------------------------------
# redact_body
# ---------------------------------------------------------------------------


def test_sk_key_in_body_redacted() -> None:
    result = redact_body("error: sk-abcd1234efgh")
    assert result == "error: <redacted>"


def test_short_sk_not_redacted() -> None:
    """sk- followed by fewer than 8 chars is NOT redacted (low-confidence)."""
    result = redact_body("error: sk-short")
    assert "sk-short" in result
    assert "<redacted>" not in result


def test_sk_exactly_eight_chars_redacted() -> None:
    result = redact_body("key=sk-12345678")
    assert "<redacted>" in result


def test_sk_seven_chars_not_redacted() -> None:
    result = redact_body("key=sk-1234567")
    assert "sk-1234567" in result


def test_multiple_keys_all_redacted() -> None:
    text = "keys: sk-abc12345abcde and sk-xyz98765xyz9"
    result = redact_body(text)
    assert "sk-abc12345abcde" not in result
    assert "sk-xyz98765xyz9" not in result
    assert result.count("<redacted>") == 2


def test_body_without_keys_unchanged() -> None:
    text = "No secrets here."
    assert redact_body(text) == text


def test_empty_body_unchanged() -> None:
    assert redact_body("") == ""

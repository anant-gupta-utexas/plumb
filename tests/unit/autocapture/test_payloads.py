"""Unit tests for plumb.autocapture._payloads (Tasks 2.1, 2.2, 2.3)."""

from __future__ import annotations

import json
from typing import Any

import pytest

from plumb.autocapture._payloads import (
    _canonical_json,
    _redact,
    canonicalize_anthropic_request,
    canonicalize_anthropic_response,
    canonicalize_openai_chat_request,
    canonicalize_openai_chat_response,
    canonicalize_openai_responses_request,
    canonicalize_openai_responses_response,
)

# ---------------------------------------------------------------------------
# Task 2.1 — _canonical_json
# ---------------------------------------------------------------------------


class TestCanonicalJson:
    def test_key_order_invariant(self) -> None:
        a = _canonical_json({"b": 2, "a": 1})
        b = _canonical_json({"a": 1, "b": 2})
        assert a == b

    def test_returns_bytes(self) -> None:
        assert isinstance(_canonical_json({"x": 1}), bytes)

    def test_round_trips(self) -> None:
        original = {"messages": [{"role": "user", "content": "hi"}], "model": "claude-3"}
        result = _canonical_json(original)
        assert json.loads(result.decode("utf-8")) == original

    def test_no_whitespace(self) -> None:
        b = _canonical_json({"a": 1, "b": 2})
        # separators=(",", ":") means no spaces anywhere
        assert b" " not in b

    def test_utf8_non_ascii_preserved(self) -> None:
        b = _canonical_json({"greeting": "こんにちは"})
        decoded = b.decode("utf-8")
        assert "こんにちは" in decoded
        # ensure_ascii=False means no \u escapes for BMP chars
        assert r"\u" not in decoded

    def test_nested_key_order(self) -> None:
        a = _canonical_json({"z": {"y": 2, "x": 1}, "a": 0})
        b = _canonical_json({"a": 0, "z": {"x": 1, "y": 2}})
        assert a == b

    def test_deterministic_across_calls(self) -> None:
        obj = {"messages": [1, 2, 3], "model": "x"}
        assert _canonical_json(obj) == _canonical_json(obj)


# ---------------------------------------------------------------------------
# Task 2.2 — _redact
# ---------------------------------------------------------------------------


class TestRedact:
    # Positive cases — should be redacted
    @pytest.mark.parametrize(
        "key",
        [
            "api_key",
            "apiKey",
            "api-key",
            "API_KEY",
            "token",
            "Token",
            "TOKEN",
            "secret",
            "Secret",
            "authorization",
            "Authorization",
            "AUTHORIZATION",
            "x-api-key",
            "X-API-KEY",
            "bearer_token",
            "Bearer",
        ],
    )
    def test_redacts_matching_key(self, key: str) -> None:
        result = _redact({key: "sk-real-value"})
        assert result[key] == "<redacted>", f"key {key!r} should be redacted"

    # Negative cases — should NOT be redacted
    @pytest.mark.parametrize(
        "key",
        [
            "messages",
            "model",
            "temperature",
            "content",
            "role",
            "max_tokens",
            "system",
            "tools",
            "stop_sequences",
        ],
    )
    def test_preserves_non_secret_key(self, key: str) -> None:
        result = _redact({key: "some-value"})
        assert result[key] == "some-value", f"key {key!r} should not be redacted"

    def test_case_insensitive(self) -> None:
        assert _redact({"API_KEY": "sk-real"})["API_KEY"] == "<redacted>"

    def test_recursive_nested_dict(self) -> None:
        obj = {"outer": {"nested_token": "abc"}}
        result = _redact(obj)
        assert result["outer"]["nested_token"] == "<redacted>"

    def test_list_of_dicts(self) -> None:
        obj = [{"token": "x"}, {"token": "y"}]
        result = _redact(obj)
        assert result[0]["token"] == "<redacted>"
        assert result[1]["token"] == "<redacted>"

    def test_non_secret_keys_preserved(self) -> None:
        obj = {"messages": [{"role": "user", "content": "hello"}]}
        result = _redact(obj)
        assert result["messages"][0]["content"] == "hello"

    def test_immutability(self) -> None:
        original = {"api_key": "sk-real", "model": "x"}
        _redact(original)
        assert original["api_key"] == "sk-real"  # input unchanged

    def test_deeply_nested(self) -> None:
        obj = {"a": {"b": {"c": {"authorization": "Bearer sk-real"}}}}
        result = _redact(obj)
        assert result["a"]["b"]["c"]["authorization"] == "<redacted>"

    def test_non_dict_non_list_passthrough(self) -> None:
        assert _redact("plain string") == "plain string"
        assert _redact(42) == 42
        assert _redact(None) is None


# ---------------------------------------------------------------------------
# Task 2.3 — Provider-specific extraction shells
# ---------------------------------------------------------------------------


class _FakeUsage:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)

    def model_dump(self) -> dict[str, Any]:
        return self.__dict__


class _FakeResponse:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)
        self._dump = kwargs

    def model_dump(self) -> dict[str, Any]:
        return self._dump


class TestAnthropicExtractors:
    def test_request_returns_bytes(self) -> None:
        result = canonicalize_anthropic_request(
            (), {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert isinstance(result, bytes)

    def test_request_redacts_authorization(self) -> None:
        result = canonicalize_anthropic_request(
            (),
            {
                "model": "claude-3",
                "messages": [{"role": "user", "content": "hi"}],
                "extra_headers": {"Authorization": "Bearer sk-x"},
            },
        )
        assert b"sk-x" not in result
        assert b"<redacted>" in result

    def test_request_deterministic(self) -> None:
        kwargs = {"model": "claude-3", "messages": [{"role": "user", "content": "hi"}]}
        result = canonicalize_anthropic_request((), kwargs)
        assert result == canonicalize_anthropic_request((), kwargs)

    def test_response_returns_bytes(self) -> None:
        resp = _FakeResponse(model="claude-3", content=[], usage={"input_tokens": 10})
        result = canonicalize_anthropic_response(resp)
        assert isinstance(result, bytes)

    def test_response_preserves_token_counts(self) -> None:
        resp = _FakeResponse(usage={"prompt_tokens": 10, "completion_tokens": 5})
        b = canonicalize_anthropic_response(resp)
        data = json.loads(b.decode("utf-8"))
        assert data["usage"]["prompt_tokens"] == 10

    def test_response_dict_fallback(self) -> None:
        b = canonicalize_anthropic_response({"model": "x", "content": []})
        data = json.loads(b.decode("utf-8"))
        assert data["model"] == "x"


class TestOpenAIChatExtractors:
    def test_request_returns_bytes(self) -> None:
        result = canonicalize_openai_chat_request(
            (), {"model": "gpt-4o", "messages": [{"role": "user", "content": "hi"}]}
        )
        assert isinstance(result, bytes)

    def test_request_redacts_api_key(self) -> None:
        result = canonicalize_openai_chat_request(
            (),
            {
                "model": "gpt-4o",
                "messages": [],
                "extra_headers": {"x-api-key": "sk-real"},
            },
        )
        assert b"sk-real" not in result
        assert b"<redacted>" in result

    def test_response_token_counts_round_trip(self) -> None:
        resp = _FakeResponse(usage={"prompt_tokens": 10, "completion_tokens": 5})
        b = canonicalize_openai_chat_response(resp)
        data = json.loads(b.decode("utf-8"))
        assert data["usage"]["prompt_tokens"] == 10
        assert data["usage"]["completion_tokens"] == 5

    def test_request_deterministic(self) -> None:
        kwargs = {"model": "gpt-4o", "messages": []}
        result = canonicalize_openai_chat_request((), kwargs)
        assert result == canonicalize_openai_chat_request((), kwargs)


class TestOpenAIResponsesExtractors:
    def test_request_returns_bytes(self) -> None:
        result = canonicalize_openai_responses_request((), {"model": "gpt-4o", "input": "hi"})
        assert isinstance(result, bytes)

    def test_response_input_output_tokens(self) -> None:
        resp = _FakeResponse(usage={"input_tokens": 20, "output_tokens": 10})
        b = canonicalize_openai_responses_response(resp)
        data = json.loads(b.decode("utf-8"))
        assert data["usage"]["input_tokens"] == 20
        assert data["usage"]["output_tokens"] == 10

    def test_request_deterministic(self) -> None:
        kwargs = {"model": "gpt-4o", "input": "x"}
        assert canonicalize_openai_responses_request(
            (), kwargs
        ) == canonicalize_openai_responses_request((), kwargs)


# ---------------------------------------------------------------------------
# Hypothesis property test — Task 2.1
# ---------------------------------------------------------------------------

try:
    from hypothesis import given, settings, strategies as st

    _has_hypothesis = True
except ImportError:
    _has_hypothesis = False


if _has_hypothesis:
    # Recursive strategy for nested dicts with string keys and simple values
    _simple = st.one_of(st.integers(), st.text(max_size=20), st.none(), st.booleans())
    _json_dict = st.recursive(
        st.dictionaries(st.text(min_size=1, max_size=10), _simple, max_size=5),
        lambda children: st.dictionaries(st.text(min_size=1, max_size=10), children, max_size=3),
        max_leaves=10,
    )

    @given(_json_dict)
    @settings(max_examples=200)
    def test_canonical_json_order_invariant(d: dict) -> None:
        """Random nested dicts produce identical bytes regardless of input ordering."""

        # Produce the same dict with reversed key order at the top level
        d2 = dict(reversed(list(d.items())))
        assert _canonical_json(d) == _canonical_json(d2)

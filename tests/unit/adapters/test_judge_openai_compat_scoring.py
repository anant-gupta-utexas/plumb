"""Scoring, retry, fail-open, and security tests for OpenAICompatibleJudge.

Construction and metadata tests live in test_judge_openai_compat_construction.py.
"""

from __future__ import annotations

import logging
import socket
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    import openai

import pytest

from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge
from plumb.core.entities import JudgeResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_response(
    verdict: str = "pass",
    rationale: str = "looks good",
    tokens_in: int = 10,
    tokens_out: int = 5,
) -> SimpleNamespace:
    import json

    text = json.dumps({"verdict": verdict, "rationale": rationale})
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


def _make_numeric_response(
    score: float = 0.9,
    rationale: str = "close",
    tokens_in: int = 10,
    tokens_out: int = 5,
) -> SimpleNamespace:
    import json

    text = json.dumps({"verdict": score, "rationale": rationale})
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=tokens_in, completion_tokens=tokens_out),
    )


def _make_judge(
    mock_client: MagicMock | None = None,
    base_url: str | None = None,
) -> OpenAICompatibleJudge:
    client = mock_client or MagicMock()
    return OpenAICompatibleJudge(
        api_key="sk-test-key",
        prompt="Rate this as pass or fail.",
        prompt_sha="a1b2c3d4",
        base_url=base_url,
        client=client,
    )


def _make_api_status_error(status_code: int, body: str = "") -> openai.APIStatusError:
    import httpx
    import openai

    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code, request=request)
    return openai.APIStatusError(body or f"HTTP {status_code}", response=response, body=body)


def _make_rate_limit_error() -> openai.RateLimitError:
    import httpx
    import openai

    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    return openai.RateLimitError("rate limited", response=resp, body="")


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_judge_result() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response("pass", "ok", 10, 5)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(
            metric_name="routing_top1",
            prompt="",
            content="some content",
            model="gpt-4o",
        )

    assert isinstance(result, JudgeResult)
    assert result.value_label == "pass"
    assert result.value_numeric is None
    assert result.metric_name == "routing_top1"


def test_happy_path_scorer_version() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response("pass")
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="gpt-4o")

    assert result.scorer_version == "openai_compat:gpt-4o:a1b2c3d4"


def test_happy_path_tokens_from_usage() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response(tokens_in=42, tokens_out=7)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.tokens_in == 42
    assert result.tokens_out == 7


def test_happy_path_latency_ms_positive() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.latency_ms >= 0.0


def test_system_prompt_as_first_message() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="user content", model="model")

    _, kwargs = client.chat.completions.create.call_args
    messages = kwargs["messages"]
    assert messages[0]["role"] == "system"
    assert messages[0]["content"] == "Rate this as pass or fail."
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "user content"


def test_request_uses_temperature_zero_and_max_tokens_1024() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    _, kwargs = client.chat.completions.create.call_args
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 1024


def test_numeric_verdict_returned() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = _make_numeric_response(0.75)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label is None
    assert result.value_numeric == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Retry behaviour
# ---------------------------------------------------------------------------


def test_rate_limit_twice_then_success_invokes_sdk_three_times() -> None:
    client = MagicMock()
    rate_err = _make_rate_limit_error()
    responses: list[object] = [rate_err, rate_err, _make_response("pass")]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.chat.completions.create.side_effect = side_effect
    judge = _make_judge(client)
    sleep_calls: list[float] = []

    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert client.chat.completions.create.call_count == 3
    assert result.value_label == "pass"
    assert len(sleep_calls) == 2


def test_sleep_monotonically_nondecreasing_on_retry() -> None:
    client = MagicMock()
    rate_err = _make_rate_limit_error()
    responses: list[object] = [rate_err, rate_err, _make_response()]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.chat.completions.create.side_effect = side_effect
    judge = _make_judge(client)
    sleep_calls: list[float] = []

    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    assert sleep_calls[0] <= sleep_calls[1]


# ---------------------------------------------------------------------------
# Fail-open paths
# ---------------------------------------------------------------------------


def test_rate_limit_three_times_fail_open() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = _make_rate_limit_error()
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="gpt-4o")

    assert result.value_label == "error"
    assert result.scorer_version == "openai_compat:gpt-4o:a1b2c3d4:error"
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.latency_ms == 0.0


def test_fail_open_rationale_truncated_to_500_chars() -> None:
    import httpx
    import openai

    long_msg = "x" * 600
    client = MagicMock()
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    exc = openai.RateLimitError(long_msg, response=resp, body=long_msg)
    client.chat.completions.create.side_effect = exc
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert len(result.rationale) <= 500


def test_api_status_5xx_three_times_fail_open() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = [
        _make_api_status_error(500),
        _make_api_status_error(503),
        _make_api_status_error(502),
    ]
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"
    assert client.chat.completions.create.call_count == 3


def test_api_status_4xx_non_429_fail_open_immediately() -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = _make_api_status_error(400)
    judge = _make_judge(client)

    with patch("time.sleep") as mock_sleep:
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"
    assert client.chat.completions.create.call_count == 1
    mock_sleep.assert_not_called()


def test_connection_error_once_then_success_retries() -> None:
    import httpx
    import openai

    client = MagicMock()
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    conn_err = openai.APIConnectionError(request=req)
    responses: list[object] = [conn_err, _make_response("fail")]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.chat.completions.create.side_effect = side_effect
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "fail"
    assert client.chat.completions.create.call_count == 2


# ---------------------------------------------------------------------------
# Reply parsing fail-open
# ---------------------------------------------------------------------------


def test_non_json_reply_fail_open() -> None:
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="not json at all"))],
        usage=SimpleNamespace(prompt_tokens=5, completion_tokens=3),
    )
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"


# ---------------------------------------------------------------------------
# Security: API key redaction
# ---------------------------------------------------------------------------


def test_api_key_in_error_is_redacted_in_result(caplog: pytest.LogCaptureFixture) -> None:
    import httpx
    import openai

    client = MagicMock()
    key_in_msg = "error: sk-abc12345abcde"
    req = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    resp = httpx.Response(429, request=req)
    exc = openai.RateLimitError(key_in_msg, response=resp, body=key_in_msg)
    client.chat.completions.create.side_effect = exc
    judge = _make_judge(client)

    with caplog.at_level(logging.WARNING), patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert "sk-abc12345abcde" not in result.rationale
    assert "<redacted>" in result.rationale
    for record in caplog.records:
        assert "sk-abc12345abcde" not in record.getMessage()


# ---------------------------------------------------------------------------
# Warning emitted exactly once per fail-open
# ---------------------------------------------------------------------------


def test_warning_emitted_once_per_fail_open(caplog: pytest.LogCaptureFixture) -> None:
    client = MagicMock()
    client.chat.completions.create.side_effect = _make_rate_limit_error()
    judge = _make_judge(client)

    with caplog.at_level(logging.WARNING), patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


# ---------------------------------------------------------------------------
# Base URL HTTP-level test (AC-INT-2)
# ---------------------------------------------------------------------------


def test_base_url_forwarded_to_openai_sdk() -> None:
    """base_url is passed into OpenAI(base_url=...) when building the client."""
    with patch("openai.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = _make_response()

        judge = OpenAICompatibleJudge(
            api_key="tok-abc",
            prompt="p",
            prompt_sha="sha",
            base_url="https://openrouter.ai/api/v1",
        )

        with patch("time.sleep"):
            judge.score(metric_name="m", prompt="", content="c", model="model")

    mock_cls.assert_called_once_with(api_key="tok-abc", base_url="https://openrouter.ai/api/v1")


def test_no_base_url_does_not_pass_base_url_kwarg() -> None:
    """base_url=None → openai.OpenAI called without base_url keyword."""
    with patch("openai.OpenAI") as mock_cls:
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_instance.chat.completions.create.return_value = _make_response()

        OpenAICompatibleJudge(api_key="tok-abc", prompt="p", prompt_sha="sha")

    call_kwargs = mock_cls.call_args[1]
    assert "base_url" not in call_kwargs


# ---------------------------------------------------------------------------
# No real network
# ---------------------------------------------------------------------------


def test_no_real_network_connect_called(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure socket.connect is never reached; mock client used."""
    connected: list[object] = []

    def fake_connect(self: socket.socket, *args: object) -> None:
        connected.append(args)
        raise AssertionError("Real network connection attempted in test!")

    monkeypatch.setattr(socket.socket, "connect", fake_connect)

    client = MagicMock()
    client.chat.completions.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    assert connected == [], "socket.connect should never have been called"

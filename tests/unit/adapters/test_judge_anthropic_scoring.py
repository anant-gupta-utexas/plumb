"""Scoring, retry, fail-open, and security tests for AnthropicJudge.

Construction and metadata tests live in test_judge_anthropic_construction.py.
"""

from __future__ import annotations

import logging
import socket
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

if TYPE_CHECKING:
    import anthropic

import pytest

from plumb.adapters.judge_anthropic import AnthropicJudge
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
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
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
        content=[SimpleNamespace(text=text)],
        usage=SimpleNamespace(input_tokens=tokens_in, output_tokens=tokens_out),
    )


def _make_judge(mock_client: MagicMock | None = None) -> AnthropicJudge:
    client = mock_client or MagicMock()
    return AnthropicJudge(
        api_key="sk-ant-test",
        prompt="Rate this as pass or fail.",
        prompt_sha="a1b2c3d4",
        client=client,
    )


def _make_api_status_error(status_code: int, body: str = "") -> anthropic.APIStatusError:
    import anthropic
    import httpx

    request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
    response = httpx.Response(status_code, request=request)
    return anthropic.APIStatusError(body or f"HTTP {status_code}", response=response, body=body)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_happy_path_returns_judge_result() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response("pass", "ok", 10, 5)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(
            metric_name="routing_top1",
            prompt="",
            content="some content",
            model="claude-sonnet-4-6",
        )

    assert isinstance(result, JudgeResult)
    assert result.value_label == "pass"
    assert result.value_numeric is None
    assert result.metric_name == "routing_top1"


def test_happy_path_scorer_version() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response("pass")
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="claude-sonnet-4-6")

    assert result.scorer_version == "anthropic:claude-sonnet-4-6:a1b2c3d4"


def test_happy_path_tokens() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response(tokens_in=42, tokens_out=7)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.tokens_in == 42
    assert result.tokens_out == 7


def test_happy_path_latency_ms_positive() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.latency_ms >= 0.0


def test_system_prompt_sent_with_cache_control() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    _, kwargs = client.messages.create.call_args
    system = kwargs["system"]
    assert isinstance(system, list)
    assert system[0]["cache_control"] == {"type": "ephemeral"}
    assert system[0]["type"] == "text"


def test_request_uses_temperature_zero_and_max_tokens_1024() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    _, kwargs = client.messages.create.call_args
    assert kwargs["temperature"] == 0.0
    assert kwargs["max_tokens"] == 1024


def test_numeric_verdict_returned() -> None:
    client = MagicMock()
    client.messages.create.return_value = _make_numeric_response(0.75)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label is None
    assert result.value_numeric == pytest.approx(0.75)


# ---------------------------------------------------------------------------
# Retry behaviour (AC-JUDGE-3)
# ---------------------------------------------------------------------------


def test_rate_limit_twice_then_success_invokes_sdk_three_times() -> None:
    import anthropic

    client = MagicMock()
    rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)

    responses = [rate_err, rate_err, _make_response("pass")]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.messages.create.side_effect = side_effect

    judge = _make_judge(client)
    sleep_calls: list[float] = []

    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert client.messages.create.call_count == 3
    assert result.value_label == "pass"
    assert len(sleep_calls) == 2


def test_sleep_monotonically_nondecreasing_on_retry() -> None:
    import anthropic

    client = MagicMock()
    rate_err = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    responses = [rate_err, rate_err, _make_response()]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.messages.create.side_effect = side_effect
    judge = _make_judge(client)
    sleep_calls: list[float] = []

    with patch("time.sleep", side_effect=lambda s: sleep_calls.append(s)):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    assert sleep_calls[0] <= sleep_calls[1]


# ---------------------------------------------------------------------------
# Fail-open paths (AC-JUDGE-4)
# ---------------------------------------------------------------------------


def test_rate_limit_three_times_fail_open() -> None:
    import anthropic

    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="claude-sonnet-4-6")

    assert result.value_label == "error"
    assert result.scorer_version == "anthropic:claude-sonnet-4-6:a1b2c3d4:error"
    assert result.tokens_in == 0
    assert result.tokens_out == 0
    assert result.latency_ms == 0.0


def test_fail_open_rationale_truncated_to_500_chars() -> None:
    import anthropic

    long_msg = "x" * 600
    client = MagicMock()
    exc = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    exc.args = (long_msg,)
    client.messages.create.side_effect = exc
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert len(result.rationale) <= 500


def test_api_status_500_three_times_fail_open() -> None:
    client = MagicMock()
    client.messages.create.side_effect = [
        _make_api_status_error(500),
        _make_api_status_error(500),
        _make_api_status_error(500),
    ]
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"


def test_api_status_400_fail_open_immediately() -> None:
    client = MagicMock()
    client.messages.create.side_effect = _make_api_status_error(400)
    judge = _make_judge(client)

    with patch("time.sleep") as mock_sleep:
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"
    assert client.messages.create.call_count == 1
    mock_sleep.assert_not_called()


def test_authentication_error_fail_open_immediately() -> None:
    client = MagicMock()
    client.messages.create.side_effect = _make_api_status_error(401)
    judge = _make_judge(client)

    with patch("time.sleep") as mock_sleep:
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"
    assert client.messages.create.call_count == 1
    mock_sleep.assert_not_called()


def test_connection_error_once_then_success_retries() -> None:
    import anthropic

    client = MagicMock()
    conn_err = anthropic.APIConnectionError.__new__(anthropic.APIConnectionError)
    responses: list[object] = [conn_err, _make_response("fail")]

    def side_effect(*args: object, **kwargs: object) -> object:
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    client.messages.create.side_effect = side_effect
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "fail"
    assert client.messages.create.call_count == 2


# ---------------------------------------------------------------------------
# Reply parsing fail-open
# ---------------------------------------------------------------------------


def test_non_json_reply_fail_open() -> None:
    client = MagicMock()
    client.messages.create.return_value = SimpleNamespace(
        content=[SimpleNamespace(text="not json at all")],
        usage=SimpleNamespace(input_tokens=5, output_tokens=3),
    )
    judge = _make_judge(client)

    with patch("time.sleep"):
        result = judge.score(metric_name="m", prompt="", content="c", model="model")

    assert result.value_label == "error"


# ---------------------------------------------------------------------------
# Security: API key redaction (AC-JUDGE-5)
# ---------------------------------------------------------------------------


def test_api_key_in_error_is_redacted_in_result(caplog: pytest.LogCaptureFixture) -> None:
    import anthropic

    client = MagicMock()
    key_in_msg = "error: sk-abc12345abcde"
    exc = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    exc.args = (key_in_msg,)
    client.messages.create.side_effect = exc
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
    import anthropic

    client = MagicMock()
    client.messages.create.side_effect = anthropic.RateLimitError.__new__(anthropic.RateLimitError)
    judge = _make_judge(client)

    with caplog.at_level(logging.WARNING), patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1


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
    client.messages.create.return_value = _make_response()
    judge = _make_judge(client)

    with patch("time.sleep"):
        judge.score(metric_name="m", prompt="", content="c", model="model")

    assert connected == [], "socket.connect should never have been called"

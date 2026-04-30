"""Regression tests for the wrapper safety boundary (FR-CAP-3 / NFR-Rel-1).

These tests pin down the contract that plumb-side serialization or emission
bugs MUST NOT prevent or alter the user's SDK call:

- Issue 1 in `dev/active/v1-autocapture/v1-autocapture-code-review.md`:
  request canonicalization happened before the protected SDK-call block, so
  a plumb bug could raise a `TypeError` *before* `original(...)` ran. The
  fix routes canonicalization through `safe_canonicalize_request`, which
  catches `BaseException`, logs a structured WARNING, and returns a
  sentinel that tells the wrapper to skip span emission while the SDK call
  still runs.

- Issue 3: response canonicalization used to silently substitute ``b"{}"``
  on failure, recording a real-looking ``output_hash`` that pointed at
  empty content. The fix logs a structured WARNING and records
  ``output_hash=None`` with ``error_type='response_serialization_failed'``
  while keeping ``status='success'`` (the user's call did succeed).
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

import plumb.autocapture._payloads as _payloads
from plumb.autocapture import _emit
from plumb.autocapture._anthropic import (
    _wrap_async_messages_create,
    _wrap_messages_create,
    _wrap_messages_stream,
)
from plumb.autocapture._openai import _wrap_async, _wrap_sync
from plumb.core.entities import SpanStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _Boom:
    """A kwarg value that raises whenever any canonicalizer touches it."""

    def __repr__(self) -> str:
        raise RuntimeError("boom: canonicalization probe")

    def __iter__(self) -> Any:
        raise RuntimeError("boom: canonicalization probe")


@pytest.fixture()
def warning_records(
    caplog: pytest.LogCaptureFixture,
) -> pytest.LogCaptureFixture:
    caplog.set_level(logging.WARNING, logger="plumb.autocapture._payloads")
    caplog.set_level(logging.WARNING, logger="plumb.autocapture._emit")
    return caplog


# ---------------------------------------------------------------------------
# Issue 1 — request canonicalization failures must not prevent the SDK call
# ---------------------------------------------------------------------------


class TestSafeCanonicalizeRequest:
    def test_returns_canonical_bytes_on_success(self) -> None:
        result = _payloads.safe_canonicalize_request(
            _payloads.canonicalize_anthropic_request,
            (),
            {"model": "x", "messages": []},
            provider="anthropic",
            endpoint="messages",
        )
        assert isinstance(result, bytes)
        assert result is not _payloads.CANONICALIZATION_FAILED

    def test_returns_sentinel_on_failure(self, warning_records: pytest.LogCaptureFixture) -> None:
        def explode(args: Any, kwargs: Any) -> bytes:
            raise TypeError("not JSON serializable")

        result = _payloads.safe_canonicalize_request(
            explode,
            (),
            {},
            provider="anthropic",
            endpoint="messages",
        )
        assert result is _payloads.CANONICALIZATION_FAILED

    def test_failure_logs_structured_warning_without_body(
        self, warning_records: pytest.LogCaptureFixture
    ) -> None:
        def explode(args: Any, kwargs: Any) -> bytes:
            raise ValueError("secret-prompt-redacted")

        _payloads.safe_canonicalize_request(
            explode,
            (),
            {"messages": [{"role": "user", "content": "TOPSECRET-PROMPT"}]},
            provider="openai",
            endpoint="chat",
        )
        records = [r for r in warning_records.records if "canonicalization" in r.message]
        assert records, "expected a structured WARNING on canonicalization failure"
        rec = records[-1]
        assert rec.levelno == logging.WARNING
        assert getattr(rec, "plumb_internal_error", False) is True
        assert getattr(rec, "subsystem", None) == "autocapture"
        assert getattr(rec, "stage", None) == "request_canonicalize"
        assert getattr(rec, "provider", None) == "openai"
        assert getattr(rec, "error_class", None) == "ValueError"
        # NFR-Sec-2: no body content in the WARNING record's message or extras.
        rendered = rec.getMessage()
        assert "TOPSECRET-PROMPT" not in rendered
        for value in rec.__dict__.values():
            assert "TOPSECRET-PROMPT" not in repr(value)


class TestAnthropicWrapperSafetyBoundary:
    def _wrap_returning(self, response: Any) -> Any:
        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return response

        return _wrap_messages_create(original)

    def _wrap_raising(self, exc: BaseException) -> Any:
        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            raise exc

        return _wrap_messages_create(original)

    def test_request_canonicalize_failure_does_not_skip_sdk_call(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
        warning_records: pytest.LogCaptureFixture,
    ) -> None:
        bs, rh = installed_emit_fakes

        def boom(args: Any, kwargs: Any) -> bytes:
            raise TypeError("plumb-side serialization bug")

        monkeypatch.setattr(_payloads, "canonicalize_anthropic_request", boom)

        sentinel_response = SimpleNamespace(model="claude-x")
        wrapped = self._wrap_returning(sentinel_response)

        result = wrapped(None, model="claude-x", messages=[])

        assert result is sentinel_response, (
            "user SDK call must still run and its return value must reach the caller "
            "even when plumb-side request canonicalization fails"
        )
        assert rh.captured_spans == [], "no span should be recorded for the failed canonicalization"

    def test_request_canonicalize_failure_preserves_sdk_exception_type(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes

        monkeypatch.setattr(
            _payloads,
            "canonicalize_anthropic_request",
            lambda *a, **k: (_ for _ in ()).throw(TypeError("plumb bug")),
        )

        class _RateLimitError(Exception):
            pass

        wrapped = self._wrap_raising(_RateLimitError("provider quota"))

        with pytest.raises(_RateLimitError):
            wrapped(None, model="claude-x", messages=[])

        assert rh.captured_spans == [], (
            "no failure span should be recorded when plumb canonicalization itself failed"
        )

    def test_stream_wrapper_request_canonicalize_failure_passes_through(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes
        monkeypatch.setattr(
            _payloads,
            "canonicalize_anthropic_request",
            lambda *a, **k: (_ for _ in ()).throw(TypeError("plumb bug")),
        )

        sentinel = SimpleNamespace(stream=True)

        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return sentinel

        wrapped = _wrap_messages_stream(original)
        result = wrapped(None, model="claude-x", messages=[])
        assert result is sentinel
        assert rh.captured_spans == []

    @pytest.mark.asyncio
    async def test_async_wrapper_request_canonicalize_failure_passes_through(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes
        monkeypatch.setattr(
            _payloads,
            "canonicalize_anthropic_request",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("plumb bug")),
        )

        sentinel = SimpleNamespace(model="claude-x")

        async def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return sentinel

        wrapped = _wrap_async_messages_create(original)
        result = await wrapped(None, model="claude-x", messages=[])
        assert result is sentinel
        assert rh.captured_spans == []


class TestOpenAIWrapperSafetyBoundary:
    def test_sync_request_canonicalize_failure_does_not_skip_sdk_call(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes
        monkeypatch.setattr(
            _payloads,
            "canonicalize_openai_chat_request",
            lambda *a, **k: (_ for _ in ()).throw(TypeError("plumb bug")),
        )

        sentinel = SimpleNamespace(model="gpt-x")

        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return sentinel

        wrapped = _wrap_sync(original, "chat", "canonicalize_openai_chat_request")
        result = wrapped(None, model="gpt-x", messages=[])
        assert result is sentinel
        assert rh.captured_spans == []

    def test_sync_request_canonicalize_failure_preserves_sdk_exception(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes
        monkeypatch.setattr(
            _payloads,
            "canonicalize_openai_chat_request",
            lambda *a, **k: (_ for _ in ()).throw(TypeError("plumb bug")),
        )

        class _ProviderError(Exception):
            pass

        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            raise _ProviderError("rate limited")

        wrapped = _wrap_sync(original, "chat", "canonicalize_openai_chat_request")
        with pytest.raises(_ProviderError):
            wrapped(None, model="gpt-x", messages=[])
        assert rh.captured_spans == []

    @pytest.mark.asyncio
    async def test_async_request_canonicalize_failure_does_not_skip_sdk_call(
        self,
        installed_emit_fakes: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        bs, rh = installed_emit_fakes
        monkeypatch.setattr(
            _payloads,
            "canonicalize_openai_chat_request",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("plumb bug")),
        )

        sentinel = SimpleNamespace(model="gpt-x")

        async def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return sentinel

        wrapped = _wrap_async(original, "chat", "canonicalize_openai_chat_request")
        result = await wrapped(None, model="gpt-x", messages=[])
        assert result is sentinel
        assert rh.captured_spans == []


# ---------------------------------------------------------------------------
# Issue 3 — response canonicalization failures must not silently substitute {}
# ---------------------------------------------------------------------------


_REQ_BYTES = b'{"model":"x","messages":[]}'


class _BadResponse:
    """A response object whose model_dump explodes — drives the canonicalizer to fail."""

    model = "x"

    def model_dump(self) -> dict[str, Any]:
        raise RuntimeError("response serialization probe")


class TestResponseCanonicalizationFailure:
    def test_output_hash_is_none_not_hash_of_empty_object(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ_BYTES,
            response=_BadResponse(),
            latency_ms=1.0,
        )
        assert len(rh.captured_spans) == 1
        span = rh.captured_spans[0]
        assert span["output_hash"] is None, (
            "output_hash must be None on serialization failure, "
            "never a real-looking hash that points to b'{}'"
        )

    def test_error_type_marks_serialization_failure(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ_BYTES,
            response=_BadResponse(),
            latency_ms=1.0,
        )
        span = rh.captured_spans[0]
        assert span.get("error_type") == "response_serialization_failed"

    def test_status_remains_success(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ_BYTES,
            response=_BadResponse(),
            latency_ms=1.0,
        )
        # The user's SDK call did succeed — only plumb's serialization failed.
        assert rh.captured_spans[0]["status"] == SpanStatus.SUCCESS

    def test_response_blob_not_written_on_failure(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ_BYTES,
            response=_BadResponse(),
            latency_ms=1.0,
        )
        # Only the request blob should have been written; response blob was None.
        assert bs.put_call_count == 1

    def test_logs_structured_warning(
        self,
        installed_emit_fakes: Any,
        warning_records: pytest.LogCaptureFixture,
    ) -> None:
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ_BYTES,
            response=_BadResponse(),
            latency_ms=1.0,
        )
        records = [
            r
            for r in warning_records.records
            if getattr(r, "stage", None) == "response_canonicalize"
        ]
        assert records, "expected a structured WARNING on response canonicalization failure"
        rec = records[-1]
        assert rec.levelno == logging.WARNING
        assert getattr(rec, "plumb_internal_error", False) is True
        assert getattr(rec, "subsystem", None) == "autocapture"
        assert getattr(rec, "provider", None) == "anthropic"
        assert getattr(rec, "error_class", None) == "RuntimeError"

"""Unit tests for plumb.autocapture._emit (Task 3.1)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest

from plumb.autocapture import _emit
from plumb.core.entities import SpanKind, SpanStatus

from .conftest import FakeBlobStore


class _FakeUsage:
    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeResponse:
    def __init__(self, model: str = "claude-3", **kwargs: Any) -> None:
        self.model = model
        self._data = {"model": model, **kwargs}
        if "usage" in kwargs:
            self.usage = kwargs["usage"]

    def model_dump(self) -> dict[str, Any]:
        return self._data


_REQ = b'{"messages":[]}'
_REQ_HASH = hashlib.sha256(_REQ).hexdigest()


class TestEmitSuccessSpan:
    def test_calls_add_span_once(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        resp = _FakeResponse()
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="claude-3",
            request_payload=_REQ,
            response=resp,
            latency_ms=12.3,
        )
        assert len(rh.captured_spans) == 1

    def test_span_kind_is_llm(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="claude-3",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["kind"] == SpanKind.LLM

    def test_span_name_shape(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="claude-sonnet-4-6",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["name"] == "anthropic/messages/claude-sonnet-4-6"

    def test_input_hash_is_sha256(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["input_hash"] == _REQ_HASH

    def test_output_hash_set(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["output_hash"] is not None
        assert len(rh.captured_spans[0]["output_hash"]) == 64

    def test_status_success(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["status"] == SpanStatus.SUCCESS

    def test_anthropic_token_extraction(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        usage = _FakeUsage(input_tokens=10, output_tokens=5)
        resp = _FakeResponse(usage=usage)
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=resp,
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["tokens"] == (10, 5)

    def test_openai_chat_token_extraction(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        usage = _FakeUsage(prompt_tokens=20, completion_tokens=8)
        resp = _FakeResponse(usage=usage)
        _emit.emit_success_span(
            provider="openai",
            endpoint="chat",
            model="gpt-4o",
            request_payload=_REQ,
            response=resp,
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["tokens"] == (20, 8)

    def test_openai_responses_token_extraction(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        usage = _FakeUsage(input_tokens=15, output_tokens=7)
        resp = _FakeResponse(usage=usage)
        _emit.emit_success_span(
            provider="openai",
            endpoint="responses",
            model="gpt-4o",
            request_payload=_REQ,
            response=resp,
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["tokens"] == (15, 7)

    def test_no_tokens_when_usage_absent(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["tokens"] is None

    def test_blobs_written(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert bs.put_call_count == 2

    def test_no_active_run_skips_span(
        self, fake_blobstore: FakeBlobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as api

        monkeypatch.setattr(api, "_blobstore", fake_blobstore)
        # _active_run is already None (default)
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        # No exception — no span emitted

    def test_blobstore_failure_still_emits_span(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        bs.put = lambda _content: (_ for _ in ()).throw(OSError("disk full"))  # type: ignore
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert len(rh.captured_spans) == 1

    def test_internal_failure_does_not_raise(
        self, fake_blobstore: FakeBlobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """NFR-Rel-1: internal failure never raises into caller."""
        import plumb.api as api

        monkeypatch.setattr(api, "_blobstore", fake_blobstore)

        class _BrokenHandle:
            def add_span(self, *args: Any, **kwargs: Any) -> str:
                raise RuntimeError("internal plumb bug")

        token = api._active_run.set(_BrokenHandle())  # type: ignore[arg-type]
        try:
            _emit.emit_success_span(
                provider="anthropic",
                endpoint="messages",
                model="x",
                request_payload=_REQ,
                response=_FakeResponse(),
                latency_ms=1.0,
            )
        finally:
            api._active_run.reset(token)

    def test_none_model_uses_unknown(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model=None,
            request_payload=_REQ,
            response=_FakeResponse(),
            latency_ms=1.0,
        )
        assert rh.captured_spans[0]["name"] == "anthropic/messages/unknown"


class TestEmitFailureSpan:
    def test_calls_add_span_once(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="RateLimitError",
        )
        assert len(rh.captured_spans) == 1

    def test_status_failure(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="RateLimitError",
        )
        assert rh.captured_spans[0]["status"] == SpanStatus.FAILURE

    def test_error_type_recorded(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="RateLimitError",
        )
        assert rh.captured_spans[0]["error_type"] == "RateLimitError"

    def test_output_hash_none(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="Timeout",
        )
        assert rh.captured_spans[0]["output_hash"] is None

    def test_tokens_none(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="Timeout",
        )
        assert rh.captured_spans[0]["tokens"] is None

    def test_input_hash_correct(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="Err",
        )
        assert rh.captured_spans[0]["input_hash"] == _REQ_HASH

    def test_no_active_run_skips_silently(
        self, fake_blobstore: FakeBlobStore, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as api

        monkeypatch.setattr(api, "_blobstore", fake_blobstore)
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint="messages",
            model="x",
            request_payload=_REQ,
            latency_ms=5.0,
            error_type="Err",
        )

    def test_none_endpoint_uses_unknown(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        _emit.emit_failure_span(
            provider="anthropic",
            endpoint=None,
            model=None,
            request_payload=_REQ,
            latency_ms=1.0,
            error_type="Err",
        )
        assert rh.captured_spans[0]["name"] == "anthropic/unknown/unknown"

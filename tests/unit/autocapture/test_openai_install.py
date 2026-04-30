"""Unit tests for plumb.autocapture._openai (Task 5.1)."""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import patch

import pytest

import plumb.autocapture as _autocapture
import plumb.autocapture._state as state
from plumb.autocapture._openai import _CHAT_MODULE, _RESPONSES_MODULE, _wrap_async, _wrap_sync


@pytest.fixture(autouse=True)
def clean_registry():
    _autocapture.uninstall()
    yield
    _autocapture.uninstall()


# ---------------------------------------------------------------------------
# _try_install — no-op without openai
# ---------------------------------------------------------------------------


class TestTryInstallNoSdk:
    def test_noop_when_openai_missing(self) -> None:
        with patch.dict("sys.modules", {"openai": None}):
            from plumb.autocapture._openai import _try_install

            _try_install()
        assert len(state._INSTALLED) == 0

    def test_registers_four_targets_when_openai_installed(self) -> None:
        pytest.importorskip("openai")
        from plumb.autocapture._openai import _try_install

        _try_install()

        assert {
            f"{_CHAT_MODULE}.Completions.create",
            f"{_CHAT_MODULE}.AsyncCompletions.create",
            f"{_RESPONSES_MODULE}.Responses.create",
            f"{_RESPONSES_MODULE}.AsyncResponses.create",
        }.issubset(state._INSTALLED)

        before = dict(state._INSTALLED)
        _try_install()
        assert state._INSTALLED == before


# ---------------------------------------------------------------------------
# Sync wrapper — _wrap_sync
# ---------------------------------------------------------------------------


class TestSyncWrapper:
    _REQ_CANON = "canonicalize_openai_chat_request"
    _RESP_CANON = "canonicalize_openai_chat_response"

    def _make_wrapper(self, side_effect: Any = None) -> tuple[Any, list]:
        calls: list[dict] = []

        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append({"args": args, "kwargs": kwargs})
            if side_effect is not None:
                raise side_effect
            return types.SimpleNamespace(model="gpt-4o")

        return (
            _wrap_sync(original, "chat", self._REQ_CANON, self._RESP_CANON),
            calls,
        )

    def test_passthrough_without_active_run(self) -> None:
        wrapper, calls = self._make_wrapper()
        result = wrapper(None, model="gpt-4o", messages=[])
        assert hasattr(result, "model")
        assert len(calls) == 1

    def test_returns_original_response(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper()
        result = wrapper(None, model="gpt-4o", messages=[])
        assert result.model == "gpt-4o"

    def test_span_emitted(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper()
        wrapper(None, model="gpt-4o", messages=[])
        assert len(rh.captured_spans) == 1
        assert rh.captured_spans[0]["name"] == "openai/chat/gpt-4o"

    def test_exception_reraised(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper(side_effect=ValueError("ratelimit"))
        with pytest.raises(ValueError):
            wrapper(None, model="gpt-4o", messages=[])

    def test_failure_span_on_exception(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper(side_effect=ValueError("oops"))
        with pytest.raises(ValueError):
            wrapper(None, model="gpt-4o", messages=[])
        assert len(rh.captured_spans) == 1
        from plumb.core.entities import SpanStatus

        assert rh.captured_spans[0]["status"] == SpanStatus.FAILURE


# ---------------------------------------------------------------------------
# Responses API wrapper — span name uses "responses"
# ---------------------------------------------------------------------------


class TestSyncWrapperResponses:
    _REQ_CANON = "canonicalize_openai_responses_request"
    _RESP_CANON = "canonicalize_openai_responses_response"

    def test_span_name_includes_responses(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes

        async def _orig(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return types.SimpleNamespace(model="gpt-4o")

        def orig(self_: Any, *args: Any, **kwargs: Any) -> Any:
            return types.SimpleNamespace(model="gpt-4o")

        wrapper = _wrap_sync(orig, "responses", self._REQ_CANON, self._RESP_CANON)
        wrapper(None, model="gpt-4o", input="hi")
        assert rh.captured_spans[0]["name"] == "openai/responses/gpt-4o"


# ---------------------------------------------------------------------------
# Async wrapper — _wrap_async
# ---------------------------------------------------------------------------


class TestAsyncWrapper:
    _REQ_CANON = "canonicalize_openai_chat_request"
    _RESP_CANON = "canonicalize_openai_chat_response"

    def _make_async_wrapper(self, side_effect: Any = None) -> tuple[Any, list]:
        calls: list[dict] = []

        async def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append({"args": args, "kwargs": kwargs})
            if side_effect is not None:
                raise side_effect
            return types.SimpleNamespace(model="gpt-4o")

        return (
            _wrap_async(original, "chat", self._REQ_CANON, self._RESP_CANON),
            calls,
        )

    @pytest.mark.asyncio
    async def test_passthrough_without_active_run(self) -> None:
        wrapper, calls = self._make_async_wrapper()
        result = await wrapper(None, model="gpt-4o", messages=[])
        assert hasattr(result, "model")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_span_emitted(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper()
        await wrapper(None, model="gpt-4o", messages=[])
        assert len(rh.captured_spans) == 1

    @pytest.mark.asyncio
    async def test_exception_reraised(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            await wrapper(None, model="gpt-4o", messages=[])

    @pytest.mark.asyncio
    async def test_failure_span_on_async_exception(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            await wrapper(None, model="gpt-4o", messages=[])
        from plumb.core.entities import SpanStatus

        assert rh.captured_spans[0]["status"] == SpanStatus.FAILURE

"""Unit tests for plumb.autocapture._anthropic (Task 4.1)."""

from __future__ import annotations

import types
from typing import Any
from unittest.mock import patch

import pytest

import plumb.autocapture._state as state
from plumb.autocapture._anthropic import (
    _wrap_async_messages_create,
    _wrap_messages_create,
)


@pytest.fixture(autouse=True)
def clean_registry():
    state._INSTALLED.clear()
    yield
    state._INSTALLED.clear()


# ---------------------------------------------------------------------------
# _try_install — no-op without anthropic
# ---------------------------------------------------------------------------


class TestTryInstallNoSdk:
    def test_noop_when_anthropic_missing(self) -> None:
        with patch.dict("sys.modules", {"anthropic": None}):
            from plumb.autocapture._anthropic import _try_install

            _try_install()
        assert len(state._INSTALLED) == 0


# ---------------------------------------------------------------------------
# Sync wrapper — _wrap_messages_create
# ---------------------------------------------------------------------------


class TestSyncWrapper:
    def _make_wrapper(self, side_effect: Any = None) -> tuple[Any, list]:
        calls: list[dict] = []

        def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append({"args": args, "kwargs": kwargs})
            if side_effect is not None:
                raise side_effect
            return types.SimpleNamespace(model="claude-3")

        return _wrap_messages_create(original), calls

    def test_passthrough_without_active_run(self) -> None:
        wrapper, calls = self._make_wrapper()
        result = wrapper(None, model="claude-3", messages=[])
        assert hasattr(result, "model")
        assert len(calls) == 1

    def test_returns_original_response(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper()
        result = wrapper(None, model="claude-3", messages=[])
        assert result.model == "claude-3"

    def test_span_emitted_with_active_run(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper()
        wrapper(None, model="claude-3", messages=[])
        assert len(rh.captured_spans) == 1
        assert rh.captured_spans[0]["name"] == "anthropic/messages/claude-3"

    def test_exception_reraised(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper(side_effect=ValueError("rate limit"))
        with pytest.raises(ValueError, match="rate limit"):
            wrapper(None, model="claude-3", messages=[])

    def test_failure_span_on_exception(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_wrapper(side_effect=ValueError("oops"))
        with pytest.raises(ValueError):
            wrapper(None, model="claude-3", messages=[])
        assert len(rh.captured_spans) == 1
        from plumb.core.entities import SpanStatus

        assert rh.captured_spans[0]["status"] == SpanStatus.FAILURE
        assert rh.captured_spans[0]["error_type"] == "ValueError"


# ---------------------------------------------------------------------------
# Async wrapper — _wrap_async_messages_create
# ---------------------------------------------------------------------------


class TestAsyncWrapper:
    def _make_async_wrapper(self, side_effect: Any = None) -> tuple[Any, list]:
        calls: list[dict] = []

        async def original(self_: Any, *args: Any, **kwargs: Any) -> Any:
            calls.append({"args": args, "kwargs": kwargs})
            if side_effect is not None:
                raise side_effect
            return types.SimpleNamespace(model="claude-3")

        return _wrap_async_messages_create(original), calls

    @pytest.mark.asyncio
    async def test_passthrough_without_active_run(self) -> None:
        wrapper, calls = self._make_async_wrapper()
        result = await wrapper(None, model="claude-3", messages=[])
        assert hasattr(result, "model")
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_returns_original_response(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper()
        result = await wrapper(None, model="claude-3", messages=[])
        assert result.model == "claude-3"

    @pytest.mark.asyncio
    async def test_span_emitted_with_active_run(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper()
        await wrapper(None, model="claude-3", messages=[])
        assert len(rh.captured_spans) == 1

    @pytest.mark.asyncio
    async def test_exception_reraised(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            await wrapper(None, model="claude-3", messages=[])

    @pytest.mark.asyncio
    async def test_failure_span_on_exception(self, installed_emit_fakes: Any) -> None:
        bs, rh = installed_emit_fakes
        wrapper, _ = self._make_async_wrapper(side_effect=RuntimeError("fail"))
        with pytest.raises(RuntimeError):
            await wrapper(None, model="claude-3", messages=[])
        assert len(rh.captured_spans) == 1
        from plumb.core.entities import SpanStatus

        assert rh.captured_spans[0]["status"] == SpanStatus.FAILURE

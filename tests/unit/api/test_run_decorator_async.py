"""Tests for async decorator path (Task 6.2)."""

from __future__ import annotations

import pytest

from plumb.api import run
from plumb.core.entities import RunStatus, SpanKind


class TestAsyncDecoratorBasics:
    async def test_decorator_writes_one_row_per_call(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="async-task")
        async def _fn() -> int:
            return 7

        result = await _fn()
        assert result == 7
        assert len(storage.runs) == 1
        assert storage.last_run.status == RunStatus.SUCCESS

    async def test_return_value_preserved(self, configured_api: object) -> None:
        @run(task_id="t")
        async def _fn(x: int) -> int:
            return x * 2

        assert await _fn(5) == 10

    async def test_functools_wraps_preserves_metadata(self, configured_api: object) -> None:
        @run(task_id="t")
        async def my_async_fn() -> None:
            """My docstring."""

        assert my_async_fn.__name__ == "my_async_fn"
        assert my_async_fn.__doc__ == "My docstring."
        assert my_async_fn.__wrapped__ is not None  # type: ignore[attr-defined]

    async def test_task_id_propagated(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="async-eval")
        async def _fn() -> None:
            pass

        await _fn()
        assert storage.last_run.task_id == "async-eval"

    async def test_exception_propagates_and_writes_failure(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        class _Boom(Exception):
            pass

        @run(task_id="t")
        async def _fn() -> None:
            raise _Boom("boom")

        with pytest.raises(_Boom):
            await _fn()

        assert storage.last_run.status == RunStatus.FAILURE
        assert storage.last_run.error_type == "_Boom"

    async def test_spans_written_via_async_decorator(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="t")
        async def _fn() -> None:
            import plumb.api as _api

            handle = _api._active_run.get()
            assert handle is not None
            handle.add_span(SpanKind.LLM, "gen")

        await _fn()
        assert len(storage.last_spans) == 1
        assert storage.last_spans[0].name == "gen"

    async def test_multiple_calls_write_multiple_rows(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="t")
        async def _fn() -> None:
            pass

        await _fn()
        await _fn()
        assert len(storage.runs) == 2


class TestAsyncDecoratorNesting:
    async def test_fr_graph_1_nested_async_decorator(self, configured_api: object) -> None:
        """FR-GRAPH-1: nested async decorated fns — child sees outer run as parent."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        captured: dict[str, str | None] = {}

        @run(task_id="inner")
        async def _inner() -> None:
            import plumb.api as _api

            handle = _api._active_run.get()
            assert handle is not None
            captured["inner_parent"] = handle.parent_run_id

        @run(task_id="outer")
        async def _outer() -> None:
            import plumb.api as _api

            outer_handle = _api._active_run.get()
            assert outer_handle is not None
            captured["outer_id"] = outer_handle.run_id
            await _inner()

        await _outer()
        assert captured["inner_parent"] == captured["outer_id"]

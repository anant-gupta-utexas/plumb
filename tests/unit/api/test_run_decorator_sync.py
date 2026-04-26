"""Tests for sync decorator path (Task 5.4)."""

from __future__ import annotations

import inspect

import pytest

from plumb.api import run
from plumb.core.entities import RunStatus, SpanKind


class TestSyncDecoratorBasics:
    def test_produces_one_run_row(self, configured_api: object) -> None:
        """FR-API-2 (sync): exactly one Run row per call."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="t")
        def fn() -> int:
            return 42

        result = fn()
        assert result == 42
        assert len(storage.runs) == 1
        assert storage.last_run.status == RunStatus.SUCCESS

    def test_return_value_preserved(self, configured_api: object) -> None:
        @run(task_id="t")
        def fn(x: int) -> int:
            return x * 2

        assert fn(5) == 10

    def test_wraps_preserves_name_and_doc(self, configured_api: object) -> None:
        """FR-API-2: __name__, __doc__, __wrapped__ preserved."""

        @run(task_id="t")
        def my_function() -> None:
            """My docstring."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "My docstring."
        assert my_function.__wrapped__ is not None  # type: ignore[attr-defined]

    def test_exception_reraises(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        class _Err(Exception):
            pass

        @run(task_id="t")
        def fn() -> None:
            raise _Err("oops")

        with pytest.raises(_Err):
            fn()

        assert storage.last_run.status == RunStatus.FAILURE
        assert storage.last_run.error_type == "_Err"

    def test_multiple_calls_produce_multiple_rows(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="t")
        def fn() -> None:
            pass

        fn()
        fn()
        fn()
        assert len(storage.runs) == 3

    def test_async_fn_detection(self, configured_api: object) -> None:
        """Async fn wrapped with @run should NOT be sync."""

        @run(task_id="t")
        async def async_fn() -> None:
            pass

        assert inspect.iscoroutinefunction(async_fn)


class TestDecoratorNestedDedup:
    def test_fr_edge_4_nested_decorator_dedup(self, configured_api: object) -> None:
        """FR-EDGE-4: @run on the same function — recursive call dedupes to one row.

        The decorator captures frame_id = id(fn). When recursive_fn calls itself,
        the inner invocation finds a parent handle whose _open_frame_id == frame_id,
        so it dedupes and the outer factory writes the single row on exit.
        """
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        call_count = [0]

        @run(task_id="recursive")
        def recursive_fn() -> None:
            call_count[0] += 1
            if call_count[0] < 2:
                recursive_fn()

        recursive_fn()
        # Dedup fires on the inner call — only one row written by the outer factory.
        assert len(storage.runs) == 1
        assert storage.last_run.status == "success"

    def test_decorator_on_sync_fn_args_kwargs_forwarded(
        self, configured_api: object
    ) -> None:
        @run(task_id="t")
        def add(a: int, b: int = 0) -> int:
            return a + b

        assert add(3, b=4) == 7


class TestDecoratorWithKindAndModels:
    def test_kind_propagated(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        @run(task_id="t", kind="offline")
        def fn() -> None:
            pass

        fn()
        assert storage.last_run.kind == "offline"

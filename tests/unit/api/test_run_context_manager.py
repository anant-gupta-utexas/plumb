"""Tests for sync context manager (Task 5.3) — ≥ 12 tests."""

from __future__ import annotations

import logging

import pytest

import plumb.api as _api
from plumb.api import RunHandle, run
from plumb.core.entities import RunStatus, SpanKind
from plumb.core.errors import StorageError


class TestBasicContextManager:
    def test_enter_yields_run_handle(self, configured_api: object) -> None:
        with run(task_id="t") as r:
            assert isinstance(r, RunHandle)

    def test_successful_run_writes_one_row(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t"):
            pass
        assert len(storage.runs) == 1
        assert storage.last_run.status == RunStatus.SUCCESS

    def test_run_id_is_32_hex(self, configured_api: object) -> None:
        with run(task_id="t") as r:
            rid = r.run_id
        import re
        assert re.match(r"^[0-9a-f]{32}$", rid)

    def test_task_id_propagated(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="my-task"):
            pass
        assert storage.last_run.task_id == "my-task"


class TestEdgeCases:
    def test_fr_edge_1_exception_reraise_and_failure_status(
        self, configured_api: object
    ) -> None:
        """FR-EDGE-1: user exception re-raised AND run written as failure."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        class _UserErr(Exception):
            pass

        with pytest.raises(_UserErr), run(task_id="t"):
            raise _UserErr("boom")

        assert len(storage.runs) == 1
        assert storage.last_run.status == RunStatus.FAILURE
        assert storage.last_run.error_type == "_UserErr"

    def test_fr_edge_3_zero_span_run_is_valid(self, configured_api: object) -> None:
        """FR-EDGE-3: zero-span run writes successfully."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t"):
            pass
        assert storage.last_run.status == RunStatus.SUCCESS
        assert storage.last_spans == []

    def test_fr_edge_5_abort_status_and_partial_flush(
        self, configured_api: object
    ) -> None:
        """FR-EDGE-5: abort writes pre-abort spans; post-abort spans not persisted."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t") as r:
            r.add_span(SpanKind.LLM, "first")
            r.abort("cancelled")
            r.add_span(SpanKind.LLM, "second")

        assert storage.last_run.status == RunStatus.ABORTED
        assert storage.last_run.error_type == "cancelled"
        assert len(storage.last_spans) == 1
        assert storage.last_spans[0].name == "first"

    def test_fr_edge_5_abort_reason_stored(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t") as r:
            r.abort("my reason")
        assert storage.last_run.error_type == "my reason"


class TestNesting:
    def test_fr_graph_1_nested_run_inherits_parent_run_id(
        self, configured_api: object
    ) -> None:
        """FR-GRAPH-1: nested `with run()` → child.parent_run_id == outer.run_id."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="outer") as outer:
            outer_id = outer.run_id
            with run(task_id="inner") as inner:
                inner_parent_id = inner.parent_run_id

        assert inner_parent_id == outer_id

    def test_fr_graph_2_explicit_parent_run_id(self, configured_api: object) -> None:
        """FR-GRAPH-2: explicit parent_run_id populated when no outer run."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        explicit_parent = "a" * 32
        with run(task_id="t", parent_run_id=explicit_parent) as r:
            assert r.parent_run_id == explicit_parent

        assert storage.last_run.parent_run_id == explicit_parent

    def test_nested_run_has_own_run_id(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="outer") as outer, run(task_id="inner") as inner:
            assert outer.run_id != inner.run_id

    def test_contextvar_restored_after_exit(self, configured_api: object) -> None:
        with run(task_id="outer"):
            with run(task_id="inner"):
                pass
            assert _api._active_run.get() is not None
        assert _api._active_run.get() is None


class TestNFRRel1:
    def test_storage_error_does_not_raise_into_caller(
        self, configured_api: object, caplog: pytest.LogCaptureFixture
    ) -> None:
        """NFR-Rel-1: StorageError swallowed; WARNING logged with plumb_internal_error."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        def _raise(*args: object, **kwargs: object) -> None:
            raise StorageError("disk full")

        storage.finalize_run = _raise  # type: ignore[method-assign]

        result = None
        with caplog.at_level(logging.WARNING, logger="plumb.api"), run(task_id="t") as r:
            result = 42

        assert result == 42  # user return value unaffected

        # WARNING should be logged
        assert any("plumb" in r.message.lower() for r in caplog.records)

    def test_storage_error_user_exception_still_reraised(
        self, configured_api: object
    ) -> None:
        """NFR-Rel-1 + FR-EDGE-1: even when storage fails, user exception is re-raised."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        def _raise(*args: object, **kwargs: object) -> None:
            raise StorageError("disk full")

        storage.write_run = _raise  # type: ignore[method-assign]

        class _UserErr(Exception):
            pass

        with pytest.raises(_UserErr), run(task_id="t"):
            raise _UserErr("user problem")


class TestSpansAndScoresWritten:
    def test_spans_written_with_run(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t") as r:
            r.add_span(SpanKind.LLM, "generate")
            r.add_span(SpanKind.TOOL, "search")
        assert len(storage.last_spans) == 2

    def test_scores_written_separately(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t") as r:
            r.add_score("accuracy", "deterministic", value_numeric=0.9)
        assert len(storage.scores) == 1
        assert storage.scores[0].value_numeric == 0.9

    def test_end_ts_set_on_run(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t"):
            pass
        assert storage.last_run.end_ts is not None
        assert storage.last_run.end_ts >= storage.last_run.start_ts

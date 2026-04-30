"""Edge-case tests supplementing the context manager tests."""

from __future__ import annotations

import pytest

from plumb.api import run
from plumb.core.entities import RunStatus


class TestExceptionFlowEdgeCases:
    def test_exception_type_recorded_exactly(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        class _CustomErr(RuntimeError):
            pass

        with pytest.raises(_CustomErr), run(task_id="t"):
            raise _CustomErr("oops")

        assert storage.last_run.error_type == "_CustomErr"

    def test_base_exception_propagates(self, configured_api: object) -> None:
        """BaseException (KeyboardInterrupt) must not be suppressed, and run is persisted."""
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        with pytest.raises(KeyboardInterrupt), run(task_id="t"):
            raise KeyboardInterrupt

        assert len(storage.runs) == 1
        assert storage.last_run.status == RunStatus.FAILURE
        assert storage.last_run.error_type == "KeyboardInterrupt"

    def test_multiple_exceptions_only_first_recorded(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        class _Err(Exception):
            pass

        with pytest.raises(_Err), run(task_id="t") as r:
            r.abort("pre-abort")
            raise _Err("after abort")

        # exception takes priority over abort when determining status
        assert storage.last_run.status == RunStatus.FAILURE


class TestKindPropagation:
    def test_offline_kind(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t", kind="offline"):
            pass
        assert storage.last_run.kind == "offline"

    def test_online_kind_default(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t"):
            pass
        assert storage.last_run.kind == "online"


class TestMultipleRuns:
    def test_sequential_runs_each_write_one_row(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)
        with run(task_id="t"):
            pass
        with run(task_id="t"):
            pass
        assert len(storage.runs) == 2

    def test_contextvar_clean_between_runs(self, configured_api: object) -> None:
        import plumb.api as _api

        with run(task_id="t"):
            pass
        assert _api._active_run.get() is None
        with run(task_id="t") as r2:
            assert r2.parent_run_id is None

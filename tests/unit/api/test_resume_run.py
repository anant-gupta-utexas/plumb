"""Unit tests for plumb.resume_run(run_id) (Task 6, §15.1)."""

from __future__ import annotations

import pytest

from plumb.api import RunHandle, resume_run, run
from plumb.core.entities import RunStatus, SpanKind
from plumb.core.errors import NotFoundError, ValidationError


class TestResumeRunBasic:
    def test_resume_pending_run_yields_run_handle(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        with run(task_id="t") as r1:
            run_id = r1.run_id
        # run() finalizes the row at __exit__; re-register it as pending in the
        # fake to simulate a run that was left open by a different process.
        storage._pending[run_id] = ("t", storage.runs[0][0].kind, None, storage.runs[0][0].start_ts)

        with resume_run(run_id) as r2:
            assert isinstance(r2, RunHandle)
            assert r2.run_id == run_id

    def test_resume_preserves_run_id_and_task_id(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        with run(task_id="my-task") as r1:
            run_id = r1.run_id

        storage._pending[run_id] = (
            "my-task",
            storage.runs[0][0].kind,
            None,
            storage.runs[0][0].start_ts,
        )

        with resume_run(run_id) as r2:
            assert r2.run_id == run_id
            assert r2.task_id == "my-task"

    def test_resume_adds_spans_and_finalizes(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        with run(task_id="t") as r1:
            run_id = r1.run_id

        storage._pending[run_id] = ("t", storage.runs[0][0].kind, None, storage.runs[0][0].start_ts)

        with resume_run(run_id) as r2:
            r2.add_span(SpanKind.LLM, "generate")

        # last finalize_run call produced the newest runs[] entry
        newest_run, newest_spans = storage.runs[-1]
        assert newest_run.run_id == run_id
        assert newest_run.status == RunStatus.SUCCESS
        assert len(newest_spans) == 1

    def test_resume_nonexistent_run_raises_not_found(self, configured_api: object) -> None:
        with pytest.raises(NotFoundError), resume_run("z" * 32):
            pass

    def test_resume_terminal_run_raises_validation_error(self, configured_api: object) -> None:
        with run(task_id="t") as r1:
            run_id = r1.run_id
        # run() finalizes to 'success' at __exit__ — already terminal.
        with pytest.raises(ValidationError, match="already terminal"), resume_run(run_id):
            pass

    def test_resume_terminal_run_writes_no_new_rows(self, configured_api: object) -> None:
        from tests.conftest import FakeStorageWriter

        storage = configured_api  # type: ignore[assignment]
        assert isinstance(storage, FakeStorageWriter)

        with run(task_id="t") as r1:
            run_id = r1.run_id
        count_before = len(storage.runs)

        with pytest.raises(ValidationError), resume_run(run_id):
            pass

        assert len(storage.runs) == count_before

    def test_resume_is_not_usable_as_decorator(self) -> None:
        factory = resume_run("a" * 32)
        # _ResumeRunFactory has no __call__, so decorator syntax raises TypeError.
        assert not callable(factory)

"""Tests for _RunBuilder (Task 5.1)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plumb.api import _RunBuilder
from plumb.core.entities import RunKind, RunStatus, SpanKind, SpanStatus
from plumb.core.errors import ValidationError


_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_END = datetime(2024, 1, 1, 0, 0, 10, tzinfo=timezone.utc)
_RUN_ID = "a" * 32
_SPAN_ID = "b" * 32
_TASK = "test-task"


def _builder(**kwargs: object) -> _RunBuilder:
    defaults: dict[str, object] = dict(
        run_id=_RUN_ID,
        task_id=_TASK,
        kind=RunKind.ONLINE,
        parent_run_id=None,
        start_ts=_START,
    )
    defaults.update(kwargs)
    return _RunBuilder(**defaults)  # type: ignore[arg-type]


class TestRunBuilderInit:
    def test_fields_stored(self) -> None:
        b = _builder(orchestrator_model="gpt-4")
        assert b.run_id == _RUN_ID
        assert b.task_id == _TASK
        assert b.kind == RunKind.ONLINE
        assert b.orchestrator_model == "gpt-4"
        assert b.spans == []
        assert b.scores == []
        assert b.aborted is False

    def test_optional_model_fields_default_none(self) -> None:
        b = _builder()
        assert b.sub_agent_model is None
        assert b.prompt_version is None
        assert b.tool_schema_version is None
        assert b.git_sha is None

    def test_status_none_before_freeze(self) -> None:
        b = _builder()
        assert b.status is None
        assert b.end_ts is None
        assert b.error_type is None


class TestRunBuilderFreeze:
    def test_freeze_success(self) -> None:
        b = _builder()
        b.status = RunStatus.SUCCESS
        b.end_ts = _END
        run = b.freeze()
        assert run.run_id == _RUN_ID
        assert run.task_id == _TASK
        assert run.status == RunStatus.SUCCESS
        assert run.end_ts == _END
        assert run.error_type is None

    def test_freeze_failure(self) -> None:
        b = _builder()
        b.status = RunStatus.FAILURE
        b.error_type = "ValueError"
        b.end_ts = _END
        run = b.freeze()
        assert run.status == RunStatus.FAILURE
        assert run.error_type == "ValueError"

    def test_freeze_aborted(self) -> None:
        b = _builder()
        b.status = RunStatus.ABORTED
        b.error_type = "user cancelled"
        b.end_ts = _END
        run = b.freeze()
        assert run.status == RunStatus.ABORTED

    def test_freeze_without_status_raises(self) -> None:
        b = _builder()
        with pytest.raises(ValidationError):
            b.freeze()

    def test_freeze_with_parent_run_id(self) -> None:
        parent_id = "c" * 32
        b = _builder(parent_run_id=parent_id)
        b.status = RunStatus.SUCCESS
        b.end_ts = _END
        run = b.freeze()
        assert run.parent_run_id == parent_id

    def test_freeze_model_fields_propagated(self) -> None:
        b = _builder(
            orchestrator_model="claude-3",
            sub_agent_model="haiku",
            prompt_version="v2",
            git_sha="abc",
        )
        b.status = RunStatus.SUCCESS
        b.end_ts = _END
        run = b.freeze()
        assert run.orchestrator_model == "claude-3"
        assert run.sub_agent_model == "haiku"
        assert run.prompt_version == "v2"
        assert run.git_sha == "abc"

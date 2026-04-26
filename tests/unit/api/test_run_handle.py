"""Tests for RunHandle (Task 5.2)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from plumb.api import RunHandle, _RunBuilder
from plumb.core.entities import RunKind, SpanKind, SpanStatus
from plumb.core.errors import ValidationError


_START = datetime(2024, 1, 1, tzinfo=timezone.utc)
_RUN_ID = "a" * 32


def _make_handle(**kwargs: object) -> RunHandle:
    defaults: dict[str, object] = dict(
        run_id=_RUN_ID,
        task_id="test-task",
        kind=RunKind.ONLINE,
        parent_run_id=None,
        start_ts=_START,
    )
    defaults.update(kwargs)
    b = _RunBuilder(**defaults)  # type: ignore[arg-type]
    return RunHandle(b)


class TestRunHandleConstruct:
    def test_no_args_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="not user-constructible"):
            RunHandle()  # type: ignore[call-arg]

    def test_none_builder_raises_type_error(self) -> None:
        with pytest.raises(TypeError, match="not user-constructible"):
            RunHandle(_builder=None)

    def test_valid_construction(self) -> None:
        h = _make_handle()
        assert h.run_id == _RUN_ID


class TestRunHandleProperties:
    def test_run_id(self) -> None:
        h = _make_handle()
        assert h.run_id == _RUN_ID

    def test_task_id(self) -> None:
        h = _make_handle(task_id="my-task")
        assert h.task_id == "my-task"

    def test_parent_run_id_none(self) -> None:
        h = _make_handle()
        assert h.parent_run_id is None

    def test_parent_run_id_set(self) -> None:
        parent = "b" * 32
        h = _make_handle(parent_run_id=parent)
        assert h.parent_run_id == parent


class TestAddSpan:
    def test_returns_span_id(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api

        counter = [0]

        class CountingIdGen:
            def new_run_id(self) -> str:
                return "0" * 32

            def new_span_id(self) -> str:
                counter[0] += 1
                return format(counter[0], "032x")

            def new_score_id(self) -> str:
                return "0" * 32

            def new_example_id(self) -> str:
                return "0" * 32

        monkeypatch.setattr(_api, "_id_gen", CountingIdGen())
        h = _make_handle()
        sid = h.add_span(SpanKind.LLM, "gen")
        assert len(sid) == 32

    def test_span_buffered(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        h.add_span(SpanKind.TOOL, "fetch")
        assert len(h._builder.spans) == 1
        assert h._builder.spans[0].name == "fetch"

    def test_add_span_with_all_optional_fields(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        parent_span_id = "c" * 32
        input_hash = "d" * 64
        output_hash = "e" * 64
        h.add_span(
            SpanKind.LLM,
            "infer",
            parent_span_id=parent_span_id,
            input_hash=input_hash,
            output_hash=output_hash,
            tokens=(10, 20),
            latency_ms=42.0,
            status=SpanStatus.SUCCESS,
            error_type=None,
        )
        span = h._builder.spans[0]
        assert span.parent_span_id == parent_span_id
        assert span.tokens_in == 10
        assert span.tokens_out == 20
        assert span.latency_ms == 42.0

    def test_noop_after_abort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        h.abort("cancelled")
        result = h.add_span(SpanKind.LLM, "post-abort")
        assert result == ""
        assert len(h._builder.spans) == 0


class TestAddScore:
    def test_numeric_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from datetime import timezone
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        sid = h.add_score("accuracy", "deterministic", value_numeric=0.95)
        assert len(sid) == 32
        assert len(h._builder.scores) == 1
        assert h._builder.scores[0].value_numeric == 0.95

    def test_label_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        h.add_score("quality", "human", value_label="good")
        assert h._builder.scores[0].value_label == "good"

    def test_both_values_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.add_score("m", "deterministic", value_numeric=1.0, value_label="ok")

    def test_neither_value_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.add_score("m", "deterministic")

    def test_empty_metric_name_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.add_score("", "deterministic", value_numeric=1.0)

    def test_noop_after_abort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        h.abort("done")
        result = h.add_score("m", "deterministic", value_numeric=1.0)
        assert result == ""
        assert len(h._builder.scores) == 0


class TestSetModels:
    def test_last_call_wins(self) -> None:
        h = _make_handle()
        h.set_models(orchestrator_model="gpt-3")
        h.set_models(orchestrator_model="gpt-4")
        assert h._builder.orchestrator_model == "gpt-4"

    def test_partial_update(self) -> None:
        h = _make_handle()
        h.set_models(orchestrator_model="claude")
        h.set_models(sub_agent_model="haiku")
        assert h._builder.orchestrator_model == "claude"
        assert h._builder.sub_agent_model == "haiku"


class TestAbort:
    def test_sets_aborted_flag(self) -> None:
        h = _make_handle()
        h.abort("user cancelled")
        assert h._builder.aborted is True
        assert h._builder.abort_reason == "user cancelled"

    def test_empty_reason_raises(self) -> None:
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.abort("")

    def test_already_buffered_spans_preserved(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        h.add_span(SpanKind.LLM, "before-abort")
        h.abort("stop")
        h.add_span(SpanKind.LLM, "after-abort")
        assert len(h._builder.spans) == 1
        assert h._builder.spans[0].name == "before-abort"

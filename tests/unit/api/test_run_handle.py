"""Tests for RunHandle (Task 5.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plumb.api import RunHandle, _RunBuilder
from plumb.core.entities import RunKind, SpanKind, SpanStatus
from plumb.core.errors import ValidationError

_START = datetime(2024, 1, 1, tzinfo=UTC)
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

    def test_attributes_round_trip_into_buffered_span(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        attrs = {"lane": "planned", "engine": "codex", "attempt_n": 2}
        h.add_span(SpanKind.LLM, "gen", attributes=attrs)
        assert h._builder.spans[0].attributes == attrs

    def test_non_serializable_attributes_raises_no_span_buffered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.add_span(SpanKind.LLM, "gen", attributes={"bad": object()})
        assert len(h._builder.spans) == 0

    def test_oversized_attributes_raises_no_span_buffered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        huge = {"blob": "x" * 9000}
        with pytest.raises(ValidationError):
            h.add_span(SpanKind.LLM, "gen", attributes=huge)
        assert len(h._builder.spans) == 0

    def test_attributes_none_by_default(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        h = _make_handle()
        h.add_span(SpanKind.LLM, "gen")
        assert h._builder.spans[0].attributes is None


class TestAddScore:
    def test_numeric_score(self, monkeypatch: pytest.MonkeyPatch) -> None:

        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        sid = h.add_score("accuracy", "deterministic", value_numeric=0.95)
        assert len(sid) == 32
        assert len(h._builder.scores) == 1
        assert h._builder.scores[0][0].value_numeric == 0.95

    def test_label_score(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        h.add_score("quality", "human", value_label="good")
        assert h._builder.scores[0][0].value_label == "good"

    def test_idempotency_key_buffered_alongside_score(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator

        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        h = _make_handle()
        h.add_score("accuracy", "deterministic", value_numeric=0.95, idempotency_key="my-key")
        _score, key = h._builder.scores[0]
        assert key == "my-key"

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


class TestAddExample:
    def test_creates_example_row_with_expected_fields(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator, FakeStorageWriter

        fake_storage = FakeStorageWriter()
        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        monkeypatch.setattr(_api, "_storage_writer", fake_storage)
        h = _make_handle(task_id="my-task")
        example_id = h.add_example("a" * 64, source="production_promotion")

        assert len(example_id) == 32
        assert len(fake_storage.examples) == 1
        ex = fake_storage.examples[0]
        assert ex.example_id == example_id
        assert ex.origin_run_id == _RUN_ID
        assert ex.task_id == "my-task"
        assert ex.active is True
        assert ex.source.value == "production_promotion"

    def test_malformed_hash_raises_validation_error_no_write(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator, FakeStorageWriter

        fake_storage = FakeStorageWriter()
        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        monkeypatch.setattr(_api, "_storage_writer", fake_storage)
        h = _make_handle()
        with pytest.raises(ValidationError):
            h.add_example("not-hex", source="synthetic")
        assert len(fake_storage.examples) == 0

    def test_noop_after_abort(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import plumb.api as _api
        from tests.conftest import FakeClock, FakeIdGenerator, FakeStorageWriter

        fake_storage = FakeStorageWriter()
        monkeypatch.setattr(_api, "_id_gen", FakeIdGenerator())
        monkeypatch.setattr(_api, "_clock", FakeClock())
        monkeypatch.setattr(_api, "_storage_writer", fake_storage)
        h = _make_handle()
        h.abort("stop")
        example_id = h.add_example("a" * 64, source="synthetic")
        assert example_id == ""
        assert len(fake_storage.examples) == 0


class TestSetUsage:
    def test_all_fields_buffered(self) -> None:
        h = _make_handle()
        h.set_usage(tokens_in=100, tokens_out=250, dollar_cost=0.0123)
        assert h._builder.usage_tokens_in == 100
        assert h._builder.usage_tokens_out == 250
        assert h._builder.usage_dollar_cost == 0.0123

    def test_last_call_wins_per_field(self) -> None:
        h = _make_handle()
        h.set_usage(tokens_in=10, dollar_cost=1.0)
        h.set_usage(tokens_in=20)
        assert h._builder.usage_tokens_in == 20
        assert h._builder.usage_dollar_cost == 1.0

    def test_partial_call_does_not_clear_other_fields(self) -> None:
        h = _make_handle()
        h.set_usage(tokens_in=10, tokens_out=20, dollar_cost=1.0)
        h.set_usage(tokens_out=99)
        assert h._builder.usage_tokens_in == 10
        assert h._builder.usage_tokens_out == 99
        assert h._builder.usage_dollar_cost == 1.0

    def test_defaults_none(self) -> None:
        h = _make_handle()
        assert h._builder.usage_tokens_in is None
        assert h._builder.usage_tokens_out is None
        assert h._builder.usage_dollar_cost is None

    def test_noop_after_abort(self) -> None:
        h = _make_handle()
        h.abort("stop")
        h.set_usage(tokens_in=10, tokens_out=20, dollar_cost=1.0)
        assert h._builder.usage_tokens_in is None
        assert h._builder.usage_tokens_out is None
        assert h._builder.usage_dollar_cost is None


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

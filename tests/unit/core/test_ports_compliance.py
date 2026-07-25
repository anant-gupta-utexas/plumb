"""Verify that hand-built fakes satisfy each Port Protocol via isinstance."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from plumb.core.entities import Example, JudgeResult, Run, RunKind, RunStatus, Score, Span
from plumb.core.ports import (
    BlobStore,
    Clock,
    IdGenerator,
    JudgeAdapter,
    StorageReader,
    StorageWriter,
)

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    def now(self) -> datetime:
        return datetime(2024, 1, 1, tzinfo=UTC)


class FakeIdGenerator:
    _seq: int = 0

    def _next(self) -> str:
        self._seq += 1
        return format(self._seq, "032x")

    def new_run_id(self) -> str:
        return self._next()

    def new_span_id(self) -> str:
        return self._next()

    def new_score_id(self) -> str:
        return self._next()

    def new_example_id(self) -> str:
        return self._next()


class FakeStorageWriter:
    def __init__(self) -> None:
        self.runs: list[tuple[Run, list[Span]]] = []
        self.scores: list[Score] = []
        self.examples: list[Example] = []

    def open_run(
        self,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: datetime,
    ) -> None:
        pass

    def finalize_run(
        self,
        run_id: str,
        status: RunStatus,
        end_ts: datetime,
        spans: Sequence[Span],
        *,
        error_type: str | None = None,
        orchestrator_model: str | None = None,
        sub_agent_model: str | None = None,
        prompt_version: str | None = None,
        tool_schema_version: str | None = None,
        git_sha: str | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        dollar_cost: float | None = None,
    ) -> None:
        pass

    def write_run(self, run: Run, spans: Sequence[Span]) -> None:
        self.runs.append((run, list(spans)))

    def write_score(self, score: Score, *, idempotency_key: str | None = None) -> bool:
        del idempotency_key
        self.scores.append(score)
        return True

    def write_example(self, example: Example) -> None:
        self.examples.append(example)

    def open_or_resume(self, run_id: str) -> Run:
        for run, _spans in self.runs:
            if run.run_id == run_id:
                return run
        raise ValueError(f"run {run_id!r} not found")


class FakeStorageReader:
    def get_run(self, run_id: str) -> Run | None:
        return None

    def list_runs(
        self,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Run]:
        return []

    def get_spans_for_run(self, run_id: str) -> list[Span]:
        return []

    def get_scores_for_run(self, run_id: str) -> list[Score]:
        return []

    def list_examples(
        self,
        *,
        task_id: str | None = None,
        active: bool | None = None,
    ) -> list[Example]:
        return []

    def list_runs_with_counts(
        self,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        limit: int = 100,
    ) -> list:
        return []

    def list_runs_with_counts_paged(
        self,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list, int]:
        return [], 0

    def aggregate_runs_for_task(
        self,
        task_id: str,
        *,
        since: datetime | None = None,
    ) -> object:
        return None

    def aggregate_scores_for_task(
        self,
        task_id: str,
        *,
        since: datetime | None = None,
    ) -> list[object]:
        return []


class FakeBlobStore:
    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}

    def put(self, content: bytes) -> str:
        import hashlib

        key = hashlib.sha256(content).hexdigest()
        self._store[key] = content
        return key

    def get(self, sha256_hex: str) -> bytes:
        return self._store[sha256_hex]

    def exists(self, sha256_hex: str) -> bool:
        return sha256_hex in self._store


class FakeJudgeAdapter:
    name = "fake"
    version = "0.0.1"

    def score(
        self,
        *,
        metric_name: str,
        prompt: str,
        content: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> JudgeResult:
        return JudgeResult(
            metric_name=metric_name,
            scorer_version=self.version,
            rationale="fake",
            tokens_in=0,
            tokens_out=0,
            latency_ms=0.0,
            value_numeric=1.0,
        )


# ---------------------------------------------------------------------------
# Protocol compliance tests
# ---------------------------------------------------------------------------


def test_fake_clock_satisfies_clock_protocol() -> None:
    fake = FakeClock()
    assert isinstance(fake, Clock)


def test_fake_id_generator_satisfies_id_generator_protocol() -> None:
    fake = FakeIdGenerator()
    assert isinstance(fake, IdGenerator)


def test_fake_storage_writer_satisfies_storage_writer_protocol() -> None:
    fake = FakeStorageWriter()
    assert isinstance(fake, StorageWriter)


def test_fake_storage_writer_finalize_run_accepts_usage_kwargs() -> None:
    """isinstance() against a runtime_checkable Protocol only checks method
    *names*, not signatures — a stale fake missing tokens_in/tokens_out/
    dollar_cost would still pass the isinstance check above while breaking at
    call time. This is the actual regression guard (Task 12)."""
    import inspect

    fake_params = set(inspect.signature(FakeStorageWriter.finalize_run).parameters)
    real_params = set(inspect.signature(StorageWriter.finalize_run).parameters)
    assert real_params <= fake_params


def test_fake_storage_writer_write_score_accepts_idempotency_key() -> None:
    import inspect

    fake_params = set(inspect.signature(FakeStorageWriter.write_score).parameters)
    real_params = set(inspect.signature(StorageWriter.write_score).parameters)
    assert real_params <= fake_params


def test_fake_storage_writer_has_open_or_resume() -> None:
    assert hasattr(FakeStorageWriter, "open_or_resume")


# ---------------------------------------------------------------------------
# Task 12: sweep the real test double + the production no-op double, not just
# this file's local FakeStorageWriter. isinstance() alone is insufficient
# (Protocol structural checks ignore signatures) so this compares parameter
# sets directly against the current StorageWriter Protocol methods.
# ---------------------------------------------------------------------------


def _assert_signature_superset(cls: type, method_name: str) -> None:
    import inspect

    real_params = set(inspect.signature(getattr(StorageWriter, method_name)).parameters)
    impl_params = set(inspect.signature(getattr(cls, method_name)).parameters)
    missing = real_params - impl_params
    assert not missing, f"{cls.__name__}.{method_name} missing params: {missing}"


def test_conftest_fake_storage_writer_matches_protocol() -> None:
    from tests.conftest import FakeStorageWriter as RealFakeStorageWriter

    assert isinstance(RealFakeStorageWriter(), StorageWriter)
    for method in ("open_run", "finalize_run", "write_run", "write_score", "write_example"):
        _assert_signature_superset(RealFakeStorageWriter, method)
    assert hasattr(RealFakeStorageWriter, "open_or_resume")


def test_noop_storage_writer_matches_protocol() -> None:
    from plumb.api import _NoopStorageWriter

    assert isinstance(_NoopStorageWriter(), StorageWriter)
    for method in ("open_run", "finalize_run", "write_run", "write_score", "write_example"):
        _assert_signature_superset(_NoopStorageWriter, method)
    assert hasattr(_NoopStorageWriter, "open_or_resume")


def test_fake_storage_reader_satisfies_storage_reader_protocol() -> None:
    fake = FakeStorageReader()
    assert isinstance(fake, StorageReader)


def test_fake_blob_store_satisfies_blob_store_protocol() -> None:
    fake = FakeBlobStore()
    assert isinstance(fake, BlobStore)


def test_fake_judge_adapter_satisfies_judge_adapter_protocol() -> None:
    fake = FakeJudgeAdapter()
    assert isinstance(fake, JudgeAdapter)


# ---------------------------------------------------------------------------
# Behavioural smoke tests for each fake
# ---------------------------------------------------------------------------


def test_fake_clock_returns_tz_aware_datetime() -> None:
    result = FakeClock().now()
    assert result.tzinfo is not None


def test_fake_id_generator_returns_32_char_hex() -> None:
    gen = FakeIdGenerator()
    for method in (gen.new_run_id, gen.new_span_id, gen.new_score_id, gen.new_example_id):
        result = method()
        assert len(result) == 32
        assert all(c in "0123456789abcdef" for c in result)


def test_fake_blob_store_round_trip() -> None:
    store = FakeBlobStore()
    key = store.put(b"hello")
    assert store.get(key) == b"hello"
    assert len(key) == 64


def test_fake_judge_adapter_returns_judge_result() -> None:
    adapter = FakeJudgeAdapter()
    result = adapter.score(
        metric_name="accuracy",
        prompt="rate this",
        content="good answer",
        model="claude-3",
    )
    assert result.metric_name == "accuracy"
    assert result.value_numeric == 1.0

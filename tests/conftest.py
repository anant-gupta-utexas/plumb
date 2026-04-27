"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import UTC, datetime

import pytest

import plumb.api as _api
from plumb.core.entities import Example, Run, RunKind, RunStatus, Score, Span

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic clock: increments by 1 second each call."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2024, 1, 1, tzinfo=UTC)
        self._step = 0

    def now(self) -> datetime:
        from datetime import timedelta

        ts = self._t + timedelta(seconds=self._step)
        self._step += 1
        return ts


class FakeIdGenerator:
    """Sequential ID generator: produces 32-char lowercase hex strings."""

    def __init__(self) -> None:
        self._counter = 0

    def _next(self) -> str:
        self._counter += 1
        return format(self._counter, "032x")

    def new_run_id(self) -> str:
        return self._next()

    def new_span_id(self) -> str:
        return self._next()

    def new_score_id(self) -> str:
        return self._next()

    def new_example_id(self) -> str:
        return self._next()


class FakeStorageWriter:
    """In-memory storage writer that records all calls for assertion.

    Implements the two-phase open_run / finalize_run protocol so the API layer
    can use it transparently.  On finalize_run the run_id and accumulated spans
    are assembled into the same (Run, [Span]) tuple the old write_run tests
    relied on, keeping existing test assertions compatible.
    """

    def __init__(self) -> None:
        self.runs: list[tuple[Run, list[Span]]] = []
        self.scores: list[Score] = []
        self.examples: list[Example] = []
        # Staging area: run_id → (task_id, kind, parent_run_id, start_ts)
        self._pending: dict[str, tuple[str, RunKind, str | None, datetime]] = {}

    def open_run(
        self,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: datetime,
    ) -> None:
        self._pending[run_id] = (task_id, kind, parent_run_id, start_ts)

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
    ) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            task_id, kind, parent_run_id, start_ts = "unknown", RunKind.ONLINE, None, end_ts
        else:
            task_id, kind, parent_run_id, start_ts = pending
        run = Run(
            run_id=run_id,
            task_id=task_id,
            kind=kind,
            status=status,
            start_ts=start_ts,
            end_ts=end_ts,
            parent_run_id=parent_run_id,
            error_type=error_type,
            orchestrator_model=orchestrator_model,
            sub_agent_model=sub_agent_model,
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
            git_sha=git_sha,
        )
        self.runs.append((run, list(spans)))

    def write_run(self, run: Run, spans: Sequence[Span]) -> None:
        self.runs.append((run, list(spans)))

    def write_score(self, score: Score) -> None:
        self.scores.append(score)

    def write_example(self, example: Example) -> None:
        self.examples.append(example)

    # -- convenience helpers --------------------------------------------------

    @property
    def last_run(self) -> Run:
        return self.runs[-1][0]

    @property
    def last_spans(self) -> list[Span]:
        return self.runs[-1][1]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_id_gen() -> FakeIdGenerator:
    return FakeIdGenerator()


@pytest.fixture
def fake_storage() -> FakeStorageWriter:
    return FakeStorageWriter()


@pytest.fixture
def configured_api(
    monkeypatch: pytest.MonkeyPatch,
    fake_clock: FakeClock,
    fake_id_gen: FakeIdGenerator,
    fake_storage: FakeStorageWriter,
) -> Iterator[FakeStorageWriter]:
    """Monkeypatches plumb.api singletons with deterministic fakes.

    Yields the FakeStorageWriter so tests can inspect recorded calls.
    """
    monkeypatch.setattr(_api, "_clock", fake_clock)
    monkeypatch.setattr(_api, "_id_gen", fake_id_gen)
    monkeypatch.setattr(_api, "_storage_writer", fake_storage)
    monkeypatch.setattr(_api, "_storage", fake_storage)
    yield fake_storage

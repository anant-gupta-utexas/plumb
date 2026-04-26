"""Pytest configuration and shared fixtures."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timezone
from typing import Iterator

import pytest

import plumb.api as _api
from plumb.core.entities import Example, Run, Score, Span


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class FakeClock:
    """Deterministic clock: increments by 1 second each call."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
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
    """In-memory storage writer that records all calls for assertion."""

    def __init__(self) -> None:
        self.runs: list[tuple[Run, list[Span]]] = []
        self.scores: list[Score] = []
        self.examples: list[Example] = []

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
    yield fake_storage

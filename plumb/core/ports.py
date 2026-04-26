"""Port Protocols for plumb — interfaces implemented by adapters (TRD §3.2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from plumb.core.entities import Example, JudgeResult, Run, Score, Span


@runtime_checkable
class Clock(Protocol):
    """Provides the current UTC time."""

    def now(self) -> datetime: ...


@runtime_checkable
class IdGenerator(Protocol):
    """Generates collision-resistant 32-char lowercase hex IDs."""

    def new_run_id(self) -> str: ...
    def new_span_id(self) -> str: ...
    def new_score_id(self) -> str: ...
    def new_example_id(self) -> str: ...


@runtime_checkable
class StorageWriter(Protocol):
    """Write-only storage port — implemented by the SQLite adapter."""

    def write_run(self, run: Run, spans: Sequence[Span]) -> None: ...
    def write_score(self, score: Score) -> None: ...
    def write_example(self, example: Example) -> None: ...


@runtime_checkable
class StorageReader(Protocol):
    """Read-only storage port — used by CLI and HTTP service."""

    def get_run(self, run_id: str) -> Run | None: ...
    def list_runs(
        self,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Run]: ...
    def get_spans_for_run(self, run_id: str) -> list[Span]: ...
    def get_scores_for_run(self, run_id: str) -> list[Score]: ...
    def list_examples(
        self,
        *,
        task_id: str | None = None,
        active: bool | None = None,
    ) -> list[Example]: ...


@runtime_checkable
class BlobStore(Protocol):
    """Content-addressed binary blob store."""

    def put(self, content: bytes) -> str: ...
    def get(self, sha256_hex: str) -> bytes: ...


@runtime_checkable
class JudgeAdapter(Protocol):
    """LLM-as-judge adapter — scores a single (prompt, content) pair."""

    name: str
    version: str

    def score(
        self,
        *,
        metric_name: str,
        prompt: str,
        content: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> JudgeResult: ...

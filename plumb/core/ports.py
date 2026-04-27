"""Port Protocols for plumb — interfaces implemented by adapters (TRD §3.2)."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Protocol, runtime_checkable

from plumb.core.entities import Example, JudgeResult, Run, RunKind, RunStatus, Score, Span


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
    """Write-only storage port — implemented by the SQLite adapter.

    The two-phase write protocol (open_run / finalize_run) ensures that nested
    runs always satisfy the parent_run_id FK: the parent row is INSERT-ed at
    __enter__ time (status='pending'), and both parent and child rows exist in
    the DB before the child's finalize_run fires at __exit__ (FR-GRAPH-1).

    write_run remains available as a single-shot convenience for direct adapter
    use (tests, ATTACH adapter backfill).
    """

    def open_run(
        self,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: datetime,
    ) -> None: ...

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
    ) -> None: ...

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

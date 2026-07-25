"""Public `run` callable — decorator + context manager (sync + async)."""

from __future__ import annotations

import functools
import inspect
import json
import logging
import uuid
from collections.abc import Callable, Sequence
from contextvars import ContextVar, Token
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from plumb.core.entities import (
    Example,
    ExampleSource,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)
from plumb.core.errors import NotFoundError, ValidationError
from plumb.core.ports import Clock, IdGenerator, StorageWriter

if TYPE_CHECKING:
    from plumb.adapters.blobstore_fs import FilesystemBlobStore
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter

logger = logging.getLogger(__name__)

_ATTRIBUTES_MAX_BYTES = 8 * 1024  # ~8KB soft cap (FR-ATTR-4)


def _validate_attributes(attributes: dict[str, Any] | None) -> None:
    """Fail-closed at the API boundary (FR-ATTR-3/4): non-serializable or
    oversized payloads raise ValidationError before any span is buffered."""
    if attributes is None:
        return
    try:
        encoded = json.dumps(attributes)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"attributes must be JSON-serializable: {exc}") from exc
    if len(encoded.encode("utf-8")) > _ATTRIBUTES_MAX_BYTES:
        raise ValidationError(
            f"attributes payload exceeds the {_ATTRIBUTES_MAX_BYTES}-byte soft cap"
        )


# ---------------------------------------------------------------------------
# Module-level singletons (DI pattern — tests monkeypatch these)
# ---------------------------------------------------------------------------


class _DefaultClock:
    def now(self) -> datetime:
        from datetime import UTC

        return datetime.now(tz=UTC)


class _DefaultIdGenerator:
    def new_run_id(self) -> str:
        return uuid.uuid4().hex

    def new_span_id(self) -> str:
        return uuid.uuid4().hex

    def new_score_id(self) -> str:
        return uuid.uuid4().hex

    def new_example_id(self) -> str:
        return uuid.uuid4().hex


class _NoopStorageWriter:
    """Silently discards all writes.

    This is the initial value of ``_storage_writer`` before
    ``_init_storage_singletons`` runs.  Tests that inject a fake adapter
    before any ``with run(...)`` call will never see this class — it only
    survives if a test monkeypatches neither ``_storage`` nor
    ``_storage_writer``, in which case all write calls are deliberate no-ops.
    """

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
        pass

    def write_score(self, score: Score, *, idempotency_key: str | None = None) -> bool:
        return True

    def write_example(self, example: Example) -> None:
        pass

    def open_or_resume(self, run_id: str) -> Run:
        raise NotFoundError(f"run {run_id!r} not found")


_clock: Clock = _DefaultClock()
_id_gen: IdGenerator = _DefaultIdGenerator()
_storage_writer: StorageWriter = _NoopStorageWriter()

# Real adapter singletons — None until first run(), allowing tests to monkeypatch first.
_storage: SQLiteStorageAdapter | None = None
_blobstore: FilesystemBlobStore | None = None


def _init_storage_singletons() -> None:
    """Lazily bootstrap real adapters on first run() call.

    No-op if _storage is already set (either by previous call or test monkeypatch).
    Imports adapters inside the function to preserve the cold-import budget (NFR-Perf-6).
    """
    global _storage, _blobstore, _storage_writer
    if _storage is not None:
        return

    from plumb.adapters.blobstore_fs import FilesystemBlobStore
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from plumb.config import ensure_data_dir, get_settings

    settings = get_settings()
    data_dir = ensure_data_dir(settings)
    _storage = SQLiteStorageAdapter(data_dir / "plumb.db", clock=_clock)
    _blobstore = FilesystemBlobStore(data_dir / "blobs")
    _storage_writer = _storage

    if settings.autocapture:
        import plumb.autocapture as autocapture

        autocapture.install()


# ---------------------------------------------------------------------------
# Contextvar — tracks the active RunHandle in the current task/thread
# ---------------------------------------------------------------------------

_active_run: ContextVar[RunHandle | None] = ContextVar("plumb_active_run", default=None)

# ---------------------------------------------------------------------------
# _RunBuilder — mutable staging area before Run is frozen
# ---------------------------------------------------------------------------

_SENTINEL = object()


class _RunBuilder:
    """Mutable staging area that accumulates state before freeze() produces a Run."""

    __slots__ = (
        "run_id",
        "task_id",
        "kind",
        "parent_run_id",
        "start_ts",
        "orchestrator_model",
        "sub_agent_model",
        "prompt_version",
        "tool_schema_version",
        "git_sha",
        "spans",
        "scores",
        "aborted",
        "abort_reason",
        "status",
        "end_ts",
        "error_type",
        "usage_tokens_in",
        "usage_tokens_out",
        "usage_dollar_cost",
    )

    def __init__(
        self,
        *,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: datetime,
        orchestrator_model: str | None = None,
        sub_agent_model: str | None = None,
        prompt_version: str | None = None,
        tool_schema_version: str | None = None,
        git_sha: str | None = None,
    ) -> None:
        self.run_id = run_id
        self.task_id = task_id
        self.kind = kind
        self.parent_run_id = parent_run_id
        self.start_ts = start_ts
        self.orchestrator_model = orchestrator_model
        self.sub_agent_model = sub_agent_model
        self.prompt_version = prompt_version
        self.tool_schema_version = tool_schema_version
        self.git_sha = git_sha
        self.spans: list[Span] = []
        self.scores: list[tuple[Score, str | None]] = []
        self.aborted: bool = False
        self.abort_reason: str | None = None
        self.status: RunStatus | None = None
        self.end_ts: datetime | None = None
        self.error_type: str | None = None
        self.usage_tokens_in: int | None = None
        self.usage_tokens_out: int | None = None
        self.usage_dollar_cost: float | None = None

    def freeze(self) -> Run:
        """Produce an immutable Run from the current builder state."""
        if self.status is None:
            raise ValidationError("status must be set before freeze()")
        return Run(
            run_id=self.run_id,
            task_id=self.task_id,
            kind=self.kind,
            status=self.status,
            start_ts=self.start_ts,
            end_ts=self.end_ts,
            parent_run_id=self.parent_run_id,
            orchestrator_model=self.orchestrator_model,
            sub_agent_model=self.sub_agent_model,
            prompt_version=self.prompt_version,
            tool_schema_version=self.tool_schema_version,
            git_sha=self.git_sha,
            error_type=self.error_type,
        )


# ---------------------------------------------------------------------------
# RunHandle — user-facing handle yielded by `with run(...) as r:`
# ---------------------------------------------------------------------------


class RunHandle:
    """Handle to an active run. Obtain via `with run(...) as r:` — not directly constructible."""

    __slots__ = ("_builder", "_open_frame_id")

    def __init__(self, _builder: _RunBuilder | None = None) -> None:
        if _builder is None:
            raise TypeError(
                "RunHandle is not user-constructible; obtain one via `with run(...) as r:`"
            )
        self._builder: _RunBuilder = _builder
        self._open_frame_id: int | None = None

    # -- read-only properties -------------------------------------------------

    @property
    def run_id(self) -> str:
        return self._builder.run_id

    @property
    def parent_run_id(self) -> str | None:
        return self._builder.parent_run_id

    @property
    def task_id(self) -> str:
        return self._builder.task_id

    # -- mutation methods -----------------------------------------------------

    def add_span(
        self,
        kind: SpanKind | str,
        name: str,
        *,
        parent_span_id: str | None = None,
        input_hash: str | None = None,
        output_hash: str | None = None,
        tokens: tuple[int, int] | None = None,
        latency_ms: float | None = None,
        status: SpanStatus | str | None = None,
        error_type: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> str:
        """Buffer a span; returns span_id. No-op after abort().

        ``attributes`` must be JSON-serializable and under an ~8KB soft cap —
        validated here (fail-closed) before the span is buffered (FR-ATTR-3/4).
        """
        if self._builder.aborted:
            return ""
        _validate_attributes(attributes)
        span_id = _id_gen.new_span_id()
        tokens_in: int | None = None
        tokens_out: int | None = None
        if tokens is not None:
            tokens_in, tokens_out = tokens
        span = Span(
            span_id=span_id,
            run_id=self._builder.run_id,
            kind=SpanKind(kind) if isinstance(kind, str) else kind,
            name=name,
            parent_span_id=parent_span_id,
            input_hash=input_hash,
            output_hash=output_hash,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
            status=SpanStatus(status) if isinstance(status, str) else status,
            error_type=error_type,
            attributes=attributes,
        )
        self._builder.spans.append(span)
        return span_id

    def add_score(
        self,
        metric_name: str,
        scorer: ScorerKind | str,
        *,
        value_numeric: float | None = None,
        value_label: str | None = None,
        span_id: str | None = None,
        scorer_version: str | None = None,
        rationale: str | None = None,
        idempotency_key: str | None = None,
    ) -> str:
        """Buffer a score; returns score_id. No-op after abort().

        ``idempotency_key`` is advisory only (FR-IDEM-4) — the actual dedup
        enforcement is the storage layer's UNIQUE index on
        ``(run_id, metric_name, scorer_version, span_id)``.
        """
        if self._builder.aborted:
            return ""
        # XOR validation — raises synchronously
        numeric_set = value_numeric is not None
        label_set = value_label is not None
        if numeric_set == label_set:
            raise ValidationError("Exactly one of value_numeric or value_label must be set (XOR)")
        if not metric_name:
            raise ValidationError("metric_name must be non-empty")
        score_id = _id_gen.new_score_id()
        score = Score(
            score_id=score_id,
            run_id=self._builder.run_id,
            metric_name=metric_name,
            scorer=ScorerKind(scorer) if isinstance(scorer, str) else scorer,
            scorer_version=scorer_version or "unversioned",
            scored_at=_clock.now(),
            span_id=span_id,
            value_numeric=value_numeric,
            value_label=value_label,
            rationale=rationale,
        )
        self._builder.scores.append((score, idempotency_key))
        return score_id

    def set_models(
        self,
        *,
        orchestrator_model: str | None = None,
        sub_agent_model: str | None = None,
    ) -> None:
        """Late-bind model fields; last call wins."""
        if orchestrator_model is not None:
            self._builder.orchestrator_model = orchestrator_model
        if sub_agent_model is not None:
            self._builder.sub_agent_model = sub_agent_model

    def add_example(
        self,
        inputs_hash: str,
        *,
        source: ExampleSource | str,
        expected_output_hash: str | None = None,
        rubric: str | None = None,
    ) -> str:
        """Promote the active run to a regression example; returns example_id.

        Writes immediately via the same `write_example` path `plumb example
        promote` (CLI) uses — not buffered like `add_span`/`add_score`. No-op
        after `abort()`. Hash validation happens via `Example.__post_init__`
        (raises `ValidationError` before any write).
        """
        if self._builder.aborted:
            return ""
        example_id = _id_gen.new_example_id()
        example = Example(
            example_id=example_id,
            task_id=self._builder.task_id,
            inputs_hash=inputs_hash,
            expected_output_hash=expected_output_hash,
            source=ExampleSource(source) if isinstance(source, str) else source,
            origin_run_id=self._builder.run_id,
            active=True,
            rubric=rubric,
            created_at=_clock.now(),
        )
        try:
            _storage_writer.write_example(example)
        except Exception as err:
            # NFR-Rel-1: NEVER raise plumb-internal failure into caller
            logger.warning(
                "plumb storage failure (write_example)",
                extra={
                    "plumb_internal_error": True,
                    "run_id": self._builder.run_id,
                    "error_class": type(err).__name__,
                },
            )
        return example_id

    def set_usage(
        self,
        *,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
        dollar_cost: float | None = None,
    ) -> None:
        """Late-bind run-level usage/cost fields; last call wins (FR-USAGE-1).

        If never called, `tokens_in`/`tokens_out` are auto-filled at close
        time from the buffered spans' split token fields (FR-USAGE-3).
        `dollar_cost` is NEVER auto-filled — absent an explicit call it stays
        `NULL` (FR-USAGE-3a). No-op after `abort()` (FR-USAGE-5).
        """
        if self._builder.aborted:
            return
        if tokens_in is not None:
            self._builder.usage_tokens_in = tokens_in
        if tokens_out is not None:
            self._builder.usage_tokens_out = tokens_out
        if dollar_cost is not None:
            self._builder.usage_dollar_cost = dollar_cost

    def abort(self, reason: str) -> None:
        """Mark run as aborted; future add_* calls become no-ops, buffered spans are preserved."""
        if not reason:
            raise ValidationError("abort reason must be non-empty")
        self._builder.aborted = True
        self._builder.abort_reason = reason


# ---------------------------------------------------------------------------
# _RunFactory — returned by run(); implements decorator + context manager
# ---------------------------------------------------------------------------


def _compute_run_level_tokens(
    explicit_tokens_in: int | None,
    explicit_tokens_out: int | None,
    buffered_spans: list[Span],
) -> tuple[int | None, int | None]:
    """FR-USAGE-3 auto-fill precedence: explicit set_usage() wins per-field
    (no merge with the span sum); otherwise sum the buffered spans' split
    tokens_in/tokens_out, excluding any span with tokens_in is None."""
    if explicit_tokens_in is not None or explicit_tokens_out is not None:
        return explicit_tokens_in, explicit_tokens_out
    eligible = [s for s in buffered_spans if s.tokens_in is not None]
    if not eligible:
        return None, None
    return (
        sum(s.tokens_in or 0 for s in eligible),
        sum(s.tokens_out or 0 for s in eligible),
    )


def _finalize_and_write(
    builder: _RunBuilder,
    exc_type: type[BaseException] | None,
) -> None:
    """Shared close-out logic for `_RunFactory` and `_ResumeRunFactory`.

    Determines final status, calls `finalize_run` (an UPDATE regardless of
    whether the row was opened via `open_run` or resumed via
    `open_or_resume`), and flushes buffered scores. Never raises
    (NFR-Rel-1) — storage failures are logged and swallowed.
    """
    if exc_type is not None:
        builder.status = RunStatus.FAILURE
        builder.error_type = exc_type.__name__
    elif builder.aborted:
        builder.status = RunStatus.ABORTED
        builder.error_type = builder.abort_reason
    else:
        builder.status = RunStatus.SUCCESS

    builder.end_ts = _clock.now()

    try:
        spans = list(builder.spans)
        scores = list(builder.scores)
        tokens_in, tokens_out = _compute_run_level_tokens(
            builder.usage_tokens_in, builder.usage_tokens_out, spans
        )
        _storage_writer.finalize_run(
            builder.run_id,
            builder.status,
            builder.end_ts,
            spans,
            error_type=builder.error_type,
            orchestrator_model=builder.orchestrator_model,
            sub_agent_model=builder.sub_agent_model,
            prompt_version=builder.prompt_version,
            tool_schema_version=builder.tool_schema_version,
            git_sha=builder.git_sha,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            dollar_cost=builder.usage_dollar_cost,
        )
        for score, idempotency_key in scores:
            _storage_writer.write_score(score, idempotency_key=idempotency_key)
    except Exception as err:
        # NFR-Rel-1: NEVER raise plumb-internal failure into caller
        logger.warning(
            "plumb storage failure",
            extra={
                "plumb_internal_error": True,
                "run_id": builder.run_id,
                "error_class": type(err).__name__,
            },
        )


class _RunFactory:
    """Returned by `run(...)`. Usable as decorator OR context manager (sync + async)."""

    __slots__ = (
        "task_id",
        "kind",
        "_explicit_parent_run_id",
        "orchestrator_model",
        "sub_agent_model",
        "prompt_version",
        "tool_schema_version",
        "git_sha",
        "_is_decorator_call",
        "_frame_id",
        "_deduped",
        "_token",
        "_handle",
    )

    def __init__(
        self,
        *,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        orchestrator_model: str | None,
        sub_agent_model: str | None,
        prompt_version: str | None,
        tool_schema_version: str | None,
        git_sha: str | None,
    ) -> None:
        self.task_id = task_id
        self.kind = kind
        self._explicit_parent_run_id = parent_run_id
        self.orchestrator_model = orchestrator_model
        self.sub_agent_model = sub_agent_model
        self.prompt_version = prompt_version
        self.tool_schema_version = tool_schema_version
        self.git_sha = git_sha
        self._is_decorator_call: bool = False
        self._frame_id: int | None = None
        self._deduped: bool = False
        self._token: Token[RunHandle | None] | None = None
        self._handle: RunHandle | None = None

    # -- context manager (sync) -----------------------------------------------

    def __enter__(self) -> RunHandle:
        _init_storage_singletons()
        self._deduped = False
        parent_handle = _active_run.get()

        # FR-GRAPH-1 / FR-GRAPH-2: resolve parent
        parent_run_id: str | None = (
            parent_handle.run_id if parent_handle else self._explicit_parent_run_id
        )

        # FR-EDGE-4: nested-decorator dedup
        if (
            self._is_decorator_call
            and parent_handle is not None
            and parent_handle._open_frame_id == self._frame_id
        ):
            self._deduped = True
            self._handle = parent_handle
            return parent_handle

        start_ts = _clock.now()
        run_id = _id_gen.new_run_id()
        builder = _RunBuilder(
            run_id=run_id,
            kind=self.kind,
            task_id=self.task_id,
            parent_run_id=parent_run_id,
            start_ts=start_ts,
            orchestrator_model=self.orchestrator_model,
            sub_agent_model=self.sub_agent_model,
            prompt_version=self.prompt_version,
            tool_schema_version=self.tool_schema_version,
            git_sha=self.git_sha,
        )
        handle = RunHandle(builder)
        if self._is_decorator_call and self._frame_id is not None:
            handle._open_frame_id = self._frame_id
        self._token = _active_run.set(handle)
        self._handle = handle

        # INSERT the pending row immediately so parent_run_id FK is satisfied
        # before any child run's open_run fires (FR-GRAPH-1).
        try:
            _storage_writer.open_run(run_id, self.task_id, self.kind, parent_run_id, start_ts)
        except Exception as err:
            logger.warning(
                "plumb storage failure (open_run)",
                extra={
                    "plumb_internal_error": True,
                    "run_id": run_id,
                    "error_class": type(err).__name__,
                },
            )

        return handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        if self._deduped:
            return False  # outer no-op; never suppresses

        handle = self._handle
        if handle is None:
            return False
        builder = handle._builder

        try:
            _finalize_and_write(builder, exc_type)
        finally:
            if self._token is not None:
                _active_run.reset(self._token)
                self._token = None

        return False  # NEVER suppress user exceptions (FR-EDGE-1)

    # -- context manager (async) ----------------------------------------------

    async def __aenter__(self) -> RunHandle:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        return self.__exit__(exc_type, exc_val, exc_tb)

    # -- decorator path -------------------------------------------------------

    def __call__(self, fn: Callable[..., Any]) -> Callable[..., Any]:
        """Wrap fn as a decorator. Async fns get an async wrapper."""
        frame_id = id(fn)

        if inspect.iscoroutinefunction(fn):

            @functools.wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                factory = _RunFactory(
                    task_id=self.task_id,
                    kind=self.kind,
                    parent_run_id=self._explicit_parent_run_id,
                    orchestrator_model=self.orchestrator_model,
                    sub_agent_model=self.sub_agent_model,
                    prompt_version=self.prompt_version,
                    tool_schema_version=self.tool_schema_version,
                    git_sha=self.git_sha,
                )
                factory._is_decorator_call = True
                factory._frame_id = frame_id
                async with factory:
                    return await fn(*args, **kwargs)

            return async_wrapper

        else:

            @functools.wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                factory = _RunFactory(
                    task_id=self.task_id,
                    kind=self.kind,
                    parent_run_id=self._explicit_parent_run_id,
                    orchestrator_model=self.orchestrator_model,
                    sub_agent_model=self.sub_agent_model,
                    prompt_version=self.prompt_version,
                    tool_schema_version=self.tool_schema_version,
                    git_sha=self.git_sha,
                )
                factory._is_decorator_call = True
                factory._frame_id = frame_id
                with factory:
                    return fn(*args, **kwargs)

            return sync_wrapper


# ---------------------------------------------------------------------------
# _ResumeRunFactory — returned by resume_run(); context manager ONLY
# ---------------------------------------------------------------------------


class _ResumeRunFactory:
    """Returned by `resume_run(...)`. Context-manager only (sync + async) — no
    decorator form, since resuming requires an existing `run_id` value that
    can't be bound at decoration time."""

    __slots__ = ("run_id", "_token", "_handle")

    def __init__(self, *, run_id: str) -> None:
        self.run_id = run_id
        self._token: Token[RunHandle | None] | None = None
        self._handle: RunHandle | None = None

    def __enter__(self) -> RunHandle:
        _init_storage_singletons()

        # FR-RESUME-4 / AC-RESUME-3: raises NotFoundError if absent.
        existing = _storage_writer.open_or_resume(self.run_id)

        # FR-RESUME-2 / AC-RESUME-2: only a 'pending' run is resumable.
        # 'stalled' is treated as terminal-for-this-purpose (Pending Decision 1,
        # tasks file) — resuming a run the stalled-sweep already gave up on
        # would race the sweep.
        if existing.status != RunStatus.PENDING:
            raise ValidationError(
                f"run {self.run_id!r} is already terminal (status={existing.status.value!r})"
            )

        builder = _RunBuilder(
            run_id=existing.run_id,
            task_id=existing.task_id,
            kind=existing.kind,
            parent_run_id=existing.parent_run_id,
            start_ts=existing.start_ts,
            orchestrator_model=existing.orchestrator_model,
            sub_agent_model=existing.sub_agent_model,
            prompt_version=existing.prompt_version,
            tool_schema_version=existing.tool_schema_version,
            git_sha=existing.git_sha,
        )
        handle = RunHandle(builder)
        self._token = _active_run.set(handle)
        self._handle = handle
        return handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        handle = self._handle
        if handle is None:
            return False
        builder = handle._builder

        try:
            _finalize_and_write(builder, exc_type)
        finally:
            if self._token is not None:
                _active_run.reset(self._token)
                self._token = None

        return False  # NEVER suppress user exceptions (FR-EDGE-1)

    async def __aenter__(self) -> RunHandle:
        return self.__enter__()

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> Literal[False]:
        return self.__exit__(exc_type, exc_val, exc_tb)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def run(
    *,
    task_id: str,
    kind: RunKind | Literal["offline", "online"] = "online",
    parent_run_id: str | None = None,
    orchestrator_model: str | None = None,
    sub_agent_model: str | None = None,
    prompt_version: str | None = None,
    tool_schema_version: str | None = None,
    git_sha: str | None = None,
) -> _RunFactory:
    """Create a run factory usable as a decorator or context manager.

    Usage::

        # context manager
        with run(task_id="eval") as r:
            r.add_span(SpanKind.LLM, "generate")

        # decorator
        @run(task_id="eval")
        def my_fn(): ...
    """
    return _RunFactory(
        task_id=task_id,
        kind=RunKind(kind) if isinstance(kind, str) else kind,
        parent_run_id=parent_run_id,
        orchestrator_model=orchestrator_model,
        sub_agent_model=sub_agent_model,
        prompt_version=prompt_version,
        tool_schema_version=tool_schema_version,
        git_sha=git_sha,
    )


def resume_run(run_id: str) -> _ResumeRunFactory:
    """Re-open an existing (`pending`) run as a context manager.

    Unlike `run()`, this is context-manager only — there is no decorator form,
    since resuming requires an existing `run_id` that can't be bound at
    decoration time.

    Raises:
        NotFoundError: if `run_id` doesn't exist.
        ValidationError: if the run is already terminal
            (`success`/`failure`/`aborted`/`stalled`).

    Usage::

        with plumb.resume_run(run_id) as r:
            r.add_span(SpanKind.LLM, "generate")
    """
    return _ResumeRunFactory(run_id=run_id)

"""Public `run` callable — decorator + context manager (sync + async)."""

from __future__ import annotations

import functools
import inspect
import logging
from collections.abc import Callable, Sequence
from contextvars import ContextVar, Token
from datetime import datetime
from typing import Any, Literal

from plumb.core.entities import (
    Example,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)
from plumb.core.errors import PlumbError, ValidationError
from plumb.core.ports import Clock, IdGenerator, StorageWriter

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level singletons (DI pattern — tests monkeypatch these)
# ---------------------------------------------------------------------------


class _DefaultClock:
    def now(self) -> datetime:
        import datetime as _dt

        return _dt.datetime.now(tz=_dt.UTC)


class _DefaultIdGenerator:
    def new_run_id(self) -> str:
        import uuid

        return uuid.uuid4().hex

    def new_span_id(self) -> str:
        import uuid

        return uuid.uuid4().hex

    def new_score_id(self) -> str:
        import uuid

        return uuid.uuid4().hex

    def new_example_id(self) -> str:
        import uuid

        return uuid.uuid4().hex


class _NoopStorageWriter:
    """Used before a real writer is configured (e.g. during test isolation)."""

    def write_run(self, run: Run, spans: Sequence[Span]) -> None:
        pass

    def write_score(self, score: Score) -> None:
        pass

    def write_example(self, example: Example) -> None:
        pass


_clock: Clock = _DefaultClock()
_id_gen: IdGenerator = _DefaultIdGenerator()
_storage_writer: StorageWriter = _NoopStorageWriter()

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
        self.scores: list[Score] = []
        self.aborted: bool = False
        self.abort_reason: str | None = None
        self.status: RunStatus | None = None
        self.end_ts: datetime | None = None
        self.error_type: str | None = None

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
    ) -> str:
        """Buffer a span; returns span_id. No-op after abort()."""
        if self._builder.aborted:
            return ""
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
    ) -> str:
        """Buffer a score; returns score_id. No-op after abort()."""
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
            scorer_kind=ScorerKind(scorer) if isinstance(scorer, str) else scorer,
            scorer_version=scorer_version or "unversioned",
            scored_at=_clock.now(),
            span_id=span_id,
            value_numeric=value_numeric,
            value_label=value_label,
        )
        self._builder.scores.append(score)
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

    def abort(self, reason: str) -> None:
        """Mark run as aborted; future add_* calls become no-ops, buffered spans are preserved."""
        if not reason:
            raise ValidationError("abort reason must be non-empty")
        self._builder.aborted = True
        self._builder.abort_reason = reason


# ---------------------------------------------------------------------------
# _RunFactory — returned by run(); implements decorator + context manager
# ---------------------------------------------------------------------------


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
        "_dedupd",
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
        self._dedupd: bool = False
        self._token: Token[RunHandle | None] | None = None
        self._handle: RunHandle | None = None

    # -- context manager (sync) -----------------------------------------------

    def __enter__(self) -> RunHandle:
        self._dedupd = False
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
            self._dedupd = True
            self._handle = parent_handle
            return parent_handle

        builder = _RunBuilder(
            run_id=_id_gen.new_run_id(),
            kind=self.kind,
            task_id=self.task_id,
            parent_run_id=parent_run_id,
            start_ts=_clock.now(),
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
        return handle

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> bool:
        if self._dedupd:
            return False  # outer no-op; never suppresses

        handle = self._handle
        if handle is None:
            return False
        builder = handle._builder

        # determine final status
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
            run_obj = builder.freeze()
            spans = list(builder.spans)
            scores = list(builder.scores)
            _storage_writer.write_run(run_obj, spans)
            for score in scores:
                _storage_writer.write_score(score)
        except PlumbError as plumb_err:
            # NFR-Rel-1: NEVER raise plumb-internal failure into caller
            logger.warning(
                "plumb storage failure",
                extra={
                    "plumb_internal_error": True,
                    "run_id": builder.run_id,
                    "error_class": type(plumb_err).__name__,
                },
            )
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
    ) -> bool:
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

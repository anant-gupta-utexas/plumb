"""Frozen dataclasses and enums for plumb's four-table schema (TRD §7.1)."""

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from plumb.core.errors import ValidationError

_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# ---------------------------------------------------------------------------
# Enums — values match TRD CHECK string literals exactly
# ---------------------------------------------------------------------------


class RunKind(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"


class RunStatus(StrEnum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"
    STALLED = "stalled"


class SpanKind(StrEnum):
    LLM = "llm"
    TOOL = "tool"
    SUBAGENT = "subagent"
    HANDOFF = "handoff"
    PLAN = "plan"
    VERIFY = "verify"


class SpanStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted"


class ScorerKind(StrEnum):
    DETERMINISTIC = "deterministic"
    JUDGE = "judge"
    HUMAN = "human"
    USER_SIGNAL = "user_signal"


class ExampleSource(StrEnum):
    SYNTHETIC = "synthetic"
    PRODUCTION_PROMOTION = "production_promotion"
    HUMAN_AUTHORED = "human_authored"


# ---------------------------------------------------------------------------
# Helper validators
# ---------------------------------------------------------------------------


def _require_hex32(value: str, field: str) -> None:
    if not _HEX32.match(value):
        raise ValidationError(f"{field} must be a 32-char lowercase hex string")


def _require_hex64(value: str, field: str) -> None:
    if not _HEX64.match(value):
        raise ValidationError(f"{field} must be a 64-char lowercase hex string")


def _require_tz(value: datetime, field: str) -> None:
    if value.tzinfo is None:
        raise ValidationError(f"{field} must be a timezone-aware datetime")


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Run:
    """A single instrumented execution (TRD §7.1 runs table)."""

    run_id: str
    task_id: str
    kind: RunKind
    status: RunStatus
    start_ts: datetime
    end_ts: datetime | None = None
    parent_run_id: str | None = None
    orchestrator_model: str | None = None
    sub_agent_model: str | None = None
    prompt_version: str | None = None
    tool_schema_version: str | None = None
    git_sha: str | None = None
    error_type: str | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    dollar_cost: float | None = None

    def __post_init__(self) -> None:
        _require_hex32(self.run_id, "run_id")
        if not self.task_id:
            raise ValidationError("task_id must be non-empty")
        _require_tz(self.start_ts, "start_ts")
        if self.end_ts is not None:
            _require_tz(self.end_ts, "end_ts")
            if self.end_ts < self.start_ts:
                raise ValidationError("end_ts must be >= start_ts")
        if self.parent_run_id is not None:
            _require_hex32(self.parent_run_id, "parent_run_id")


@dataclass(frozen=True, slots=True)
class Span:
    """A single unit of work within a run (TRD §7.1 spans table).

    Token storage contract: the DB schema has a single ``tokens`` column.
    On write, ``tokens_in + tokens_out`` is summed and stored.  On read, the
    sum is surfaced as ``tokens_in``; ``tokens_out`` is always ``None``.
    The in/out split is informational at the entity layer — it is not durable.
    (v2 deferred: split into ``tokens_in`` + ``tokens_out`` columns.)
    """

    span_id: str
    run_id: str
    kind: SpanKind
    name: str
    parent_span_id: str | None = None
    status: SpanStatus | None = None
    input_hash: str | None = None
    output_hash: str | None = None
    latency_ms: float | None = None
    tokens_in: int | None = None
    tokens_out: int | None = None
    error_type: str | None = None
    started_at: datetime | None = None

    def __post_init__(self) -> None:
        _require_hex32(self.span_id, "span_id")
        _require_hex32(self.run_id, "run_id")
        if not self.name:
            raise ValidationError("name must be non-empty")
        if self.parent_span_id is not None:
            _require_hex32(self.parent_span_id, "parent_span_id")
        if self.latency_ms is not None and self.latency_ms < 0:
            raise ValidationError("latency_ms must be >= 0")
        if self.input_hash is not None:
            _require_hex64(self.input_hash, "input_hash")
        if self.output_hash is not None:
            _require_hex64(self.output_hash, "output_hash")


@dataclass(frozen=True, slots=True)
class Score:
    """A metric recorded against a run or span (TRD §7.1 scores table)."""

    score_id: str
    run_id: str
    metric_name: str
    scorer: ScorerKind
    scorer_version: str
    scored_at: datetime
    span_id: str | None = None
    value_numeric: float | None = None
    value_label: str | None = None
    rationale: str | None = None

    def __post_init__(self) -> None:
        _require_hex32(self.score_id, "score_id")
        _require_hex32(self.run_id, "run_id")
        if not self.metric_name:
            raise ValidationError("metric_name must be non-empty")
        if not self.scorer_version:
            raise ValidationError("scorer_version must be non-empty")
        _require_tz(self.scored_at, "scored_at")
        if self.span_id is not None:
            _require_hex32(self.span_id, "span_id")
        # XOR: exactly one of value_numeric / value_label must be set
        numeric_set = self.value_numeric is not None
        label_set = self.value_label is not None
        if numeric_set == label_set:
            raise ValidationError("Exactly one of value_numeric or value_label must be set (XOR)")


@dataclass(frozen=True, slots=True)
class Example:
    """A stored example for offline evaluation (TRD §7.1 examples table)."""

    example_id: str
    task_id: str
    inputs_hash: str
    source: ExampleSource
    created_at: datetime
    expected_output_hash: str | None = None
    active: bool = True
    rubric: str | None = None
    origin_run_id: str | None = None

    def __post_init__(self) -> None:
        _require_hex32(self.example_id, "example_id")
        if not self.task_id:
            raise ValidationError("task_id must be non-empty")
        _require_hex64(self.inputs_hash, "inputs_hash")
        _require_tz(self.created_at, "created_at")
        if self.expected_output_hash is not None:
            _require_hex64(self.expected_output_hash, "expected_output_hash")
        if self.origin_run_id is not None:
            _require_hex32(self.origin_run_id, "origin_run_id")


@dataclass(frozen=True, slots=True)
class JudgeResult:
    """Return value of a JudgeAdapter.score() call."""

    metric_name: str
    scorer_version: str
    rationale: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    value_numeric: float | None = None
    value_label: str | None = None

    def __post_init__(self) -> None:
        numeric_set = self.value_numeric is not None
        label_set = self.value_label is not None
        if numeric_set == label_set:
            raise ValidationError("Exactly one of value_numeric or value_label must be set (XOR)")


@dataclass(frozen=True, slots=True)
class RunSummaryRow:
    """A run row augmented with span and score counts.

    Lightweight projection used by ``plumb run stats`` (CLI) and
    ``GET /runs`` (HTTP service). Pydantic-free; mypy-strict-clean.

    Attributes:
        run_id: 32-char lowercase hex ID.
        task_id: Task identifier string.
        kind: Run kind — ``offline`` or ``online``.
        status: Run status string.
        start_ts: ISO-8601 start timestamp string (as stored in SQLite).
        end_ts: ISO-8601 end timestamp string, or ``None`` if pending.
        orchestrator_model: Model string for the top-level orchestrator.
        sub_agent_model: Model string for sub-agents, if applicable.
        git_sha: Git commit SHA at run time, if captured.
        tokens_in: Total input tokens consumed.
        tokens_out: Total output tokens generated.
        dollar_cost: Estimated dollar cost of the run.
        error_type: Error classification string on failure.
        parent_run_id: 32-char hex ID of the parent run, if nested.
        span_count: Number of spans attached to this run.
        score_count: Number of scores recorded for this run.
    """

    run_id: str
    task_id: str
    kind: str
    status: str
    start_ts: str
    end_ts: str | None
    orchestrator_model: str | None
    sub_agent_model: str | None
    git_sha: str | None
    tokens_in: int | None
    tokens_out: int | None
    dollar_cost: float | None
    error_type: str | None
    parent_run_id: str | None
    span_count: int
    score_count: int


@dataclass(frozen=True, slots=True)
class McNemarResult:
    """Result of a paired McNemar test."""

    b: int
    c: int
    statistic: float
    p_value: float
    n_discordant: int

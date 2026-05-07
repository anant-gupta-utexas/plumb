"""Pydantic v2 response models for the plumb HTTP service (TRD §7.1).

All models use ``extra="forbid"`` to catch accidental field additions in tests.
Datetimes are always timezone-aware; hashes are 64-char hex; IDs are 32-char hex.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class HealthOut(BaseModel):
    """Liveness probe response."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok"]


class ErrorOut(BaseModel):
    """Standard error envelope for non-422 HTTP errors."""

    model_config = ConfigDict(extra="forbid")

    error_type: str
    detail: str


class RunOut(BaseModel):
    """A single run row (TRD §7.1 runs table).

    Attributes:
        run_id: 32-char lowercase hex ID.
        task_id: Task identifier string.
        kind: Run kind — ``offline`` or ``online``.
        status: Run status.
        start_ts: Timezone-aware start timestamp.
        end_ts: Timezone-aware end timestamp, or ``None`` if still pending.
        parent_run_id: 32-char hex ID of the parent run, if nested.
        orchestrator_model: Model string for the top-level orchestrator.
        sub_agent_model: Model string for sub-agents, if applicable.
        git_sha: Git commit SHA at run time, if captured.
        tokens_in: Total input tokens consumed.
        tokens_out: Total output tokens generated.
        dollar_cost: Estimated dollar cost of the run.
        error_type: Error classification string on failure.
        duration_ms: Computed wall-clock duration in milliseconds.
    """

    model_config = ConfigDict(extra="forbid")

    run_id: str
    task_id: str
    kind: Literal["offline", "online"]
    status: Literal["pending", "success", "failure", "aborted", "stalled"]
    start_ts: datetime
    end_ts: datetime | None
    parent_run_id: str | None
    orchestrator_model: str | None
    sub_agent_model: str | None
    git_sha: str | None
    tokens_in: int | None
    tokens_out: int | None
    dollar_cost: float | None
    error_type: str | None
    duration_ms: int | None


class RunSummaryOut(RunOut):
    """A run row with span and score counts (for list endpoints).

    Attributes:
        span_count: Number of spans attached to this run.
        score_count: Number of scores recorded for this run.
    """

    span_count: int
    score_count: int


class SpanOut(BaseModel):
    """A single span row (TRD §7.1 spans table).

    Attributes:
        span_id: 32-char lowercase hex ID.
        run_id: Parent run's 32-char hex ID.
        parent_span_id: Parent span's 32-char hex ID, or ``None`` for root spans.
        kind: Span kind classification.
        name: Human-readable span name.
        input_hash: SHA-256 hex of the input blob (64 chars). Blob not inlined.
        output_hash: SHA-256 hex of the output blob (64 chars). Blob not inlined.
        tokens: Total token count for this span.
        latency_ms: Span wall-clock latency in milliseconds.
        status: Span completion status.
        error_type: Error classification string on failure.
    """

    model_config = ConfigDict(extra="forbid")

    span_id: str
    run_id: str
    parent_span_id: str | None
    kind: Literal["llm", "tool", "subagent", "handoff", "plan", "verify"]
    name: str
    input_hash: str | None
    output_hash: str | None
    tokens: int | None
    latency_ms: int | None
    status: Literal["success", "failure", "aborted"] | None
    error_type: str | None


class ScoreOut(BaseModel):
    """A single score row (TRD §7.1 scores table).

    Attributes:
        score_id: 32-char lowercase hex ID.
        run_id: Parent run's 32-char hex ID.
        span_id: Optional span the score was attached to.
        metric_name: Name of the metric being scored.
        scorer: Scorer kind classification.
        scorer_version: Version string of the scorer.
        value_numeric: Numeric score value (XOR with value_label).
        value_label: Label score value (XOR with value_numeric).
        scored_at: Timezone-aware timestamp when the score was recorded.
    """

    model_config = ConfigDict(extra="forbid")

    score_id: str
    run_id: str
    span_id: str | None
    metric_name: str
    scorer: Literal["deterministic", "judge", "human", "user_signal"]
    scorer_version: str
    value_numeric: float | None
    value_label: str | None
    scored_at: datetime


class ExampleOut(BaseModel):
    """A single example row (TRD §7.1 examples table).

    Attributes:
        example_id: 32-char lowercase hex ID.
        task_id: Task this example belongs to.
        inputs_hash: SHA-256 hex of the input blob (64 chars).
        expected_output_hash: SHA-256 hex of expected output blob, if set.
        rubric: Optional evaluation rubric text.
        source: How this example was created.
        origin_run_id: Run this was promoted from, if applicable.
        active: Whether this example is in the active regression set.
        created_at: Timezone-aware creation timestamp.
    """

    model_config = ConfigDict(extra="forbid")

    example_id: str
    task_id: str
    inputs_hash: str
    expected_output_hash: str | None
    rubric: str | None
    source: Literal["synthetic", "production_promotion", "human_authored"]
    origin_run_id: str | None
    active: bool
    created_at: datetime


class RunListOut(BaseModel):
    """Paginated list of run summaries.

    Attributes:
        items: The page of run summaries.
        total: Total matching runs regardless of offset/limit.
        limit: Page size requested.
        offset: Page offset requested.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[RunSummaryOut]
    total: int
    limit: int
    offset: int


class ExampleListOut(BaseModel):
    """Full list of matching examples (no pagination in v1).

    Attributes:
        items: All matching example rows.
    """

    model_config = ConfigDict(extra="forbid")

    items: list[ExampleOut]


class RunDetailOut(BaseModel):
    """Full run detail with spans and scores.

    Attributes:
        run: The run row.
        spans: Spans ordered root-first, then by parent_span_id, then span_id.
        scores: All scores recorded against this run.
    """

    model_config = ConfigDict(extra="forbid")

    run: RunOut
    spans: list[SpanOut]
    scores: list[ScoreOut]


class MetricStatOut(BaseModel):
    """Aggregated statistics for one metric in the ten-metric v1 cut.

    Attributes:
        metric_name: Name of the metric.
        n: Total number of observations.
        value_mean: Mean of numeric observations, or ``None`` if no numeric values.
        value_p50: 50th-percentile of numeric observations.
        value_p95: 95th-percentile of numeric observations.
        pass_rate: Fraction of label observations that equal ``"pass"``.
        by_scorer: Observation count broken down by scorer kind.
    """

    model_config = ConfigDict(extra="forbid")

    metric_name: str
    n: int
    value_mean: float | None
    value_p50: float | None
    value_p95: float | None
    pass_rate: float | None
    by_scorer: dict[str, int]


class StatsOut(BaseModel):
    """Aggregated task statistics for the v1 ten-metric cut.

    Attributes:
        task_id: The task identifier echoed verbatim.
        since: The ``since`` filter applied, or ``None`` for all time.
        run_count: Total runs matching the window.
        success_rate: Fraction of resolved (non-pending/aborted) runs that succeeded.
        intervention_rate: Fraction of runs with a ``user_signal`` intervention score.
        latency_ms_p50: 50th-percentile end-to-end latency in milliseconds.
        latency_ms_p95: 95th-percentile end-to-end latency in milliseconds.
        dollar_cost_total: Sum of ``dollar_cost`` across all matching runs.
        tokens_in_total: Sum of ``tokens_in`` across all matching runs.
        tokens_out_total: Sum of ``tokens_out`` across all matching runs.
        tokens_per_resolved_task: Average tokens consumed per successful run.
        metrics: Per-metric aggregates for the v1 ten-metric cut.
    """

    model_config = ConfigDict(extra="forbid")

    task_id: str
    since: datetime | None
    run_count: int
    success_rate: float | None
    intervention_rate: float | None
    latency_ms_p50: float | None
    latency_ms_p95: float | None
    dollar_cost_total: float | None
    tokens_in_total: int | None
    tokens_out_total: int | None
    tokens_per_resolved_task: float | None
    metrics: list[MetricStatOut]

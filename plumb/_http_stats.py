"""Pure aggregation functions for the plumb HTTP stats endpoint.

Computes the v1 ten-metric cut from a ``StorageReader`` without I/O side-effects.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import TYPE_CHECKING

from plumb._http_schemas import MetricStatOut, StatsOut
from plumb.core.errors import ValidationError

if TYPE_CHECKING:
    from plumb.adapters.storage_sqlite import ScoreAggregateRow, TaskRunAggregate
    from plumb.core.ports import StorageReader


class NotFoundError(Exception):
    """Raised when the task has zero runs in the requested window."""


def _percentile(values: list[float], p: float) -> float | None:
    """Compute the nearest-rank percentile (matches SQL PERCENTILE_DISC).

    Args:
        values: Sorted or unsorted list of numeric values.
        p: Fraction in [0, 1].

    Returns:
        The nearest-rank percentile value, or ``None`` if ``values`` is empty.
    """
    if not values:
        return None
    sorted_vals = sorted(values)
    idx = max(0, math.ceil(p * len(sorted_vals)) - 1)
    return sorted_vals[idx]


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _build_metric_stat(row: ScoreAggregateRow) -> MetricStatOut:
    n = len(row.value_numeric_list) + len(row.value_label_list)
    v_mean = _mean(row.value_numeric_list)
    v_p50 = _percentile(row.value_numeric_list, 0.50)
    v_p95 = _percentile(row.value_numeric_list, 0.95)

    total_label = len(row.value_label_list)
    pass_count = sum(1 for v in row.value_label_list if v == "pass")
    pass_rate = (pass_count / total_label) if total_label > 0 else None

    return MetricStatOut(
        metric_name=row.metric_name,
        n=n,
        value_mean=v_mean,
        value_p50=v_p50,
        value_p95=v_p95,
        pass_rate=pass_rate,
        by_scorer={row.scorer: n},
    )


def compute_task_stats(
    reader: StorageReader,
    task_id: str,
    since: datetime | None,
) -> StatsOut:
    """Compute the v1 ten-metric cut for a task.

    Performs two reader calls: one for run-level aggregates (counts, costs,
    latency) and one for score-level aggregates grouped by metric+scorer.

    Args:
        reader: A ``StorageReader`` instance for DB access.
        task_id: The task identifier to aggregate over.
        since: Optional lower-bound timestamp filter.

    Returns:
        A ``StatsOut`` with all ten v1 metric fields populated.

    Raises:
        NotFoundError: If the task has zero runs in the requested window.
        ValidationError: If ``task_id`` is empty.
    """
    if not task_id:
        raise ValidationError("task_id must be non-empty")

    agg: TaskRunAggregate = reader.aggregate_runs_for_task(task_id, since=since)  # type: ignore[assignment]
    if agg.run_count == 0:
        since_str = since.isoformat() if since else "all time"
        raise NotFoundError(f"No runs for task '{task_id}' since {since_str}")

    resolved = agg.success_count + agg.failure_count
    success_rate: float | None = agg.success_count / resolved if resolved > 0 else None

    p50 = _percentile(agg.latency_ms_values, 0.50)
    p95 = _percentile(agg.latency_ms_values, 0.95)

    tokens_per_resolved: float | None = (
        agg.successful_tokens_total / agg.success_count
        if agg.success_count > 0 and agg.successful_tokens_total is not None
        else None
    )

    score_rows: list[ScoreAggregateRow] = reader.aggregate_scores_for_task(task_id, since=since)  # type: ignore[assignment]

    intervention_rate: float | None = None
    metrics: list[MetricStatOut] = []

    for row in score_rows:
        if row.metric_name == "intervention" and row.scorer == "user_signal":
            intervened = sum(1 for v in row.value_label_list if v in {"true", "intervened"})
            intervention_rate = intervened / agg.run_count

        metrics.append(_build_metric_stat(row))

    dollar_cost: float | None = (
        float(agg.dollar_cost_total) if agg.dollar_cost_total is not None else None
    )
    tokens_in: int | None = int(agg.tokens_in_total) if agg.tokens_in_total is not None else None
    tokens_out: int | None = int(agg.tokens_out_total) if agg.tokens_out_total is not None else None

    return StatsOut(
        task_id=task_id,
        since=since,
        run_count=agg.run_count,
        success_rate=success_rate,
        intervention_rate=intervention_rate,
        latency_ms_p50=p50,
        latency_ms_p95=p95,
        dollar_cost_total=dollar_cost,
        tokens_in_total=tokens_in,
        tokens_out_total=tokens_out,
        tokens_per_resolved_task=tokens_per_resolved,
        metrics=metrics,
    )

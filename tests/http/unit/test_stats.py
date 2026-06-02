"""Unit tests for plumb/_http_stats.py — pure function, FakeReader-driven."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from plumb._http_stats import NotFoundError, _percentile, compute_task_stats

# ---------------------------------------------------------------------------
# _percentile helper
# ---------------------------------------------------------------------------


def test_percentile_empty() -> None:
    assert _percentile([], 0.5) is None


def test_percentile_single() -> None:
    assert _percentile([42.0], 0.5) == 42.0


def test_percentile_p50() -> None:
    # nearest-rank: ceil(0.5 * 4) - 1 = idx 1 → second element in sorted list
    assert _percentile([10.0, 20.0, 30.0, 40.0], 0.50) == 20.0


def test_percentile_p95_matches_percentile_disc() -> None:
    # 20 values; ceil(0.95 * 20) = 19 → idx 18 → sorted[18]
    vals = list(range(1, 21))
    result = _percentile([float(v) for v in vals], 0.95)
    assert result == 19.0


# ---------------------------------------------------------------------------
# FakeReader
# ---------------------------------------------------------------------------


class _FakeRunAggregate:
    def __init__(
        self,
        run_count: int = 5,
        success_count: int = 3,
        failure_count: int = 2,
        aborted_count: int = 0,
        stalled_count: int = 0,
        latency_ms_values: list[float] | None = None,
        dollar_cost_total: float | None = 1.5,
        tokens_in_total: int | None = 1000,
        tokens_out_total: int | None = 500,
        successful_tokens_total: int | None = 600,
    ) -> None:
        self.task_id = "test.task"
        self.run_count = run_count
        self.success_count = success_count
        self.failure_count = failure_count
        self.aborted_count = aborted_count
        self.stalled_count = stalled_count
        self.latency_ms_values = latency_ms_values or [100.0, 200.0, 500.0]
        self.dollar_cost_total = dollar_cost_total
        self.tokens_in_total = tokens_in_total
        self.tokens_out_total = tokens_out_total
        self.successful_tokens_total = successful_tokens_total


class _FakeScoreRow:
    def __init__(
        self,
        metric_name: str,
        scorer: str,
        value_numeric_list: list[float] | None = None,
        value_label_list: list[str] | None = None,
    ) -> None:
        self.metric_name = metric_name
        self.scorer = scorer
        self.value_numeric_list = value_numeric_list or []
        self.value_label_list = value_label_list or []


class _FakeReader:
    def __init__(
        self,
        agg: _FakeRunAggregate | None = None,
        score_rows: list[_FakeScoreRow] | None = None,
    ) -> None:
        self._agg = agg or _FakeRunAggregate()
        self._score_rows = score_rows or []

    def aggregate_runs_for_task(self, task_id: str, *, since=None):  # type: ignore[override]
        return self._agg

    def aggregate_scores_for_task(self, task_id: str, *, since=None):  # type: ignore[override]
        return self._score_rows


# ---------------------------------------------------------------------------
# compute_task_stats — happy paths
# ---------------------------------------------------------------------------


def test_basic_stats() -> None:
    reader = _FakeReader()
    result = compute_task_stats(reader, "test.task", None)

    assert result.task_id == "test.task"
    assert result.run_count == 5
    assert result.success_rate == pytest.approx(3 / 5)
    assert result.since is None
    assert result.dollar_cost_total == pytest.approx(1.5)
    assert result.tokens_in_total == 1000
    assert result.tokens_out_total == 500
    # tokens_per_resolved_task = successful_tokens_total / success_count = 600 / 3 = 200
    assert result.tokens_per_resolved_task == pytest.approx(200.0)


def test_latency_percentiles() -> None:
    agg = _FakeRunAggregate(latency_ms_values=[100.0, 200.0, 300.0, 400.0, 500.0])
    reader = _FakeReader(agg=agg)
    result = compute_task_stats(reader, "test.task", None)

    assert result.latency_ms_p50 is not None
    assert result.latency_ms_p95 is not None


def test_success_rate_excludes_pending_and_aborted() -> None:
    # Only success + failure go into denominator.
    agg = _FakeRunAggregate(
        run_count=10,
        success_count=4,
        failure_count=4,
        aborted_count=2,
    )
    reader = _FakeReader(agg=agg)
    result = compute_task_stats(reader, "test.task", None)
    # 4 / (4 + 4) = 0.5
    assert result.success_rate == pytest.approx(0.5)


def test_success_rate_none_when_no_resolved() -> None:
    agg = _FakeRunAggregate(
        run_count=3,
        success_count=0,
        failure_count=0,
        aborted_count=3,
        successful_tokens_total=None,
    )
    reader = _FakeReader(agg=agg)
    result = compute_task_stats(reader, "test.task", None)
    assert result.success_rate is None


def test_tokens_per_resolved_none_when_no_success() -> None:
    agg = _FakeRunAggregate(success_count=0, successful_tokens_total=None)
    reader = _FakeReader(agg=agg)
    result = compute_task_stats(reader, "test.task", None)
    assert result.tokens_per_resolved_task is None


def test_intervention_rate_computed() -> None:
    score_rows = [
        _FakeScoreRow(
            "intervention",
            "user_signal",
            value_label_list=["intervened", "true", "false"],
        )
    ]
    reader = _FakeReader(score_rows=score_rows)
    result = compute_task_stats(reader, "test.task", None)
    # 2 intervened out of 5 runs
    assert result.intervention_rate == pytest.approx(2 / 5)


def test_intervention_rate_none_when_no_user_signal() -> None:
    reader = _FakeReader(score_rows=[])
    result = compute_task_stats(reader, "test.task", None)
    assert result.intervention_rate is None


def test_metrics_list_populated() -> None:
    score_rows = [
        _FakeScoreRow("quality", "judge", value_numeric_list=[0.8, 0.9, 1.0]),
        _FakeScoreRow("routing_top1", "deterministic", value_label_list=["pass", "fail"]),
    ]
    reader = _FakeReader(score_rows=score_rows)
    result = compute_task_stats(reader, "test.task", None)

    assert len(result.metrics) == 2
    quality = next(m for m in result.metrics if m.metric_name == "quality")
    assert quality.n == 3
    assert quality.value_mean == pytest.approx(0.9)
    assert quality.pass_rate is None  # no labels

    routing = next(m for m in result.metrics if m.metric_name == "routing_top1")
    assert routing.n == 2
    assert routing.pass_rate == pytest.approx(0.5)


def test_since_passed_through() -> None:
    since = datetime(2026, 1, 1, tzinfo=UTC)
    reader = _FakeReader()
    result = compute_task_stats(reader, "test.task", since)
    assert result.since == since


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_raises_not_found_when_zero_runs() -> None:
    agg = _FakeRunAggregate(run_count=0, success_count=0, failure_count=0)
    reader = _FakeReader(agg=agg)
    with pytest.raises(NotFoundError, match="No runs for task"):
        compute_task_stats(reader, "test.task", None)

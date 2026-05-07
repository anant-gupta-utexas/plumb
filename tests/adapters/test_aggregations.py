"""Tests for aggregate_runs_for_task and aggregate_scores_for_task (T3.1)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter, TaskRunAggregate
from plumb.core.entities import Run, RunKind, RunStatus, Score, ScorerKind


class _FakeClock:
    def now(self) -> datetime:
        return datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def adapter(tmp_path: Path) -> SQLiteStorageAdapter:
    a = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_FakeClock())
    yield a
    a.close()


def _run(
    run_id: str,
    task_id: str = "task.a",
    status: RunStatus = RunStatus.SUCCESS,
    start_offset_days: int = 0,
    tokens_in: int | None = 100,
    tokens_out: int | None = 50,
    dollar_cost: float | None = 0.01,
) -> Run:
    start = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC) + timedelta(days=start_offset_days)
    end = start + timedelta(seconds=30)
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.OFFLINE,
        status=status,
        start_ts=start,
        end_ts=end if status != RunStatus.PENDING else None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        dollar_cost=dollar_cost,
    )


def _score(
    score_id: str,
    run_id: str,
    metric_name: str = "quality",
    scorer: ScorerKind = ScorerKind.JUDGE,
    value_numeric: float | None = 0.9,
    value_label: str | None = None,
) -> Score:
    return Score(
        score_id=score_id,
        run_id=run_id,
        metric_name=metric_name,
        scorer=scorer,
        scorer_version="v1",
        scored_at=datetime(2026, 1, 1, 12, 0, 5, tzinfo=UTC),
        value_numeric=value_numeric,
        value_label=value_label,
    )


class TestAggregateRunsForTask:
    def test_empty_task_returns_zero_counts(self, adapter: SQLiteStorageAdapter) -> None:
        result = adapter.aggregate_runs_for_task("nonexistent")
        assert result.run_count == 0
        assert result.success_count == 0
        assert result.latency_ms_values == []
        assert result.dollar_cost_total is None

    def test_counts_by_status(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, status=RunStatus.SUCCESS), [])
        adapter.write_run(_run("b" * 32, status=RunStatus.FAILURE), [])
        adapter.write_run(_run("c" * 32, status=RunStatus.ABORTED), [])

        result = adapter.aggregate_runs_for_task("task.a")
        assert result.run_count == 3
        assert result.success_count == 1
        assert result.failure_count == 1
        assert result.aborted_count == 1

    def test_only_counts_matching_task(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, task_id="task.a"), [])
        adapter.write_run(_run("b" * 32, task_id="task.b"), [])

        result = adapter.aggregate_runs_for_task("task.a")
        assert result.run_count == 1

    def test_since_filter(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, start_offset_days=0), [])
        adapter.write_run(_run("b" * 32, start_offset_days=5), [])

        cutoff = datetime(2026, 1, 4, tzinfo=UTC)
        result = adapter.aggregate_runs_for_task("task.a", since=cutoff)
        assert result.run_count == 1

    def test_latency_values_populated(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32), [])
        result = adapter.aggregate_runs_for_task("task.a")
        assert len(result.latency_ms_values) == 1
        # 30 second run → 30000 ms
        assert abs(result.latency_ms_values[0] - 30000) < 10

    def test_cost_and_token_sums(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, tokens_in=100, tokens_out=50, dollar_cost=0.01), [])
        adapter.write_run(_run("b" * 32, tokens_in=200, tokens_out=100, dollar_cost=0.02), [])

        result = adapter.aggregate_runs_for_task("task.a")
        assert result.tokens_in_total == 300
        assert result.tokens_out_total == 150
        assert abs(result.dollar_cost_total - 0.03) < 1e-9

    def test_successful_tokens_only_success_status(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, status=RunStatus.SUCCESS, tokens_in=100, tokens_out=50), [])
        adapter.write_run(_run("b" * 32, status=RunStatus.FAILURE, tokens_in=200, tokens_out=100), [])

        result = adapter.aggregate_runs_for_task("task.a")
        # Only the success run: 100 + 50 = 150
        assert result.successful_tokens_total == 150

    def test_returns_taskrunaggregate_instance(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32), [])
        result = adapter.aggregate_runs_for_task("task.a")
        assert isinstance(result, TaskRunAggregate)


class TestAggregateScoresForTask:
    def test_empty_returns_empty_list(self, adapter: SQLiteStorageAdapter) -> None:
        result = adapter.aggregate_scores_for_task("nonexistent")
        assert result == []

    def test_groups_by_metric_and_scorer(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32), [])
        adapter.write_score(_score("0" * 31 + "1", "a" * 32, metric_name="quality", scorer=ScorerKind.JUDGE, value_numeric=0.8))
        adapter.write_score(_score("0" * 31 + "2", "a" * 32, metric_name="quality", scorer=ScorerKind.JUDGE, value_numeric=0.9))
        adapter.write_score(_score("0" * 31 + "3", "a" * 32, metric_name="routing", scorer=ScorerKind.DETERMINISTIC, value_numeric=1.0))

        result = adapter.aggregate_scores_for_task("task.a")
        assert len(result) == 2

        quality = next(r for r in result if r.metric_name == "quality")
        assert len(quality.value_numeric_list) == 2
        assert sorted(quality.value_numeric_list) == [0.8, 0.9]

    def test_only_scores_for_matching_task(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, task_id="task.a"), [])
        adapter.write_run(_run("b" * 32, task_id="task.b"), [])
        adapter.write_score(_score("0" * 31 + "1", "a" * 32, value_numeric=0.8))
        adapter.write_score(_score("0" * 31 + "2", "b" * 32, value_numeric=0.5))

        result = adapter.aggregate_scores_for_task("task.a")
        assert len(result) == 1
        assert result[0].value_numeric_list == [0.8]

    def test_since_filter_excludes_old_runs(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32, start_offset_days=0), [])
        adapter.write_run(_run("b" * 32, start_offset_days=5), [])
        adapter.write_score(_score("0" * 31 + "1", "a" * 32, value_numeric=0.8))
        adapter.write_score(_score("0" * 31 + "2", "b" * 32, value_numeric=0.9))

        cutoff = datetime(2026, 1, 4, tzinfo=UTC)
        result = adapter.aggregate_scores_for_task("task.a", since=cutoff)
        assert len(result) == 1
        assert result[0].value_numeric_list == [0.9]

    def test_label_scores_collected(self, adapter: SQLiteStorageAdapter) -> None:
        adapter.write_run(_run("a" * 32), [])
        adapter.write_score(
            _score("0" * 31 + "1", "a" * 32, metric_name="routing_top1",
                   scorer=ScorerKind.DETERMINISTIC, value_numeric=None, value_label="pass")
        )
        adapter.write_score(
            _score("0" * 31 + "2", "a" * 32, metric_name="routing_top1",
                   scorer=ScorerKind.DETERMINISTIC, value_numeric=None, value_label="fail")
        )

        result = adapter.aggregate_scores_for_task("task.a")
        routing = next(r for r in result if r.metric_name == "routing_top1")
        assert sorted(routing.value_label_list) == ["fail", "pass"]
        assert routing.value_numeric_list == []

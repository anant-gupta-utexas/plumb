"""Tests for plumb run stats (T1.4) — unit + integration."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from plumb.cli import app
from tests.cli.conftest import make_run, make_score, make_span

runner = CliRunner()


def _invoke(db: Path, *args: str):
    """Invoke CLI with PLUMB_DATA_DIR pointing at a tmp db directory."""
    return runner.invoke(app, ["run", "stats", *args], env={"PLUMB_DATA_DIR": str(db.parent)})


# ---------------------------------------------------------------------------
# Unit: list_runs_with_counts
# ---------------------------------------------------------------------------


def test_list_runs_with_counts_empty(storage) -> None:
    assert storage.list_runs_with_counts() == []


def test_list_runs_with_counts_span_and_score(storage) -> None:
    run = make_run(1)
    storage.write_run(run, [make_span(1, run.run_id)])
    storage.write_score(make_score(1, run.run_id))

    summaries = storage.list_runs_with_counts()
    assert len(summaries) == 1
    assert summaries[0].span_count == 1
    assert summaries[0].score_count == 1


def test_list_runs_with_counts_since_filter(storage) -> None:
    from datetime import UTC, datetime, timedelta

    old_run = make_run(1, start_offset_days=10)
    new_run = make_run(2, start_offset_days=0)
    storage.write_run(old_run, [])
    storage.write_run(new_run, [])

    since = datetime.now(UTC) - timedelta(days=5)
    summaries = storage.list_runs_with_counts(since=since)
    ids = {s.run_id for s in summaries}
    assert new_run.run_id in ids
    assert old_run.run_id not in ids


def test_list_runs_with_counts_task_id_filter(storage) -> None:
    run_a = make_run(1, task_id="task-a")
    run_b = make_run(2, task_id="task-b")
    storage.write_run(run_a, [])
    storage.write_run(run_b, [])

    summaries = storage.list_runs_with_counts(task_id="task-a")
    assert len(summaries) == 1
    assert summaries[0].task_id == "task-a"


def test_list_runs_with_counts_limit(storage) -> None:
    for i in range(1, 6):
        storage.write_run(make_run(i), [])
    summaries = storage.list_runs_with_counts(limit=3)
    assert len(summaries) == 3


# ---------------------------------------------------------------------------
# Integration: plumb run stats via CliRunner
# ---------------------------------------------------------------------------


def test_run_stats_empty_db(db_path) -> None:
    result = _invoke(db_path)
    assert result.exit_code == 0


def test_run_stats_lists_runs(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [make_span(1, run.run_id)])
    storage.close()

    result = _invoke(db_path, "--format", "json")
    assert result.exit_code == 0
    lines = [ln for ln in result.output.strip().splitlines() if ln]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["run_id"] == run.run_id[:8]
    assert obj["span_count"] == 1


def test_run_stats_score_count(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.write_score(make_score(1, run.run_id))
    storage.close()

    result = _invoke(db_path, "--format", "json")
    assert result.exit_code == 0
    obj = json.loads(result.output.strip().splitlines()[0])
    assert obj["score_count"] == 1


def test_run_stats_since_filter(storage, db_path) -> None:
    old_run = make_run(1, start_offset_days=10)
    new_run = make_run(2, start_offset_days=0)
    storage.write_run(old_run, [])
    storage.write_run(new_run, [])
    storage.close()

    result = _invoke(db_path, "--since", "5d", "--format", "json")
    assert result.exit_code == 0
    ids = [json.loads(ln)["run_id"] for ln in result.output.strip().splitlines() if ln]
    assert new_run.run_id[:8] in ids
    assert old_run.run_id[:8] not in ids


def test_run_stats_task_id_filter(storage, db_path) -> None:
    run_a = make_run(1, task_id="task-a")
    run_b = make_run(2, task_id="task-b")
    storage.write_run(run_a, [])
    storage.write_run(run_b, [])
    storage.close()

    result = _invoke(db_path, "--task-id", "task-a", "--format", "json")
    assert result.exit_code == 0
    lines = [ln for ln in result.output.strip().splitlines() if ln]
    assert len(lines) == 1
    assert json.loads(lines[0])["task_id"] == "task-a"


def test_run_stats_format_csv(storage, db_path) -> None:
    storage.write_run(make_run(1), [])
    storage.close()

    result = _invoke(db_path, "--format", "csv")
    assert result.exit_code == 0
    lines = result.output.strip().splitlines()
    assert lines[0].startswith("run_id")


def test_run_stats_limit(storage, db_path) -> None:
    for i in range(1, 6):
        storage.write_run(make_run(i), [])
    storage.close()

    result = _invoke(db_path, "--limit", "3", "--format", "json")
    assert result.exit_code == 0
    lines = [ln for ln in result.output.strip().splitlines() if ln]
    assert len(lines) == 3


def test_run_stats_invalid_since(db_path) -> None:
    result = _invoke(db_path, "--since", "foo")
    assert result.exit_code == 1
    assert "Invalid --since" in result.output


def test_run_stats_invalid_format(db_path) -> None:
    result = _invoke(db_path, "--format", "xml")
    assert result.exit_code == 1
    assert "table, json, or csv" in result.output

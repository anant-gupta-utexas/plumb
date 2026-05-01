"""Tests for plumb score write (T2.1) — unit + integration."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from plumb.cli import app
from tests.cli.conftest import make_run

runner = CliRunner()


def _invoke(db: Path, *args: str):
    return runner.invoke(
        app,
        ["score", "write", *args],
        env={"PLUMB_DATA_DIR": str(db.parent)},
    )


def test_score_write_numeric(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "quality",
        "--scorer",
        "human",
        "--value-numeric",
        "0.9",
    )
    assert result.exit_code == 0, result.output

    # Verify score was written
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores = st.get_scores_for_run(run.run_id)
    assert len(scores) == 1
    assert scores[0].value_numeric == pytest.approx(0.9)


def test_score_write_label(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "quality",
        "--scorer",
        "human",
        "--value-label",
        "pass",
    )
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores = st.get_scores_for_run(run.run_id)
    assert scores[0].value_label == "pass"


def test_score_write_both_flags_exit_1(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "q",
        "--scorer",
        "human",
        "--value-numeric",
        "1.0",
        "--value-label",
        "pass",
    )
    assert result.exit_code == 1
    combined = result.output  # stderr merged into output (Click 8.2+)
    assert "Exactly one" in combined


def test_score_write_neither_flag_exit_1(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "q",
        "--scorer",
        "human",
    )
    assert result.exit_code == 1
    combined = result.output  # stderr merged into output (Click 8.2+)
    assert "Exactly one" in combined


def test_score_write_unknown_run_exit_1(db_path) -> None:
    result = _invoke(
        db_path,
        "--run-id",
        "a" * 32,
        "--metric",
        "q",
        "--scorer",
        "human",
        "--value-numeric",
        "1.0",
    )
    assert result.exit_code == 1
    combined = result.output  # stderr merged into output (Click 8.2+)
    assert "not found" in combined


def test_score_write_invalid_scorer_exit_1(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "q",
        "--scorer",
        "xyz",
        "--value-numeric",
        "1.0",
    )
    assert result.exit_code == 1
    combined = result.output  # stderr merged into output (Click 8.2+)
    assert "Invalid --scorer" in combined


def test_score_write_omitted_scorer_version_defaults(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "q",
        "--scorer",
        "human",
        "--value-numeric",
        "1.0",
    )
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores = st.get_scores_for_run(run.run_id)
    assert scores[0].scorer_version == "cli-unversioned"


def test_score_write_with_span_id(storage, db_path) -> None:
    from tests.cli.conftest import make_span

    run = make_run(1)
    span = make_span(1, run.run_id)
    storage.write_run(run, [span])
    storage.close()

    result = _invoke(
        db_path,
        "--run-id",
        run.run_id,
        "--metric",
        "q",
        "--scorer",
        "human",
        "--value-numeric",
        "1.0",
        "--span-id",
        span.span_id,
    )
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores = st.get_scores_for_run(run.run_id)
    assert scores[0].span_id == span.span_id

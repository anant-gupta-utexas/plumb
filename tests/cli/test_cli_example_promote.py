"""Tests for plumb example promote (T2.2) — unit + integration."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from plumb.cli import app
from tests.cli.conftest import make_run, make_span

runner = CliRunner()


def _invoke(db: Path, *args: str):
    return runner.invoke(
        app,
        ["example", "promote", *args],
        env={"PLUMB_DATA_DIR": str(db.parent)},
    )


def test_example_promote_success(storage, db_path) -> None:
    run = make_run(1)
    span = make_span(1, run.run_id, tokens_in=100)
    storage.write_run(run, [span])
    storage.close()

    result = _invoke(db_path, "--from-run", run.run_id)
    assert result.exit_code == 0, result.output
    assert "Promoted run" in result.output
    assert run.run_id[:8] in result.output


def test_example_promote_not_found_exit_1(db_path) -> None:
    result = _invoke(db_path, "--from-run", "b" * 32)
    assert result.exit_code == 1
    assert "not found" in result.output


def test_example_promote_zero_span_run(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    result = _invoke(db_path, "--from-run", run.run_id)
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert len(examples) == 1
    # "no_spans" sentinel encoded as sha256 of b"no_spans"
    import hashlib

    expected = hashlib.sha256(b"no_spans").hexdigest()
    assert examples[0].inputs_hash == expected


def test_example_promote_uses_highest_token_llm_span(storage, db_path) -> None:

    run = make_run(1)
    span_low = make_span(1, run.run_id, tokens_in=50)
    span_high = make_span(2, run.run_id, tokens_in=200)
    storage.write_run(run, [span_low, span_high])
    storage.close()

    result = _invoke(db_path, "--from-run", run.run_id)
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert examples[0].inputs_hash == span_high.input_hash


def test_example_promote_with_rubric(storage, db_path, tmp_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    rubric_file = tmp_path / "rubric.md"
    rubric_file.write_text("# Score 1 if correct.", encoding="utf-8")

    result = _invoke(db_path, "--from-run", run.run_id, "--rubric", str(rubric_file))
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert examples[0].rubric == "# Score 1 if correct."


def test_example_promote_active_true(storage, db_path) -> None:
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    _invoke(db_path, "--from-run", run.run_id)

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert examples[0].active is True


def test_example_promote_source_production_promotion(storage, db_path) -> None:
    from plumb.core.entities import ExampleSource

    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    _invoke(db_path, "--from-run", run.run_id)

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert examples[0].source == ExampleSource.PRODUCTION_PROMOTION


def test_example_promote_non_llm_span_fallback(storage, db_path) -> None:
    from plumb.core.entities import SpanKind

    run = make_run(1)
    tool_span = make_span(1, run.run_id, kind=SpanKind.TOOL, tokens_in=10)
    storage.write_run(run, [tool_span])
    storage.close()

    result = _invoke(db_path, "--from-run", run.run_id)
    assert result.exit_code == 0

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        examples = st.list_examples()
    assert examples[0].inputs_hash == tool_span.input_hash

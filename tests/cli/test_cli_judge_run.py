"""Tests for plumb judge run (T3.1) — integration with FakeJudgeAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from plumb.cli import app
from tests.cli.conftest import make_run, make_score, make_span
from tests.helpers.fake_judge import FakeJudgeAdapter

runner = CliRunner()


def _invoke(db: Path, *args: str, env: dict | None = None):
    base_env = {"PLUMB_DATA_DIR": str(db.parent), "PLUMB_JUDGE_PROVIDER": "fake"}
    if env:
        base_env.update(env)
    return runner.invoke(app, ["judge", "run", *args], env=base_env)


def _patch_adapter(fake: FakeJudgeAdapter):
    return patch("plumb._cli_judge._load_judge_adapter", return_value=fake)


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------


def test_judge_run_dry_run_prints_count(storage, db_path) -> None:
    """--dry-run prints count and exits 0; no score rows written."""
    for i in range(3):
        storage.write_run(make_run(i + 1), [])
    storage.close()

    fake = FakeJudgeAdapter()
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality", "--dry-run")

    assert result.exit_code == 0, result.output
    assert "Would judge 3 run(s)" in result.output
    assert "quality" in result.output
    assert len(fake.calls) == 0


def test_judge_run_dry_run_zero_writes(storage, db_path) -> None:
    """--dry-run with 0 un-scored runs still exits 0 and writes nothing."""
    storage.close()

    fake = FakeJudgeAdapter()
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality", "--dry-run")

    assert result.exit_code == 0
    assert "Would judge 0 run(s)" in result.output
    assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# score rows written
# ---------------------------------------------------------------------------


def test_judge_run_writes_score_rows(storage, db_path) -> None:
    """Non-dry-run: one score row written per un-scored run."""
    for i in range(3):
        storage.write_run(make_run(i + 1), [])
    storage.close()

    fake = FakeJudgeAdapter(value_label="pass")
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality")

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 3

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        for i in range(1, 4):
            run = make_run(i)
            scores = st.get_scores_for_run(run.run_id)
            assert len(scores) == 1
            assert scores[0].value_label == "pass"
            assert scores[0].metric_name == "quality"


# ---------------------------------------------------------------------------
# already-scored runs skipped
# ---------------------------------------------------------------------------


def test_judge_run_skips_already_scored(storage, db_path) -> None:
    """Runs that already have a score for the metric are not re-judged."""
    run1 = make_run(1)
    run2 = make_run(2)
    storage.write_run(run1, [])
    storage.write_run(run2, [])
    # Pre-score run1 for "quality"
    storage.write_score(make_score(1, run1.run_id, metric="quality"))
    storage.close()

    fake = FakeJudgeAdapter(value_label="pass")
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality")

    assert result.exit_code == 0, result.output
    # Only run2 should be judged
    assert len(fake.calls) == 1

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores_run1 = st.get_scores_for_run(run1.run_id)
        scores_run2 = st.get_scores_for_run(run2.run_id)
    # run1 still has only its original score
    assert len(scores_run1) == 1
    assert scores_run1[0].scorer.value == "human"
    # run2 got a new judge score
    assert len(scores_run2) == 1
    assert scores_run2[0].value_label == "pass"


# ---------------------------------------------------------------------------
# adapter not configured
# ---------------------------------------------------------------------------


def test_judge_run_no_provider_exits_1(storage, db_path) -> None:
    """PLUMB_JUDGE_PROVIDER unset → exit 1 with env var name in message."""
    storage.close()

    result = runner.invoke(
        app,
        ["judge", "run", "--model", "gpt-4o", "--metric", "quality"],
        env={"PLUMB_DATA_DIR": str(db_path.parent), "PLUMB_JUDGE_PROVIDER": ""},
    )

    assert result.exit_code == 1
    assert "PLUMB_JUDGE_PROVIDER" in result.output


# ---------------------------------------------------------------------------
# --model API-key guard
# ---------------------------------------------------------------------------


def test_judge_run_model_looks_like_api_key_exits_1(storage, db_path) -> None:
    """--model sk-abc123 → exit 1 with 'looks like an API key' message."""
    storage.close()

    result = _invoke(db_path, "--model", "sk-abc123", "--metric", "quality")
    assert result.exit_code == 1
    assert "looks like an API key" in result.output


def test_judge_run_anthropic_key_pattern_exits_1(storage, db_path) -> None:
    """--model anthropic_key_xyz → exit 1."""
    storage.close()

    result = _invoke(db_path, "--model", "anthropic_key_xyz", "--metric", "quality")
    assert result.exit_code == 1
    assert "looks like an API key" in result.output


# ---------------------------------------------------------------------------
# filter flags
# ---------------------------------------------------------------------------


def test_judge_run_since_filter(storage, db_path) -> None:
    """--since filters out old runs."""
    old_run = make_run(1, start_offset_days=30)
    new_run = make_run(2, start_offset_days=0)
    storage.write_run(old_run, [])
    storage.write_run(new_run, [])
    storage.close()

    fake = FakeJudgeAdapter(value_label="pass")
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality", "--since", "7d")

    assert result.exit_code == 0, result.output
    # Only the recent run should be judged
    assert len(fake.calls) == 1


def test_judge_run_task_id_filter(storage, db_path) -> None:
    """--task-id filters to only matching runs."""
    run_a = make_run(1, task_id="task-a")
    run_b = make_run(2, task_id="task-b")
    storage.write_run(run_a, [])
    storage.write_run(run_b, [])
    storage.close()

    fake = FakeJudgeAdapter(value_label="pass")
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality", "--task-id", "task-a")

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# judge failure → error score row; command still exits 0
# ---------------------------------------------------------------------------


def test_judge_run_failure_writes_error_score(storage, db_path) -> None:
    """Judge adapter failure → value_label='error' score row; exit 0."""
    run = make_run(1)
    storage.write_run(run, [])
    storage.close()

    class _RaisingAdapter(FakeJudgeAdapter):
        def score(self, **kwargs):
            raise RuntimeError("LLM unavailable")

    with _patch_adapter(_RaisingAdapter()):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality")

    assert result.exit_code == 0, result.output

    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from tests.cli.conftest import _Clock

    with SQLiteStorageAdapter(db_path, clock=_Clock()) as st:
        scores = st.get_scores_for_run(run.run_id)
    assert len(scores) == 1
    assert scores[0].value_label == "error"
    assert scores[0].scorer_version == "error"


# ---------------------------------------------------------------------------
# nothing to judge
# ---------------------------------------------------------------------------


def test_judge_run_nothing_to_judge(storage, db_path) -> None:
    """Empty DB → 'Nothing to judge' message; exit 0."""
    storage.close()

    fake = FakeJudgeAdapter()
    with _patch_adapter(fake):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality")

    assert result.exit_code == 0, result.output
    assert "Nothing to judge" in result.output
    assert len(fake.calls) == 0


# ---------------------------------------------------------------------------
# span present — content loaded from span's input_hash
# ---------------------------------------------------------------------------


def test_judge_run_passes_content_from_span(storage, db_path) -> None:
    """When a span has input_hash, _load_run_content is invoked (content may be empty in test)."""
    run = make_run(1)
    span = make_span(1, run.run_id, tokens_in=100)
    storage.write_run(run, [span])
    storage.close()

    fake = FakeJudgeAdapter(value_label="pass")
    return_value = "test content"
    with (
        _patch_adapter(fake),
        patch("plumb._cli_judge._load_run_content", return_value=return_value),
    ):
        result = _invoke(db_path, "--model", "gpt-4o", "--metric", "quality")

    assert result.exit_code == 0, result.output
    assert len(fake.calls) == 1
    assert fake.calls[0]["content"] == "test content"

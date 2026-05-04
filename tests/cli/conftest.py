"""Shared fixtures for CLI tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import (
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)


class _Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


def _hex32(n: int) -> str:
    # Use the last 8 digits as a suffix so the first-8-char prefix is unique per n.
    # format(1,"032x") = "0...001"; we want distinct prefixes, so place n at the front.
    return f"{n:08x}" + "0" * 24


def _hex64(n: int) -> str:
    return format(n, "064x")


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear the lru_cache on get_settings before each test so PLUMB_DATA_DIR env takes effect."""
    from plumb.config import get_settings

    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    # Must match cli._get_storage: data_dir / "plumb.db"
    # Tests pass PLUMB_DATA_DIR=str(db_path.parent), so cli opens db_path.parent/plumb.db.
    return tmp_path / "plumb.db"


@pytest.fixture
def storage(db_path: Path) -> SQLiteStorageAdapter:
    adapter = SQLiteStorageAdapter(db_path, clock=_Clock())
    yield adapter
    adapter.close()


def make_run(
    n: int = 1,
    task_id: str = "my-task",
    kind: RunKind = RunKind.ONLINE,
    status: RunStatus = RunStatus.SUCCESS,
    start_offset_days: int = 0,
) -> Run:
    """Create a deterministic Run for testing.

    start_offset_days is subtracted from *now* so that ``start_offset_days=0``
    always means "today" and since-filters remain correct regardless of the
    calendar date on which the tests run.
    """
    start = datetime.now(UTC) - timedelta(days=start_offset_days)
    return Run(
        run_id=_hex32(n),
        task_id=task_id,
        kind=kind,
        status=status,
        start_ts=start,
        end_ts=start + timedelta(seconds=10),
    )


def make_span(
    n: int,
    run_id: str,
    kind: SpanKind = SpanKind.LLM,
    tokens_in: int | None = None,
    input_hash: str | None = None,
    output_hash: str | None = None,
) -> Span:
    return Span(
        span_id=_hex32(n + 1000),
        run_id=run_id,
        kind=kind,
        name="test-span",
        status=SpanStatus.SUCCESS,
        tokens_in=tokens_in,
        input_hash=input_hash if input_hash is not None else _hex64(n),
        output_hash=output_hash,
    )


def make_score(n: int, run_id: str, metric: str = "quality", value_numeric: float = 1.0) -> Score:
    return Score(
        score_id=_hex32(n + 2000),
        run_id=run_id,
        metric_name=metric,
        scorer=ScorerKind.HUMAN,
        scorer_version="v1",
        scored_at=datetime.now(UTC),
        value_numeric=value_numeric,
    )

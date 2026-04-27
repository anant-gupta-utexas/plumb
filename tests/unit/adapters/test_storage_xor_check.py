"""Tests for XOR CHECK enforcement at the SQL boundary (Task 3.3)."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.adapters._schema import DDL_STATEMENTS
from plumb.adapters._pragmas import apply_pragmas
from plumb.core.errors import StorageError


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


class _FixedClock:
    def now(self) -> datetime:
        return _NOW


def _raw_conn(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    apply_pragmas(conn)
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        """INSERT INTO runs (run_id, kind, task_id, start_ts, status)
           VALUES ('a' * 32, 'online', 'task1', '2026-01-01T12:00:00+00:00', 'success')""".replace(
            "'a' * 32", f"'{'a' * 32}'"
        )
    )
    return conn


def test_sql_xor_check_rejects_both_values(tmp_path: Path) -> None:
    conn = _raw_conn(tmp_path / "raw.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO scores (
                score_id, run_id, metric_name, scorer, scorer_version,
                value_numeric, value_label, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("c" * 32, "a" * 32, "acc", "deterministic", "v1", 0.9, "bad", "2026-01-01T12:00:00+00:00"),
        )
    conn.close()


def test_sql_xor_check_rejects_neither_value(tmp_path: Path) -> None:
    conn = _raw_conn(tmp_path / "raw.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            """INSERT INTO scores (
                score_id, run_id, metric_name, scorer, scorer_version,
                value_numeric, value_label, scored_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            ("c" * 32, "a" * 32, "acc", "deterministic", "v1", None, None, "2026-01-01T12:00:00+00:00"),
        )
    conn.close()


def test_sql_xor_check_accepts_numeric_only(tmp_path: Path) -> None:
    conn = _raw_conn(tmp_path / "raw.db")
    conn.execute(
        """INSERT INTO scores (
            score_id, run_id, metric_name, scorer, scorer_version,
            value_numeric, value_label, scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("c" * 32, "a" * 32, "acc", "deterministic", "v1", 0.9, None, "2026-01-01T12:00:00+00:00"),
    )
    count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    assert count == 1
    conn.close()


def test_sql_xor_check_accepts_label_only(tmp_path: Path) -> None:
    conn = _raw_conn(tmp_path / "raw.db")
    conn.execute(
        """INSERT INTO scores (
            score_id, run_id, metric_name, scorer, scorer_version,
            value_numeric, value_label, scored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        ("c" * 32, "a" * 32, "acc", "deterministic", "v1", None, "good", "2026-01-01T12:00:00+00:00"),
    )
    count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    assert count == 1
    conn.close()


def test_write_score_fk_violation_raises_storage_error(tmp_path: Path) -> None:
    """Score with nonexistent run_id raises StorageError (FK enforcement)."""
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_FixedClock()) as adapter:
        from plumb.core.entities import Score, ScorerKind
        score = Score(
            score_id="c" * 32,
            run_id="b" * 32,  # nonexistent
            metric_name="acc",
            scorer=ScorerKind.DETERMINISTIC,
            scorer_version="v1",
            scored_at=_NOW,
            value_numeric=0.9,
        )
        with pytest.raises(StorageError):
            adapter.write_score(score)

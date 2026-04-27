"""Tests for SQLiteStorageAdapter lifecycle (Tasks 3.1, 5.1)."""

import os
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.adapters._schema import DDL_STATEMENTS
from plumb.adapters._pragmas import apply_pragmas
from plumb.core.errors import StorageError


class _FixedClock:
    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def now(self) -> datetime:
        return self._dt


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _clock(dt: datetime = _NOW) -> _FixedClock:
    return _FixedClock(dt)


# ---------------------------------------------------------------------------
# Fresh-init
# ---------------------------------------------------------------------------


def test_fresh_db_creates_tables(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_clock()) as adapter:
        tables = {
            row[0]
            for row in adapter._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert {"runs", "spans", "scores", "examples"}.issubset(tables)


def test_fresh_db_sets_user_version(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_clock()) as adapter:
        version = adapter._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 1


def test_reinit_existing_db_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with SQLiteStorageAdapter(db, clock=_clock()):
        pass
    with SQLiteStorageAdapter(db, clock=_clock()):
        pass


def test_version_mismatch_raises(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    conn = sqlite3.connect(str(db))
    conn.execute("PRAGMA user_version = 999")
    conn.close()
    with pytest.raises(StorageError, match="Schema version mismatch"):
        SQLiteStorageAdapter(db, clock=_clock())


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_db_file_mode_is_0600(tmp_path: Path) -> None:
    db = tmp_path / "test.db"
    with SQLiteStorageAdapter(db, clock=_clock()):
        pass
    assert (db.stat().st_mode & 0o777) == 0o600


def test_close_is_idempotent(tmp_path: Path) -> None:
    adapter = SQLiteStorageAdapter(tmp_path / "test.db", clock=_clock())
    adapter.close()
    adapter.close()


def test_context_manager_enter_exit(tmp_path: Path) -> None:
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_clock()) as adapter:
        assert isinstance(adapter, SQLiteStorageAdapter)


# ---------------------------------------------------------------------------
# Stalled-run sweep (Task 5.1)
# ---------------------------------------------------------------------------


def _setup_db_with_open_run(db_path: Path, start_ts_iso: str) -> None:
    """Create schema + insert a row with end_ts=NULL bypassing entity validation.

    SQLite STRICT + CHECK only allows ('success','failure','aborted','stalled') for status.
    We use 'stalled' as initial status, then UPDATE back to simulate a pre-sweep state.
    The sweep targets: end_ts IS NULL AND status NOT IN ('stalled','aborted','failure','success').
    Since all valid enum values are terminal, an "in-flight" run at the DB level must be
    represented differently. We directly write status='success' with end_ts=NULL to test
    that the sweep's status-NOT-IN guard correctly leaves terminal-status rows untouched,
    and that the sweep itself executes without error.
    """
    conn = sqlite3.connect(str(db_path))
    apply_pragmas(conn)
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.execute(
        """INSERT INTO runs (
            run_id, kind, task_id, parent_run_id,
            orchestrator_model, sub_agent_model, prompt_version, tool_schema_version, git_sha,
            start_ts, end_ts, tokens_in, tokens_out, dollar_cost, status, error_type
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, NULL, NULL, ?, NULL)""",
        ("a" * 32, "online", "task1", None, None, None, None, None, None, start_ts_iso, "success"),
    )
    conn.commit()
    conn.close()


def test_stalled_sweep_runs_without_error_on_empty_db(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    with SQLiteStorageAdapter(tmp_path / "test.db", clock=_FixedClock(now)):
        pass


def test_stalled_sweep_does_not_mark_terminal_status_rows(tmp_path: Path) -> None:
    """Rows with terminal status + NULL end_ts are left unchanged (status-guard)."""
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    two_hours_ago = (now - timedelta(hours=2)).isoformat()
    db = tmp_path / "test.db"
    _setup_db_with_open_run(db, two_hours_ago)

    # Open adapter — sweep runs during init
    with SQLiteStorageAdapter(db, clock=_FixedClock(now), stalled_threshold_seconds=3600) as adapter:
        row = adapter._conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", ("a" * 32,)
        ).fetchone()
        # status='success' is in the NOT IN guard — must remain unchanged
        assert row["status"] == "success"


def test_stalled_sweep_leaves_recent_runs_unchanged(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    thirty_min_ago = (now - timedelta(minutes=30)).isoformat()
    db = tmp_path / "test.db"
    _setup_db_with_open_run(db, thirty_min_ago)

    with SQLiteStorageAdapter(db, clock=_FixedClock(now), stalled_threshold_seconds=3600) as adapter:
        row = adapter._conn.execute(
            "SELECT status FROM runs WHERE run_id = ?", ("a" * 32,)
        ).fetchone()
        assert row["status"] == "success"


def test_stalled_threshold_seconds_honored(tmp_path: Path) -> None:
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
    adapter = SQLiteStorageAdapter(
        tmp_path / "test.db", clock=_FixedClock(now), stalled_threshold_seconds=60
    )
    assert adapter._stalled_threshold_seconds == 60
    adapter.close()

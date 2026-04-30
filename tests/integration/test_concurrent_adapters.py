"""Integration tests for concurrent SQLiteStorageAdapter instances (Task 5.2).

Verifies WAL semantics: two adapter instances on the same db_path can coexist
and that a reader never blocks on a writer's open transaction.
"""

import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Run, RunKind, RunStatus


class _FixedClock:
    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def now(self) -> datetime:
        return self._dt


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
_CLOCK = _FixedClock(_NOW)


def _make_run(run_id: str, task_id: str = "task") -> Run:
    return Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.ONLINE,
        status=RunStatus.SUCCESS,
        start_ts=_NOW,
        end_ts=_NOW,
    )


def test_two_adapters_open_same_db_without_error(tmp_path: Path) -> None:
    """Two SQLiteStorageAdapter instances on the same db_path both open cleanly."""
    db = tmp_path / "shared.db"
    with (
        SQLiteStorageAdapter(db, clock=_CLOCK) as adapter1,
        SQLiteStorageAdapter(db, clock=_CLOCK) as adapter2,
    ):
        assert adapter1 is not adapter2


def test_reader_sees_data_committed_by_writer(tmp_path: Path) -> None:
    """Data written and committed by adapter1 is readable by adapter2."""
    db = tmp_path / "shared.db"
    run = _make_run("a" * 32)

    with SQLiteStorageAdapter(db, clock=_CLOCK) as writer:
        writer.write_run(run, [])

    with SQLiteStorageAdapter(db, clock=_CLOCK) as reader:
        result = reader.get_run(run.run_id)
        assert result is not None
        assert result.run_id == run.run_id
        assert result.task_id == run.task_id


def test_reader_sees_data_after_writer_commits_concurrent_adapters(tmp_path: Path) -> None:
    """Reader adapter sees a run written by writer adapter after commit.

    Both adapters are open simultaneously.
    """
    db = tmp_path / "shared.db"
    run = _make_run("b" * 32, "concurrent-task")

    with (
        SQLiteStorageAdapter(db, clock=_CLOCK) as writer,
        SQLiteStorageAdapter(db, clock=_CLOCK) as reader,
    ):
        # Before write: not visible
        assert reader.get_run(run.run_id) is None

        # Writer commits
        writer.write_run(run, [])

        # After commit: reader sees the data (WAL checkpoint not required for read)
        result = reader.get_run(run.run_id)
        assert result is not None
        assert result.run_id == run.run_id


def test_writer_does_not_block_reader_list_runs(tmp_path: Path) -> None:
    """A writer holding BEGIN does not block a reader's list_runs (WAL semantics).

    Uses threads to simulate concurrent access: writer starts a transaction,
    reader calls list_runs while writer holds the lock, then writer commits.
    Under WAL, readers never block behind writers.
    """
    db = tmp_path / "shared.db"

    # Pre-populate one run so list_runs has something to return
    seed_run = _make_run("a" * 32, "seed")
    with SQLiteStorageAdapter(db, clock=_CLOCK) as seeder:
        seeder.write_run(seed_run, [])

    writer_ready = threading.Event()
    writer_commit = threading.Event()
    reader_result: list[int] = []
    reader_blocked = threading.Event()

    def writer_thread() -> None:
        with SQLiteStorageAdapter(db, clock=_CLOCK) as writer:
            # Begin a transaction but hold it open
            writer._conn.execute("BEGIN IMMEDIATE")
            writer_ready.set()
            # Wait for reader to finish before committing
            writer_commit.wait(timeout=5.0)
            writer._conn.execute("ROLLBACK")

    def reader_thread() -> None:
        with SQLiteStorageAdapter(db, clock=_CLOCK) as reader:
            writer_ready.wait(timeout=5.0)
            start = time.monotonic()
            results = reader.list_runs()
            elapsed = time.monotonic() - start
            reader_result.append(len(results))
            # If reader was blocked, elapsed would be large; WAL means it should be fast
            reader_blocked.set()
            assert elapsed < 1.0, f"list_runs blocked for {elapsed:.2f}s — WAL not working?"

    t_writer = threading.Thread(target=writer_thread, daemon=True)
    t_reader = threading.Thread(target=reader_thread, daemon=True)

    t_writer.start()
    t_reader.start()

    # Wait for reader to finish, then let writer commit
    reader_blocked.wait(timeout=5.0)
    writer_commit.set()

    t_writer.join(timeout=5.0)
    t_reader.join(timeout=5.0)

    assert not t_writer.is_alive(), "Writer thread did not finish in time"
    assert not t_reader.is_alive(), "Reader thread did not finish in time"
    assert reader_result == [1], f"Expected 1 result from list_runs, got {reader_result}"


def test_concurrent_adapters_run_within_time_budget(tmp_path: Path) -> None:
    """Full concurrent-open + read scenario completes in under 2 seconds."""
    db = tmp_path / "shared.db"
    start = time.monotonic()

    with (
        SQLiteStorageAdapter(db, clock=_CLOCK) as writer,
        SQLiteStorageAdapter(db, clock=_CLOCK) as reader,
    ):
        run = _make_run("c" * 32)
        writer.write_run(run, [])
        result = reader.get_run(run.run_id)
        assert result is not None

    elapsed = time.monotonic() - start
    assert elapsed < 2.0, f"Concurrent adapter test took {elapsed:.2f}s, budget is 2s"

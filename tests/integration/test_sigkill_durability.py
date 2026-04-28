"""SIGKILL durability test — NFR-Rel-2 / AC-REL-2 (Task 7.1).

A child Python process writes a sentinel run+spans, prints READY, then sleeps.
The parent sends SIGKILL.  After the kill the parent re-opens the DB and asserts
the committed data is fully intact.

Skipped on Windows (SIGKILL not portable).
Runs on ubuntu-24.04 and macos-14 in CI.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter

HELPER = Path(__file__).parent / "_sigkill_helper.py"

# Fixed IDs matching what the helper writes
_RUN_ID = "deadbeef" * 4  # 32 hex chars
_SPAN_BASE = "cafebabe" * 4  # first 29 chars + 3-digit suffix = 32 chars


class _FixedClock:
    def now(self) -> datetime:
        return datetime(2024, 6, 1, tzinfo=UTC)


@pytest.mark.skipif(os.name == "nt", reason="SIGKILL not portable on Windows")
def test_sigkill_durability(tmp_path: Path) -> None:
    """Committed writes survive a SIGKILL (NFR-Rel-2)."""
    db_path = tmp_path / "plumb.db"

    proc = subprocess.Popen(
        [sys.executable, str(HELPER), str(db_path), _RUN_ID, _SPAN_BASE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        # Wait for "READY" — means write_run committed and fsynced
        line = proc.stdout.readline()  # type: ignore[union-attr]
        assert line.strip() == "READY", f"Helper did not print READY; got: {line!r}"

        # Kill the child process
        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=5)
    except Exception:
        proc.kill()
        proc.wait()
        raise

    # Re-open the DB in the parent process
    adapter = SQLiteStorageAdapter(db_path, clock=_FixedClock())
    try:
        run = adapter.get_run(_RUN_ID)
        assert run is not None, "Sentinel run missing after SIGKILL"
        assert run.run_id == _RUN_ID
        assert run.task_id == "sigkill-sentinel"
        assert run.start_ts == datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
        assert run.parent_run_id is None

        spans = adapter.get_spans_for_run(_RUN_ID)
        assert len(spans) == 3, f"Expected 3 spans, got {len(spans)}"

        span_ids = {s.span_id for s in spans}
        for i in range(3):
            expected = f"{_SPAN_BASE[:29]}{i:03d}"
            assert expected in span_ids, f"Span {i} missing: {expected}"
    finally:
        adapter.close()

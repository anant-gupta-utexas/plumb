"""Helper script for the SIGKILL durability test (Task 7.1).

Usage:
    python _sigkill_helper.py <db_path> <run_id> <span_id>

The script:
1. Opens a real SQLiteStorageAdapter on <db_path>.
2. Writes a sentinel run + 3 spans via write_run.
3. Prints "READY" to stdout and flushes (parent reads this to know the write committed).
4. Sleeps indefinitely — parent kills the process with SIGKILL.
"""

from __future__ import annotations

import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# Ensure project root is on sys.path when invoked as a subprocess
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Run, RunKind, RunStatus, Span, SpanKind


class _FixedClock:
    def __init__(self, ts: datetime) -> None:
        self._ts = ts

    def now(self) -> datetime:
        return self._ts


def main() -> None:
    db_path = Path(sys.argv[1])
    run_id = sys.argv[2]
    span_id_base = sys.argv[3]

    start_ts = datetime(2024, 6, 1, 12, 0, 0, tzinfo=UTC)
    end_ts = datetime(2024, 6, 1, 12, 0, 1, tzinfo=UTC)

    clock = _FixedClock(start_ts)
    adapter = SQLiteStorageAdapter(db_path, clock=clock)

    sentinel_run = Run(
        run_id=run_id,
        task_id="sigkill-sentinel",
        kind=RunKind.OFFLINE,
        status=RunStatus.SUCCESS,
        start_ts=start_ts,
        end_ts=end_ts,
    )

    spans = [
        Span(
            span_id=f"{span_id_base[:29]}{i:03d}",
            run_id=run_id,
            kind=SpanKind.LLM,
            name=f"sentinel-span-{i}",
        )
        for i in range(3)
    ]

    adapter.write_run(sentinel_run, spans)

    # Signal parent: write is committed and fsynced
    sys.stdout.write("READY\n")
    sys.stdout.flush()

    # Sleep until killed
    time.sleep(3600)


if __name__ == "__main__":
    main()

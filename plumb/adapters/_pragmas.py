"""SQLite connection-time PRAGMA helpers (TRD NFR-Perf-3)."""

from __future__ import annotations

import sqlite3

from plumb.core.errors import StorageError

_PRAGMAS: dict[str, str | int] = {
    "journal_mode": "WAL",
    "synchronous": "NORMAL",
    "busy_timeout": 5000,
    "foreign_keys": "ON",
}

# journal_mode returns the mode that was set; others return the int value
_PRAGMA_EXPECTED: dict[str, object] = {
    "journal_mode": "wal",
    "synchronous": 1,  # NORMAL == 1
    "busy_timeout": 5000,
    "foreign_keys": 1,
}


def apply_pragmas(conn: sqlite3.Connection) -> None:
    """Apply WAL + durability + FK pragmas. Safe to call multiple times."""
    for name, value in _PRAGMAS.items():
        conn.execute(f"PRAGMA {name}={value}")  # noqa: S608 — name/value come from module-level literal dict, not user input


def verify_pragmas(conn: sqlite3.Connection) -> None:
    """Raise StorageError if any required pragma is not at the expected value."""
    for name, expected in _PRAGMA_EXPECTED.items():
        row = conn.execute(f"PRAGMA {name}").fetchone()  # noqa: S608 — name comes from module-level literal dict, not user input
        actual = row[0] if row else None
        if actual != expected:
            raise StorageError(f"PRAGMA {name}: expected {expected!r}, got {actual!r}")

"""Tests for _pragmas.py — apply_pragmas + verify_pragmas (Task 1.3)."""

import os
import sqlite3
import tempfile

import pytest

from plumb.adapters._pragmas import apply_pragmas, verify_pragmas
from plumb.core.errors import StorageError


def _fresh_conn() -> sqlite3.Connection:
    # WAL mode requires a real file; :memory: silently stays in 'memory' mode
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return sqlite3.connect(path)


def test_apply_sets_journal_mode_wal() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_apply_sets_synchronous_normal() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    value = conn.execute("PRAGMA synchronous").fetchone()[0]
    assert value == 1  # NORMAL == 1


def test_apply_sets_busy_timeout() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    value = conn.execute("PRAGMA busy_timeout").fetchone()[0]
    assert value == 5000


def test_apply_sets_foreign_keys_on() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    value = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert value == 1


def test_apply_idempotent() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    apply_pragmas(conn)  # second call must not raise
    # end state unchanged
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


def test_verify_passes_after_apply() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    verify_pragmas(conn)  # must not raise


def test_verify_fails_when_foreign_keys_off() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    conn.execute("PRAGMA foreign_keys=OFF")
    # verify_pragmas must raise StorageError mentioning the offending pragma
    with pytest.raises(StorageError):
        verify_pragmas(conn)


def test_verify_fails_when_synchronous_wrong() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    conn.execute("PRAGMA synchronous=FULL")
    with pytest.raises(StorageError):
        verify_pragmas(conn)


def test_verify_error_message_names_the_pragma() -> None:
    conn = _fresh_conn()
    apply_pragmas(conn)
    conn.execute("PRAGMA foreign_keys=OFF")
    with pytest.raises(StorageError, match="foreign_keys|journal_mode|synchronous|busy_timeout"):
        verify_pragmas(conn)

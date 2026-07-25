"""Integration tests for the v1.0 -> v1.1 `user_version` 1->2 migration.

Real temp-file SQLite is required throughout (not :memory:) because
`user_version` persistence and reopen semantics are exactly what's under test.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

from plumb.adapters._pragmas import apply_pragmas
from plumb.adapters._schema import DDL_STATEMENTS
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.errors import StorageError


class _FixedClock:
    def __init__(self, dt: datetime) -> None:
        self._dt = dt

    def now(self) -> datetime:
        return self._dt


_NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _make_v1_db(db_path: Path) -> None:
    """Build a v1.0-shaped DB: v1 DDL only, user_version=1, no migration columns."""
    conn = sqlite3.connect(str(db_path))
    apply_pragmas(conn)
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 1")
    conn.commit()
    conn.close()


def _insert_run(db_path: Path, run_id: str, task_id: str = "task1") -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "INSERT INTO runs (run_id, kind, task_id, start_ts, status) VALUES (?, ?, ?, ?, ?)",
        (run_id, "online", task_id, _NOW.isoformat(), "success"),
    )
    conn.commit()
    conn.close()


def _insert_span(
    db_path: Path,
    span_id: str,
    run_id: str,
    *,
    tokens: int | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO spans (span_id, run_id, kind, name, tokens)
        VALUES (?, ?, 'llm', 'generate', ?)
        """,
        (span_id, run_id, tokens),
    )
    conn.commit()
    conn.close()


def _insert_score(
    db_path: Path,
    score_id: str,
    run_id: str,
    *,
    metric_name: str = "accuracy",
    scorer_version: str = "v1",
    span_id: str | None = None,
) -> None:
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        INSERT INTO scores
            (score_id, run_id, span_id, metric_name, scorer,
             scorer_version, value_numeric, scored_at)
        VALUES (?, ?, ?, ?, 'deterministic', ?, 1.0, ?)
        """,
        (score_id, run_id, span_id, metric_name, scorer_version, _NOW.isoformat()),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# AC-MIG-1 — v1.0 DB opened by this build migrates to user_version=2
# ---------------------------------------------------------------------------


def test_migration_bumps_version_and_adds_columns(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    _insert_run(db, "a" * 32)
    _insert_score(db, "c" * 32, "a" * 32)

    with SQLiteStorageAdapter(db, clock=_FixedClock(_NOW)) as adapter:
        version = adapter._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2

        cols = {r[1] for r in adapter._conn.execute("PRAGMA table_info(scores)").fetchall()}
        assert "rationale" in cols

        span_cols = {r[1] for r in adapter._conn.execute("PRAGMA table_info(spans)").fetchall()}
        assert {"tokens_in", "tokens_out", "attributes"}.issubset(span_cols)

        idx_names = {
            r[0]
            for r in adapter._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
        assert "idx_scores_idem" in idx_names

        # pre-existing rows readable unchanged
        run = adapter.get_run("a" * 32)
        assert run is not None
        scores = adapter.get_scores_for_run("a" * 32)
        assert len(scores) == 1
        # FR-RATIONALE-3: pre-migration score row reads back with rationale=None
        assert scores[0].rationale is None


# ---------------------------------------------------------------------------
# AC-TOKENS-2 — a v1.0-written span row falls back to legacy `tokens` on read
# ---------------------------------------------------------------------------


def test_migrated_legacy_span_tokens_fallback(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    _insert_run(db, "a" * 32)
    _insert_span(db, "1" * 32, "a" * 32, tokens=35)

    with SQLiteStorageAdapter(db, clock=_FixedClock(_NOW)) as adapter:
        spans = adapter.get_spans_for_run("a" * 32)
        assert len(spans) == 1
        assert spans[0].tokens_in == 35
        assert spans[0].tokens_out is None
        # AC-ATTR-2: a v1.0-written span row (attributes NULL post-migration)
        # reads back as Span.attributes is None, no read error.
        assert spans[0].attributes is None


# ---------------------------------------------------------------------------
# AC-MIG-2 — reopening an already-migrated DB is a no-op
# ---------------------------------------------------------------------------


def test_reopen_already_migrated_db_is_noop(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    with SQLiteStorageAdapter(db, clock=_FixedClock(_NOW)):
        pass

    # second open must not error and must not re-run ALTER/CREATE INDEX
    with SQLiteStorageAdapter(db, clock=_FixedClock(_NOW)) as adapter:
        version = adapter._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2


# ---------------------------------------------------------------------------
# AC-MIG-3 — duplicate scores rows abort migration, zero deletions
# ---------------------------------------------------------------------------


def test_migration_aborts_on_duplicate_scores(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    _insert_run(db, "a" * 32)
    _insert_score(db, "c" * 32, "a" * 32, metric_name="accuracy", scorer_version="v1")
    _insert_score(db, "d" * 32, "a" * 32, metric_name="accuracy", scorer_version="v1")

    with pytest.raises(StorageError, match="duplicate"):
        SQLiteStorageAdapter(db, clock=_FixedClock(_NOW))

    # user_version stays 1, both duplicate rows still present
    conn = sqlite3.connect(str(db))
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
    count = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    assert count == 2
    conn.close()


# ---------------------------------------------------------------------------
# AC-MIG-4 — injected failure rolls back the whole migration atomically
# ---------------------------------------------------------------------------


def test_migration_failure_rolls_back_atomically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    _insert_run(db, "a" * 32)

    import plumb.adapters.storage_sqlite as storage_mod

    broken = (
        *storage_mod.MIGRATION_1_TO_2[:-2],
        "CREATE UNIQUE INDEX idx_scores_idem_BOGUS SYNTAX ERROR",
    )
    monkeypatch.setattr(storage_mod, "MIGRATION_1_TO_2", broken)

    with pytest.raises(StorageError):
        SQLiteStorageAdapter(db, clock=_FixedClock(_NOW))

    conn = sqlite3.connect(str(db))
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    assert version == 1
    cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    assert "rationale" not in cols  # earlier-in-transaction column also rolled back
    conn.close()


# ---------------------------------------------------------------------------
# Regression guard — DB at user_version > SCHEMA_VERSION still raises
# ---------------------------------------------------------------------------


def test_downgrade_still_raises_storage_error(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    conn = sqlite3.connect(str(db))
    for stmt in DDL_STATEMENTS:
        conn.execute(stmt)
    conn.execute("PRAGMA user_version = 999")
    conn.close()

    with pytest.raises(StorageError, match="Schema version mismatch"):
        SQLiteStorageAdapter(db, clock=_FixedClock(_NOW))


# ---------------------------------------------------------------------------
# NFR-MIG-1 — migration completes <=500ms for a 100k-score-row fixture
# ---------------------------------------------------------------------------


@pytest.mark.perf
def test_migration_performance_100k_scores(tmp_path: Path) -> None:
    db = tmp_path / "v1.db"
    _make_v1_db(db)
    _insert_run(db, "a" * 32)

    conn = sqlite3.connect(str(db))
    rows = [
        (f"{i:032x}", "a" * 32, None, "metric", "deterministic", f"v{i}", 1.0, _NOW.isoformat())
        for i in range(100_000)
    ]
    conn.executemany(
        """
        INSERT INTO scores
            (score_id, run_id, span_id, metric_name, scorer,
             scorer_version, value_numeric, scored_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    conn.commit()
    conn.close()

    start = time.perf_counter()
    with SQLiteStorageAdapter(db, clock=_FixedClock(_NOW)) as adapter:
        elapsed_ms = (time.perf_counter() - start) * 1000
        version = adapter._conn.execute("PRAGMA user_version").fetchone()[0]
        assert version == 2

    assert elapsed_ms <= 500, f"migration took {elapsed_ms:.1f}ms, budget is 500ms"

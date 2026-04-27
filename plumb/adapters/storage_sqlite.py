"""SQLiteStorageAdapter — implements StorageWriter + StorageReader (TRD §7.1)."""

from __future__ import annotations

import logging
import os
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from plumb.adapters._pragmas import apply_pragmas
from plumb.adapters._schema import DDL_STATEMENTS, SCHEMA_VERSION
from plumb.core.entities import (
    Example,
    ExampleSource,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)
from plumb.core.errors import StorageError, ValidationError
from plumb.core.ports import Clock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------


def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise StorageError("datetime must be timezone-aware before storage")
    return dt.isoformat()


def _iso_to_dt(s: str | None) -> datetime | None:
    if s is None:
        return None
    return datetime.fromisoformat(s)


def _run_to_row(run: Run) -> tuple[Any, ...]:
    return (
        run.run_id,
        run.kind.value,
        run.task_id,
        run.parent_run_id,
        run.orchestrator_model,
        run.sub_agent_model,
        run.prompt_version,
        run.tool_schema_version,
        run.git_sha,
        _dt_to_iso(run.start_ts),
        _dt_to_iso(run.end_ts),
        run.tokens_in,
        run.tokens_out,
        run.dollar_cost,
        run.status.value,
        run.error_type,
    )


def _span_to_row(span: Span) -> tuple[Any, ...]:
    tokens: int | None = None
    if span.tokens_in is not None or span.tokens_out is not None:
        tokens = (span.tokens_in or 0) + (span.tokens_out or 0)
    latency_ms: int | None = None
    if span.latency_ms is not None:
        latency_ms = int(span.latency_ms)
    return (
        span.span_id,
        span.run_id,
        span.parent_span_id,
        span.kind.value,
        span.name,
        span.input_hash,
        span.output_hash,
        tokens,
        latency_ms,
        span.status.value if span.status is not None else None,
        span.error_type,
    )


def _score_to_row(score: Score) -> tuple[Any, ...]:
    return (
        score.score_id,
        score.run_id,
        score.span_id,
        score.metric_name,
        score.scorer.value,
        score.scorer_version,
        score.value_numeric,
        score.value_label,
        _dt_to_iso(score.scored_at),
    )


def _example_to_row(example: Example) -> tuple[Any, ...]:
    return (
        example.example_id,
        example.task_id,
        example.inputs_hash,
        example.expected_output_hash,
        None,  # rubric — not in entity; stored as NULL
        example.source.value,
        None,  # origin_run_id — not in entity
        1 if example.active else 0,
        _dt_to_iso(example.created_at),
    )


def _row_to_run(row: sqlite3.Row) -> Run:
    return Run(
        run_id=row["run_id"],
        kind=RunKind(row["kind"]),
        task_id=row["task_id"],
        parent_run_id=row["parent_run_id"],
        orchestrator_model=row["orchestrator_model"],
        sub_agent_model=row["sub_agent_model"],
        prompt_version=row["prompt_version"],
        tool_schema_version=row["tool_schema_version"],
        git_sha=row["git_sha"],
        start_ts=_iso_to_dt(row["start_ts"]),  # type: ignore[arg-type]
        end_ts=_iso_to_dt(row["end_ts"]),
        tokens_in=row["tokens_in"],
        tokens_out=row["tokens_out"],
        dollar_cost=row["dollar_cost"],
        status=RunStatus(row["status"]),
        error_type=row["error_type"],
    )


def _row_to_span(row: sqlite3.Row) -> Span:
    # DB has a single `tokens` column; entity tracks tokens_in/tokens_out separately.
    # On read, the stored total is surfaced as tokens_in; tokens_out stays None.
    tokens_in: int | None = None
    tokens_out: int | None = None
    if row["tokens"] is not None:
        tokens_in = row["tokens"]
    latency: float | None = None
    if row["latency_ms"] is not None:
        latency = float(row["latency_ms"])
    status_val = row["status"]
    return Span(
        span_id=row["span_id"],
        run_id=row["run_id"],
        parent_span_id=row["parent_span_id"],
        kind=SpanKind(row["kind"]),
        name=row["name"],
        input_hash=row["input_hash"],
        output_hash=row["output_hash"],
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=latency,
        status=SpanStatus(status_val) if status_val is not None else None,
        error_type=row["error_type"],
    )


def _row_to_score(row: sqlite3.Row) -> Score:
    return Score(
        score_id=row["score_id"],
        run_id=row["run_id"],
        span_id=row["span_id"],
        metric_name=row["metric_name"],
        scorer=ScorerKind(row["scorer"]),
        scorer_version=row["scorer_version"],
        value_numeric=row["value_numeric"],
        value_label=row["value_label"],
        scored_at=_iso_to_dt(row["scored_at"]),  # type: ignore[arg-type]
    )


def _row_to_example(row: sqlite3.Row) -> Example:
    return Example(
        example_id=row["example_id"],
        task_id=row["task_id"],
        inputs_hash=row["inputs_hash"],
        expected_output_hash=row["expected_output_hash"],
        source=ExampleSource(row["source"]),
        active=bool(row["active"]),
        created_at=_iso_to_dt(row["created_at"]),  # type: ignore[arg-type]
        tags=None,
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

_INSERT_RUN = """
INSERT INTO runs (
    run_id, kind, task_id, parent_run_id,
    orchestrator_model, sub_agent_model, prompt_version, tool_schema_version, git_sha,
    start_ts, end_ts, tokens_in, tokens_out, dollar_cost, status, error_type
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()

# Minimal pending-row INSERT: only the FK-relevant and NOT NULL columns.
# All optional metadata columns stay NULL; finalize_run fills them in.
_INSERT_PENDING_RUN = """
INSERT INTO runs (run_id, kind, task_id, parent_run_id, start_ts, status)
VALUES (?, ?, ?, ?, ?, 'pending')
""".strip()

_FINALIZE_RUN = """
UPDATE runs
SET
    status              = ?,
    end_ts              = ?,
    error_type          = ?,
    orchestrator_model  = ?,
    sub_agent_model     = ?,
    prompt_version      = ?,
    tool_schema_version = ?,
    git_sha             = ?
WHERE run_id = ?
""".strip()

_INSERT_SPAN = """
INSERT INTO spans (
    span_id, run_id, parent_span_id, kind, name,
    input_hash, output_hash, tokens, latency_ms, status, error_type
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()

_INSERT_SCORE = """
INSERT INTO scores (
    score_id, run_id, span_id, metric_name, scorer, scorer_version,
    value_numeric, value_label, scored_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()

_INSERT_EXAMPLE = """
INSERT INTO examples (
    example_id, task_id, inputs_hash, expected_output_hash, rubric,
    source, origin_run_id, active, created_at
) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""".strip()


class SQLiteStorageAdapter:
    """Implements StorageWriter + StorageReader against a single SQLite file."""

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Clock,
        stalled_threshold_seconds: int = 3600,
    ) -> None:
        self._db_path = Path(db_path)
        self._clock = clock
        self._stalled_threshold_seconds = stalled_threshold_seconds
        self._closed = False

        self._db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        self._conn = sqlite3.connect(
            str(self._db_path),
            isolation_level=None,
            check_same_thread=False,
            timeout=5.0,
        )
        self._conn.row_factory = sqlite3.Row

        apply_pragmas(self._conn)
        self._bootstrap_schema()
        self._sweep_stalled_runs()

        if os.name != "nt":
            import contextlib

            with contextlib.suppress(OSError):
                os.chmod(self._db_path, 0o600)

    def _bootstrap_schema(self) -> None:
        # Run DDL idempotently then check/set user_version.
        with self._conn:
            for stmt in DDL_STATEMENTS:
                self._conn.execute(stmt)

        version: int = self._conn.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            self._conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            raise StorageError(f"Schema version mismatch: db={version} expected={SCHEMA_VERSION}")

    def _sweep_stalled_runs(self) -> None:
        threshold = self._clock.now() - timedelta(seconds=self._stalled_threshold_seconds)
        threshold_iso = threshold.isoformat()
        # 'pending' rows are mid-flight runs (INSERT-on-enter); they are the
        # primary target of the sweep.  The broader NOT IN guard is defense-in-depth.
        cur = self._conn.execute(
            """
            UPDATE runs
            SET status = 'stalled'
            WHERE end_ts IS NULL
              AND status NOT IN ('stalled', 'aborted', 'failure', 'success')
              AND start_ts < ?
            """,
            (threshold_iso,),
        )
        count = cur.rowcount
        if count:
            logger.info(
                "Stalled-run sweep marked %d run(s) as 'stalled' (threshold=%s)",
                count,
                threshold_iso,
            )

    # -------------------------------------------------------------------------
    # StorageWriter — two-phase protocol (open_run / finalize_run)
    # -------------------------------------------------------------------------

    def open_run(
        self,
        run_id: str,
        task_id: str,
        kind: RunKind,
        parent_run_id: str | None,
        start_ts: datetime,
    ) -> None:
        """INSERT a pending run row immediately at run-enter time (FR-GRAPH-1).

        The row exists in the DB before any child run's open_run fires, so the
        parent_run_id FK is always satisfied when the child row is inserted.
        """
        try:
            with self._conn:
                self._conn.execute(
                    _INSERT_PENDING_RUN,
                    (run_id, kind.value, task_id, parent_run_id, _dt_to_iso(start_ts)),
                )
        except sqlite3.IntegrityError as exc:
            raise StorageError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def finalize_run(
        self,
        run_id: str,
        status: RunStatus,
        end_ts: datetime,
        spans: Sequence[Span],
        *,
        error_type: str | None = None,
        orchestrator_model: str | None = None,
        sub_agent_model: str | None = None,
        prompt_version: str | None = None,
        tool_schema_version: str | None = None,
        git_sha: str | None = None,
    ) -> None:
        """UPDATE the pending row to its final status and batch-INSERT spans.

        Single transaction, single fsync (NFR-Perf-4).
        """
        span_rows = [_span_to_row(s) for s in spans]
        try:
            with self._conn:
                self._conn.execute(
                    _FINALIZE_RUN,
                    (
                        status.value,
                        _dt_to_iso(end_ts),
                        error_type,
                        orchestrator_model,
                        sub_agent_model,
                        prompt_version,
                        tool_schema_version,
                        git_sha,
                        run_id,
                    ),
                )
                if span_rows:
                    self._conn.executemany(_INSERT_SPAN, span_rows)
        except sqlite3.IntegrityError as exc:
            raise StorageError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def write_run(self, run: Run, spans: Sequence[Span]) -> None:
        run_row = _run_to_row(run)
        span_rows = [_span_to_row(s) for s in spans]
        try:
            with self._conn:
                self._conn.execute(_INSERT_RUN, run_row)
                if span_rows:
                    self._conn.executemany(_INSERT_SPAN, span_rows)
        except sqlite3.IntegrityError as exc:
            raise StorageError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def write_score(self, score: Score) -> None:
        try:
            self._conn.execute(_INSERT_SCORE, _score_to_row(score))
        except sqlite3.IntegrityError as exc:
            raise StorageError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    def write_example(self, example: Example) -> None:
        try:
            self._conn.execute(_INSERT_EXAMPLE, _example_to_row(example))
        except sqlite3.IntegrityError as exc:
            raise StorageError(str(exc)) from exc
        except sqlite3.Error as exc:
            raise StorageError(str(exc)) from exc

    # -------------------------------------------------------------------------
    # StorageReader
    # -------------------------------------------------------------------------

    def get_run(self, run_id: str) -> Run | None:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return _row_to_run(row)

    def list_runs(
        self,
        *,
        since: datetime | None = None,
        task_id: str | None = None,
        kind: str | None = None,
        limit: int = 100,
    ) -> list[Run]:
        if kind is not None:
            try:
                RunKind(kind)
            except ValueError as exc:
                raise ValidationError(f"Invalid kind: {kind!r}") from exc

        clauses: list[str] = []
        params: list[Any] = []

        if since is not None:
            clauses.append("start_ts >= ?")
            params.append(_dt_to_iso(since))
        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if kind is not None:
            clauses.append("kind = ?")
            params.append(kind)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)

        rows = self._conn.execute(
            f"SELECT * FROM runs {where} ORDER BY start_ts DESC LIMIT ?",  # noqa: S608
            params,
        ).fetchall()
        return [_row_to_run(r) for r in rows]

    def get_spans_for_run(self, run_id: str) -> list[Span]:
        rows = self._conn.execute(
            "SELECT * FROM spans WHERE run_id = ? ORDER BY span_id",
            (run_id,),
        ).fetchall()
        return [_row_to_span(r) for r in rows]

    def get_scores_for_run(self, run_id: str) -> list[Score]:
        rows = self._conn.execute(
            "SELECT * FROM scores WHERE run_id = ?",
            (run_id,),
        ).fetchall()
        return [_row_to_score(r) for r in rows]

    def list_examples(
        self,
        *,
        task_id: str | None = None,
        active: bool | None = None,
    ) -> list[Example]:
        clauses: list[str] = []
        params: list[Any] = []

        if task_id is not None:
            clauses.append("task_id = ?")
            params.append(task_id)
        if active is not None:
            clauses.append("active = ?")
            params.append(1 if active else 0)

        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""

        rows = self._conn.execute(
            f"SELECT * FROM examples {where}",  # noqa: S608
            params,
        ).fetchall()
        return [_row_to_example(r) for r in rows]

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._conn.close()

    def __enter__(self) -> SQLiteStorageAdapter:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

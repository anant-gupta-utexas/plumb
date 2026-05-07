"""plumb v1 read-only HTTP service (TRD FR-HTTP-2).

Bound to ``127.0.0.1:8765`` by default via ``plumb serve``.
All routes are read-only; no POST/PUT/DELETE/PATCH verbs exist.
"""

from __future__ import annotations

try:
    from fastapi import Depends, FastAPI, HTTPException, Path, Query, Request
    from fastapi.responses import JSONResponse
except ImportError as _e:
    raise ImportError(
        "plumb HTTP service requires 'fastapi' and 'uvicorn'. "
        "Install them with: pip install 'plumb[http]'"
    ) from _e

import logging
import sqlite3
from datetime import datetime
from typing import Annotated

import plumb
from plumb._http_deps import StoragePool, get_pool, get_pool_lifespan
from plumb._http_schemas import (
    ErrorOut,
    ExampleListOut,
    ExampleOut,
    HealthOut,
    RunDetailOut,
    RunListOut,
    RunOut,
    RunSummaryOut,
    ScoreOut,
    SpanOut,
    StatsOut,
)
from plumb._http_stats import NotFoundError as StatsNotFoundError, compute_task_stats
from plumb._time_utils import parse_since
from plumb.core.entities import RunSummaryRow
from plumb.core.errors import StorageError

logger = logging.getLogger(__name__)

app = FastAPI(
    title="plumb",
    version=plumb.__version__,
    description="plumb v1 read-only HTTP service (loopback only).",
    lifespan=get_pool_lifespan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _duration_ms(start_ts: str, end_ts: str | None) -> int | None:
    if end_ts is None:
        return None
    try:
        start = datetime.fromisoformat(start_ts)
        end = datetime.fromisoformat(end_ts)
        return int((end - start).total_seconds() * 1000)
    except (ValueError, TypeError):
        return None


def _run_summary_row_to_out(row: RunSummaryRow) -> RunSummaryOut:
    return RunSummaryOut(
        run_id=row.run_id,
        task_id=row.task_id,
        kind=row.kind,  # type: ignore[arg-type]
        status=row.status,  # type: ignore[arg-type]
        start_ts=datetime.fromisoformat(row.start_ts),
        end_ts=datetime.fromisoformat(row.end_ts) if row.end_ts else None,
        parent_run_id=row.parent_run_id,
        orchestrator_model=row.orchestrator_model,
        sub_agent_model=row.sub_agent_model,
        git_sha=row.git_sha,
        tokens_in=row.tokens_in,
        tokens_out=row.tokens_out,
        dollar_cost=row.dollar_cost,
        error_type=row.error_type,
        duration_ms=_duration_ms(row.start_ts, row.end_ts),
        span_count=row.span_count,
        score_count=row.score_count,
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthOut, tags=["health"])
def health() -> HealthOut:
    """Return a simple liveness probe.

    Returns:
        A ``HealthOut`` with ``status="ok"``. Never errors.
    """
    return HealthOut(status="ok")


@app.get(
    "/runs",
    response_model=RunListOut,
    tags=["runs"],
    summary="List runs with pagination",
    description=(
        "Return a paginated list of run summaries, optionally filtered by "
        "``since``, ``task_id``, and ``kind``. The ``total`` field reflects "
        "all matching runs regardless of ``offset``/``limit``."
    ),
)
def list_runs(
    since: Annotated[
        str | None,
        Query(description="ISO-8601 datetime or relative (7d, 2w, 1h, 30m)."),
    ] = None,
    task_id: Annotated[
        str | None,
        Query(description="Filter to a single task_id."),
    ] = None,
    kind: Annotated[
        str | None,
        Query(pattern="^(offline|online)$", description="Filter by run kind."),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500, description="Page size (1–500).")] = 100,
    offset: Annotated[int, Query(ge=0, description="Page offset.")] = 0,
    pool: Annotated[StoragePool, Depends(get_pool)] = ...,  # type: ignore[assignment]
) -> RunListOut:
    """List runs with span and score counts.

    Args:
        since: Optional time filter. Relative (``7d``) or ISO-8601.
        task_id: Optional task identifier filter.
        kind: Optional run kind filter (``offline`` or ``online``).
        limit: Maximum items per page (1–500, default 100).
        offset: Items to skip before returning results.
        pool: Injected storage pool.

    Returns:
        A paginated ``RunListOut``.

    Raises:
        HTTPException: 422 if ``since`` cannot be parsed.
    """
    since_dt = _parse_since_or_422(since)

    with pool.acquire() as reader:
        rows, total = reader.list_runs_with_counts_paged(
            since=since_dt,
            task_id=task_id,
            kind=kind,
            limit=limit,
            offset=offset,
        )

    return RunListOut(
        items=[_run_summary_row_to_out(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@app.get(
    "/runs/{run_id}",
    response_model=RunDetailOut,
    responses={404: {"model": ErrorOut}},
    tags=["runs"],
    summary="Get a run with spans and scores",
    description=(
        "Return the full detail for a single run: the run row, all spans "
        "ordered root-first then by ``parent_span_id``/``span_id``, and all "
        "scores. Hashes are 64-char hex; blob bodies are never inlined."
    ),
)
def get_run(
    run_id: Annotated[
        str,
        Path(
            min_length=32,
            max_length=32,
            pattern="^[0-9a-f]{32}$",
            description="32-char lowercase hex run ID.",
        ),
    ],
    pool: Annotated[StoragePool, Depends(get_pool)] = ...,  # type: ignore[assignment]
) -> RunDetailOut:
    """Return a run with all its spans and scores.

    Args:
        run_id: 32-char lowercase hex run ID. Invalid formats return 422.
        pool: Injected storage pool.

    Returns:
        ``RunDetailOut`` with the run row, ordered spans, and scores.

    Raises:
        HTTPException: 422 if ``run_id`` is not valid hex32.
        HTTPException: 404 if no run with that ID exists.
    """
    with pool.acquire() as reader:
        run = reader.get_run(run_id)
        if run is None:
            raise HTTPException(
                status_code=404,
                detail={"error_type": "not_found", "detail": f"Run {run_id[:8]} not found"},
            )

        spans = reader.get_spans_for_run(run_id)
        scores = reader.get_scores_for_run(run_id)

    run_out = RunOut(
        run_id=run.run_id,
        task_id=run.task_id,
        kind=run.kind.value,  # type: ignore[arg-type]
        status=run.status.value,  # type: ignore[arg-type]
        start_ts=run.start_ts,
        end_ts=run.end_ts,
        parent_run_id=run.parent_run_id,
        orchestrator_model=run.orchestrator_model,
        sub_agent_model=run.sub_agent_model,
        git_sha=run.git_sha,
        tokens_in=run.tokens_in,
        tokens_out=run.tokens_out,
        dollar_cost=run.dollar_cost,
        error_type=run.error_type,
        duration_ms=(
            int((run.end_ts - run.start_ts).total_seconds() * 1000)
            if run.end_ts is not None
            else None
        ),
    )

    spans_sorted = sorted(
        spans,
        key=lambda s: (
            s.parent_span_id is not None,
            s.parent_span_id or "",
            s.span_id,
        ),
    )

    span_outs = [
        SpanOut(
            span_id=s.span_id,
            run_id=s.run_id,
            parent_span_id=s.parent_span_id,
            kind=s.kind.value,  # type: ignore[arg-type]
            name=s.name,
            input_hash=s.input_hash,
            output_hash=s.output_hash,
            tokens=s.tokens_in,
            latency_ms=int(s.latency_ms) if s.latency_ms is not None else None,
            status=s.status.value if s.status is not None else None,  # type: ignore[arg-type]
            error_type=s.error_type,
        )
        for s in spans_sorted
    ]

    score_outs = [
        ScoreOut(
            score_id=sc.score_id,
            run_id=sc.run_id,
            span_id=sc.span_id,
            metric_name=sc.metric_name,
            scorer=sc.scorer.value,  # type: ignore[arg-type]
            scorer_version=sc.scorer_version,
            value_numeric=sc.value_numeric,
            value_label=sc.value_label,
            scored_at=sc.scored_at,
        )
        for sc in scores
    ]

    return RunDetailOut(run=run_out, spans=span_outs, scores=score_outs)


@app.get(
    "/examples",
    response_model=ExampleListOut,
    tags=["examples"],
    summary="List regression-set examples",
    description=(
        "Return all examples matching the optional ``task_id`` and ``active`` "
        "filters. No pagination in v1 — the examples table is bounded."
    ),
)
def list_examples(
    task_id: Annotated[
        str | None,
        Query(description="Filter to a specific task_id."),
    ] = None,
    active: Annotated[
        bool | None,
        Query(description="Filter by active flag."),
    ] = None,
    pool: Annotated[StoragePool, Depends(get_pool)] = ...,  # type: ignore[assignment]
) -> ExampleListOut:
    """List regression-set examples.

    Args:
        task_id: Optional task identifier filter.
        active: Optional active-flag filter.
        pool: Injected storage pool.

    Returns:
        ``ExampleListOut`` with all matching rows.
    """
    with pool.acquire() as reader:
        examples = reader.list_examples(task_id=task_id, active=active)

    example_outs = [
        ExampleOut(
            example_id=ex.example_id,
            task_id=ex.task_id,
            inputs_hash=ex.inputs_hash,
            expected_output_hash=ex.expected_output_hash,
            rubric=ex.rubric,
            source=ex.source.value,  # type: ignore[arg-type]
            origin_run_id=ex.origin_run_id,
            active=ex.active,
            created_at=ex.created_at,
        )
        for ex in examples
    ]

    return ExampleListOut(items=example_outs)


@app.get(
    "/stats/task/{task_id}",
    response_model=StatsOut,
    responses={404: {"model": ErrorOut}},
    tags=["stats"],
    summary="Get aggregated task statistics",
    description=(
        "Return the v1 ten-metric cut for ``task_id``, optionally filtered "
        "by ``since``. Returns 404 if no runs match the window."
    ),
)
def get_task_stats(
    task_id: Annotated[
        str,
        Path(min_length=1, max_length=255, description="Task identifier."),
    ],
    since: Annotated[
        str | None,
        Query(description="ISO-8601 datetime or relative (7d, 2w, 1h, 30m)."),
    ] = None,
    pool: Annotated[StoragePool, Depends(get_pool)] = ...,  # type: ignore[assignment]
) -> StatsOut:
    """Return aggregated v1 ten-metric statistics for a task.

    Args:
        task_id: The task identifier to aggregate over.
        since: Optional time filter. Relative (``7d``) or ISO-8601.
        pool: Injected storage pool.

    Returns:
        A ``StatsOut`` with all ten v1 metric fields.

    Raises:
        HTTPException: 422 if ``since`` cannot be parsed.
        HTTPException: 404 if no runs exist for the task in the window.
    """
    since_dt = _parse_since_or_422(since)

    with pool.acquire() as reader:
        try:
            return compute_task_stats(reader, task_id, since_dt)
        except StatsNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail={"error_type": "not_found", "detail": str(exc)},
            ) from exc


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------


@app.exception_handler(StorageError)
async def _storage_error_handler(request: Request, exc: StorageError) -> JSONResponse:
    """Convert StorageError to a 500 JSON envelope without leaking internals."""
    logger.warning("StorageError on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error_type": "plumb_internal_error", "detail": "Storage error"},
    )


@app.exception_handler(sqlite3.OperationalError)
async def _sqlite_busy_handler(request: Request, exc: sqlite3.OperationalError) -> JSONResponse:
    """Convert SQLite busy/locked errors to 503."""
    msg = str(exc).lower()
    if "locked" in msg or "busy" in msg:
        logger.warning("Database busy on %s", request.url.path)
        return JSONResponse(
            status_code=503,
            content={"error_type": "service_busy", "detail": "Database busy; retry"},
        )
    logger.warning("SQLite OperationalError on %s: %s", request.url.path, type(exc).__name__)
    return JSONResponse(
        status_code=500,
        content={"error_type": "plumb_internal_error", "detail": "Storage error"},
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _parse_since_or_422(since: str | None) -> datetime | None:
    if since is None:
        return None
    try:
        return parse_since(since)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail={"error_type": "validation_error", "detail": str(exc)},
        ) from exc

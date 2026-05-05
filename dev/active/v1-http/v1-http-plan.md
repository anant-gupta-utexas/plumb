# TRS — `plumb/http.py` (v1 HTTP Read Service Slice) — Part 1 of 2

**Status:** Draft v1 — derived from [TRD §3.6](../../../docs/2_architecture/TRD.md#36-local-read-only-http-service), follows [v1 CLI TRS](../../archive/v1-cli/v1-cli-plan.md), [v1 Storage Adapter TRS](../../archive/v1-storage-adapter/v1-storage-adapter-plan.md)
**Owner:** anant
**Last updated:** 2026-05-05
**Scope:** Sixth component slice of plumb v1 — the read-only FastAPI HTTP service launched by `plumb serve`, bound to `127.0.0.1:8765` by default, exposing JSON query endpoints over the four-table SQLite schema.

> **Reading order.** This file covers §§1–7 (scope, requirements, component design, API spec, DB, algorithms, errors). `[v1-http-plan-part2.md](./v1-http-plan-part2.md)` covers §§8–13 (dependencies, security, testing, performance, phases, pending decisions). Implementation tasks with checkboxes are in `[v1-http-tasks.md](./v1-http-tasks.md)`. Resolved decisions and integration notes are in `[v1-http-context.md](./v1-http-context.md)`. The split exists to keep each file under the 800-line workspace cap (`CLAUDE.md` "files < 400 lines, 800 max").

---

## 1. Overview & Scope

### 1.1 What this slice delivers

A FastAPI application served by `uvicorn`, exposing the **read-only** endpoints mandated by TRD FR-HTTP-2 over the existing `SQLiteStorageAdapter`:

```
GET /health
GET /runs?since=&task_id=&kind=&limit=&offset=
GET /runs/{run_id}
GET /examples?task_id=&active=
GET /stats/task/{task_id}?since=
GET /openapi.json     (auto)
GET /docs             (Swagger UI, auto)
```

**Files produced:**

- `plumb/http.py` — full FastAPI app, replaces the current 12-line stub.
- `plumb/_http_schemas.py` — Pydantic v2 response models (`RunOut`, `SpanOut`, `ScoreOut`, `RunDetailOut`, `ExampleOut`, `StatsOut`, `RunListOut`, `ErrorOut`).
- `plumb/_http_deps.py` — dependency-injected storage pool + `Settings` resolver.
- `plumb/_http_stats.py` — pure functions that aggregate the v1 ten-metric cut from a `StorageReader`.
- `tests/http/` — one test file per endpoint group.

**Files modified:**

- `plumb/cli.py` — already calls `uvicorn.run("plumb.http:app", ...)`; no edits expected.
- `plumb/core/ports.py` — extend `StorageReader` with read methods needed by `/stats` (see §3.5).
- `plumb/adapters/storage_sqlite.py` — implement the new reader methods.

### 1.2 What this slice does NOT deliver

- **No `POST/PUT/DELETE/PATCH` routes.** Writes go through `plumb.run` and CLI only (TRD FR-HTTP-2).
- **No authentication.** Loopback-only + single-user is the security posture (TRD §5.3 Assumption 3, NFR-Sec-4).
- **No blob endpoint.** `/runs/{run_id}` returns hashes only; users open blob files directly from disk via documented `$PLUMB_DATA_DIR/blobs/<2>/<62>` path.
- **No TLS / no reverse proxy / no Docker bundle.** Single-process `uvicorn` on loopback (TRD §8.2).
- **No metrics endpoint / no OpenTelemetry export.** PRD non-goal.
- **No streaming endpoints (SSE / WebSocket).** PRD non-goal "no real-time streaming".
- **No multi-tenant / no `?db=` query param.** Single SQLite file resolved from `Settings`.

### 1.3 Why this slice now

1. **Closes the FR-HTTP-2 gap.** The CLI slice landed `plumb serve` calling `uvicorn.run("plumb.http:app", ...)`, but `plumb/http.py` is currently a 12-line stub returning only `/health`. Until this slice ships, the TRD's promised query surface (§3.6) does not exist.
2. **Unblocks notebook + ad-hoc workflows.** Per [deferred-features.md "Library-only vs library + local service"](../../../docs/2_architecture/deferred-features.md), the read service is the v1 answer to "I just want to look at my runs" without writing a SQL harness.
3. **Final non-judge slice before ship.** With storage, autocapture, CLI, and judge adapters complete, this slice + the ATTACH adapter are the last v1-blocking work items.
4. **Exercises the `StorageReader` port end-to-end.** Forces gap-fixing in the reader surface (e.g., metric aggregation queries) that the CLI didn't need.

### 1.4 Anchor TRD references


| TRD ID    | Constraint                                                                  |
| --------- | --------------------------------------------------------------------------- |
| FR-HTTP-1 | Default bind `127.0.0.1`; non-loopback requires explicit `--host` + WARNING |
| FR-HTTP-2 | Read-only endpoint set; no write verbs                                      |
| FR-HTTP-3 | All bodies JSON; Pydantic v2 validation                                     |
| NFR-Sec-3 | Parameterized SQL only                                                      |
| NFR-Sec-4 | Loopback-only default; no auth required                                     |
| NFR-Rel-1 | HTTP errors degrade to structured response, never crash the process         |
| NFR-Use-3 | `mypy --strict` passes on `plumb/core/`; HTTP layer permissive              |
| NFR-Use-4 | Public-API docstring coverage ≥ 95% (`interrogate` on `plumb/http.py`)      |
| §5.4      | `fastapi ≥ 0.115`, `uvicorn ≥ 0.30`, `pydantic ≥ 2.6`                       |
| §3.6      | Endpoint inventory (the source of truth for routes)                         |


---

## 2. Requirements Summary

### 2.1 Functional requirements

- **FR-HTTP-1 (MUST).** `app` is a `fastapi.FastAPI` instance. Bind host/port comes from `plumb serve` flags, not from the app itself; the app is host-agnostic.
- **FR-HTTP-2.1 (MUST).** `GET /runs` returns paginated run summaries filtered by `since`, `task_id`, `kind`. Pagination is `limit` + `offset`.
- **FR-HTTP-2.2 (MUST).** `GET /runs/{run_id}` returns the run row, all spans (parent then child ordered), and all scores. 404 when the run is unknown.
- **FR-HTTP-2.3 (MUST).** `GET /examples` returns regression-set rows filtered by `task_id` and `active` boolean.
- **FR-HTTP-2.4 (MUST).** `GET /stats/task/{task_id}` returns aggregated v1 ten-metric cut for the task, scoped by `since`.
- **FR-HTTP-2.5 (MUST).** `GET /health` returns `{"status": "ok"}`. Already implemented in the current stub; preserved as-is.
- **FR-HTTP-3 (MUST).** Every response body is `application/json`. Every request param is validated by a Pydantic v2 model (`Annotated[..., Query(...)]` form is acceptable).
- **FR-HTTP-4 (MUST).** Validation failures return HTTP 422 with FastAPI's default error envelope. Resource-not-found returns HTTP 404. Internal failures return HTTP 500 with a sanitized envelope.

### 2.2 NFRs in scope

- **NFR-Sec-3 (MUST).** All SQL behind `/runs`, `/runs/{id}`, `/examples`, `/stats` uses parameterized bindings (already enforced by `SQLiteStorageAdapter`).
- **NFR-Sec-4 (MUST).** No authentication. The host-binding warning lives in `plumb serve`, not in the app.
- **NFR-Sec-7 (MUST, locally derived).** No secrets or filesystem absolute paths leak into HTTP error responses or `/openapi.json`. Stack traces never appear in 500 bodies.
- **NFR-Rel-1 (MUST).** Storage errors are caught at the route layer and converted to HTTP 500 with `error_type='plumb_internal_error'`. The uvicorn process keeps running.
- **NFR-Perf-7 (locally derived).** A `GET /runs?limit=100` against a 10k-row DB completes in p95 under 50 ms on the CI runner. No new I/O on the open path; reuse existing indexes.
- **NFR-Use-4 (MUST).** Every public route function has a Google-style docstring; `interrogate` already gates `plumb/http.py` per TRD §10.2.

### 2.3 Out of scope

- Authentication, rate limiting, CORS (single-user loopback).
- WebSocket / SSE.
- Multi-DB selection.
- Background tasks.
- Server-Sent Events for live tailing of runs.

---

## 3. Detailed Component Design

### 3.1 Module structure

```
plumb/
├── http.py             # FastAPI app: routes only (≤ 250 LOC)
├── _http_schemas.py    # Pydantic v2 response models (~150 LOC)
├── _http_deps.py       # Dependency injection: pool, settings (~60 LOC)
└── _http_stats.py      # Pure aggregation functions (~200 LOC)
```

Total target: ≤ 700 production LOC across new files. `plumb/http.py` itself stays thin — routes orchestrate, do not compute.

### 3.2 FastAPI app layout

```python
# plumb/http.py
from fastapi import FastAPI, Depends, HTTPException, Query, Path
from typing import Annotated

from plumb._http_deps import StoragePool, get_pool, get_pool_lifespan
from plumb._http_schemas import (
    HealthOut, RunListOut, RunDetailOut, ExampleListOut, StatsOut, ErrorOut,
)
from plumb._http_stats import compute_task_stats

app = FastAPI(
    title="plumb",
    version=plumb.__version__,
    description="plumb v1 read-only HTTP service (loopback only).",
    lifespan=get_pool_lifespan,                 # opens/closes the pool
    # docs_url, redoc_url, openapi_url stay at FastAPI defaults — enabled
)
```

Single FastAPI app, no sub-routers (small enough to inline). All routes are synchronous — SQLite I/O is cheap on loopback and `uvicorn` runs sync handlers in a worker thread by default.

### 3.3 Endpoint method signatures

#### `GET /health`

```python
@app.get("/health", response_model=HealthOut)
def health() -> HealthOut:
    return HealthOut(status="ok")
```

No DB access. Always returns 200.

#### `GET /runs`

```python
@app.get("/runs", response_model=RunListOut)
def list_runs(
    since:    Annotated[str | None, Query(description="ISO-8601 datetime or relative (7d, 2w, 1h)")] = None,
    task_id:  Annotated[str | None, Query(description="Filter to a single task_id")] = None,
    kind:     Annotated[str | None, Query(pattern="^(offline|online)$")] = None,
    limit:    Annotated[int, Query(ge=1, le=500)] = 100,
    offset:   Annotated[int, Query(ge=0)] = 0,
    pool:     Annotated[StoragePool, Depends(get_pool)] = ...,
) -> RunListOut: ...
```

Behavior: parses `since` via the same `parse_since` helper used by the CLI. Calls `StorageReader.list_runs_with_counts_paged(...)` (new — see §3.5). Returns `RunListOut(items=[...], total=<int>, limit=<int>, offset=<int>)`.

Pagination semantics: `limit` defaults to 100, hard-capped at 500; `offset` ≥ 0. `total` is a separate `COUNT(*)` query against the same WHERE clause (executed inside the same connection lease — so under WAL it sees the same snapshot for both queries).

#### `GET /runs/{run_id}`

```python
@app.get("/runs/{run_id}", response_model=RunDetailOut, responses={404: {"model": ErrorOut}})
def get_run(
    run_id: Annotated[str, Path(min_length=32, max_length=32, pattern="^[0-9a-f]{32}$")],
    pool:   Annotated[StoragePool, Depends(get_pool)],
) -> RunDetailOut: ...
```

Behavior: `pool.get_run(run_id)` → 404 if `None`. Then `pool.get_spans_for_run(run_id)` and `pool.get_scores_for_run(run_id)`. Spans returned in `(parent_span_id IS NULL DESC, parent_span_id, span_id)` order, building a flat list — clients reconstruct the tree from `parent_span_id`. Hashes (`input_hash`, `output_hash`) are returned as 64-char hex strings; **blob bodies are NOT inlined**.

Path-param hex32 validation rejects bad IDs with HTTP 422 before any DB access.

#### `GET /examples`

```python
@app.get("/examples", response_model=ExampleListOut)
def list_examples(
    task_id: Annotated[str | None, Query()] = None,
    active:  Annotated[bool | None, Query()] = None,
    pool:    Annotated[StoragePool, Depends(get_pool)] = ...,
) -> ExampleListOut: ...
```

Behavior: thin wrapper over `pool.list_examples(task_id=..., active=...)`. No pagination in v1 — examples table is bounded (200-task regression set; few thousand rows max). Returns `ExampleListOut(items=[...])`.

#### `GET /stats/task/{task_id}`

```python
@app.get("/stats/task/{task_id}", response_model=StatsOut, responses={404: {"model": ErrorOut}})
def get_task_stats(
    task_id: Annotated[str, Path(min_length=1, max_length=255)],
    since:   Annotated[str | None, Query()] = None,
    pool:    Annotated[StoragePool, Depends(get_pool)] = ...,
) -> StatsOut: ...
```

Behavior: aggregates the **v1 ten-metric cut** (PRD §4 / SDD "v1 metric cut") for the task. Returns 404 only if the task has zero runs in the window. See §6 for the aggregation algorithm.

### 3.4 Response schemas (Pydantic v2)

```python
# plumb/_http_schemas.py
from pydantic import BaseModel, ConfigDict
from datetime import datetime
from typing import Literal


class HealthOut(BaseModel):
    status: Literal["ok"]


class ErrorOut(BaseModel):
    error_type: str
    detail: str


class RunOut(BaseModel):
    run_id: str
    task_id: str
    kind: Literal["offline", "online"]
    status: Literal["pending", "success", "failure", "aborted", "stalled"]
    start_ts: datetime
    end_ts: datetime | None
    parent_run_id: str | None
    orchestrator_model: str | None
    sub_agent_model: str | None
    git_sha: str | None
    tokens_in: int | None
    tokens_out: int | None
    dollar_cost: float | None
    error_type: str | None
    duration_ms: int | None  # computed: (end_ts - start_ts).total_seconds() * 1000


class RunSummaryOut(RunOut):
    span_count: int
    score_count: int


class SpanOut(BaseModel):
    span_id: str
    run_id: str
    parent_span_id: str | None
    kind: Literal["llm", "tool", "subagent", "handoff", "plan", "verify"]
    name: str
    input_hash: str | None  # 64-char hex; blob NOT inlined
    output_hash: str | None
    tokens: int | None
    latency_ms: int | None
    status: Literal["success", "failure", "aborted"] | None
    error_type: str | None


class ScoreOut(BaseModel):
    score_id: str
    run_id: str
    span_id: str | None
    metric_name: str
    scorer: Literal["deterministic", "judge", "human", "user_signal"]
    scorer_version: str
    value_numeric: float | None
    value_label: str | None
    scored_at: datetime


class ExampleOut(BaseModel):
    example_id: str
    task_id: str
    inputs_hash: str
    expected_output_hash: str | None
    rubric: str | None
    source: Literal["synthetic", "production_promotion", "human_authored"]
    origin_run_id: str | None
    active: bool
    created_at: datetime


class RunListOut(BaseModel):
    items: list[RunSummaryOut]
    total: int
    limit: int
    offset: int


class ExampleListOut(BaseModel):
    items: list[ExampleOut]


class RunDetailOut(BaseModel):
    run: RunOut
    spans: list[SpanOut]
    scores: list[ScoreOut]


class MetricStatOut(BaseModel):
    """One row of the ten-metric stats block. NULL fields when no data."""
    metric_name: str
    n: int
    value_mean: float | None
    value_p50: float | None
    value_p95: float | None
    pass_rate: float | None       # for binary metrics (value_label-based)
    by_scorer: dict[str, int]


class StatsOut(BaseModel):
    task_id: str
    since: datetime | None
    run_count: int
    success_rate: float | None
    intervention_rate: float | None
    latency_ms_p50: float | None
    latency_ms_p95: float | None
    dollar_cost_total: float | None
    tokens_in_total: int | None
    tokens_out_total: int | None
    tokens_per_resolved_task: float | None
    metrics: list[MetricStatOut]
```

All models have `model_config = ConfigDict(extra="forbid")` so accidental field additions are caught in tests.

### 3.5 `StorageReader` extensions

Two new methods on `StorageReader` (Protocol) + `SQLiteStorageAdapter` (impl):

```python
class StorageReader(Protocol):
    def list_runs_with_counts_paged(
        self, *, since=None, task_id=None, kind=None,
        limit=100, offset=0,
    ) -> tuple[list["RunSummary"], int]: ...

    def aggregate_runs_for_task(
        self, task_id: str, *, since=None,
    ) -> "TaskRunAggregate": ...

    def aggregate_scores_for_task(
        self, task_id: str, *, since=None,
    ) -> list["ScoreAggregateRow"]: ...
```

`TaskRunAggregate` and `ScoreAggregateRow` (in `plumb/adapters/storage_sqlite.py` alongside `RunSummary`):

```python
@dataclass(frozen=True, slots=True)
class TaskRunAggregate:
    task_id: str
    run_count: int
    success_count: int
    failure_count: int
    aborted_count: int
    stalled_count: int
    latency_ms_values: list[float]  # for percentile compute outside SQL (small N)
    dollar_cost_total: float | None
    tokens_in_total: int | None
    tokens_out_total: int | None
    successful_tokens_total: int | None  # for tokens_per_resolved_task


@dataclass(frozen=True, slots=True)
class ScoreAggregateRow:
    metric_name: str
    scorer: str
    value_numeric_list: list[float]
    value_label_list: list[str]
```

Rationale: percentile calculation in SQLite-3 doesn't have a built-in (no PERCENTILE_DISC). Pulling latency values out and computing in Python is fine at v1's "30+ runs" scale.

### 3.6 Blob access policy

`/runs/{run_id}` returns `input_hash`/`output_hash` as 64-char hex strings, never inlines blob content. Rationale:

- Keeps response sizes bounded (a single LLM call may have a 100KB input blob).
- Loopback-only deployment means clients can read `$PLUMB_DATA_DIR/blobs/<sha[:2]>/<sha[2:]>` directly from disk.
- A future `GET /blobs/{hash}` endpoint can be added in v1.1 without breaking compatibility.

`$PLUMB_DATA_DIR` is **not** exposed via the API (NFR-Sec-7 — no filesystem absolute paths in responses).

### 3.7 Storage pool

A small connection pool with semaphore-bounded concurrency. Pool size **4** matches the most-common SQLite-WAL guidance: WAL allows many concurrent readers but locking still serializes within a single connection.

```python
# plumb/_http_deps.py
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

_POOL_SIZE = 4


class StoragePool:
    """Bounded pool of SQLiteStorageAdapter instances, async-safe."""

    def __init__(self, db_path: Path, pool_size: int = _POOL_SIZE) -> None:
        self._adapters = [
            SQLiteStorageAdapter(db_path, clock=_RealClock())
            for _ in range(pool_size)
        ]
        self._semaphore = asyncio.Semaphore(pool_size)
        self._idx = 0
        self._idx_lock = asyncio.Lock()

    async def acquire(self) -> SQLiteStorageAdapter:
        await self._semaphore.acquire()
        async with self._idx_lock:
            adapter = self._adapters[self._idx % len(self._adapters)]
            self._idx += 1
        return adapter

    def release(self) -> None:
        self._semaphore.release()

    def close(self) -> None:
        for a in self._adapters:
            a.close()


@asynccontextmanager
async def get_pool_lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    db_path = ensure_data_dir(settings) / "plumb.db"
    pool = StoragePool(db_path)
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


def get_pool(request: Request) -> StoragePool:
    return request.app.state.pool
```

Routes use `get_pool` as a `Depends` and acquire/release inside a try/finally.

### 3.8 Pending-run filter

By default, `GET /runs` and `GET /stats` **include** runs with `status='pending'` because they may legitimately be open (in-progress). The `since` filter alone determines staleness. The `_sweep_stalled_runs` migration in `SQLiteStorageAdapter.__init__` (FR-EDGE-2) re-classifies long-pending runs as `stalled` on next adapter open — which happens at HTTP-service startup (because the pool opens adapters fresh).

---

## 4. API Specifications

### 4.1 Endpoint inventory


| Method | Path                    | Status codes  | Notes                               |
| ------ | ----------------------- | ------------- | ----------------------------------- |
| GET    | `/health`               | 200           | Liveness; never errors              |
| GET    | `/runs`                 | 200, 422      | Pagination via `limit`+`offset`     |
| GET    | `/runs/{run_id}`        | 200, 404, 422 | 422 on bad hex32; 404 on unknown ID |
| GET    | `/examples`             | 200, 422      | No pagination                       |
| GET    | `/stats/task/{task_id}` | 200, 404, 422 | 404 when zero runs match the window |
| GET    | `/openapi.json`         | 200           | FastAPI auto                        |
| GET    | `/docs`                 | 200           | Swagger UI auto — enabled           |
| GET    | `/redoc`                | 200           | ReDoc auto                          |


### 4.2 Example request / response

**Request:**

```
GET /runs?since=7d&task_id=atlas.stage5.codegen&kind=online&limit=50&offset=0
```

**Response (200):**

```json
{
  "items": [
    {
      "run_id": "abc123...",
      "task_id": "atlas.stage5.codegen",
      "kind": "online",
      "status": "success",
      "start_ts": "2026-05-01T12:34:56+00:00",
      "end_ts": "2026-05-01T12:35:09+00:00",
      "parent_run_id": null,
      "orchestrator_model": "cursor/claude-sonnet-4.6",
      "sub_agent_model": null,
      "git_sha": "deadbeef",
      "tokens_in": 1234,
      "tokens_out": 567,
      "dollar_cost": 0.0123,
      "error_type": null,
      "duration_ms": 13000,
      "span_count": 7,
      "score_count": 2
    }
  ],
  "total": 142,
  "limit": 50,
  "offset": 0
}
```

### 4.3 Error envelope

All non-422 errors use:

```json
{
  "error_type": "not_found",
  "detail": "<sanitized human-readable message>"
}
```

Where `error_type` is one of: `not_found`, `plumb_internal_error`, `validation_error`, `service_busy`. 422 responses use FastAPI's default validation envelope.

### 4.4 Authentication / rate limiting

**None.** Loopback-only, single-user (TRD §5.3 Assumption 3). No `Authorization` header is read.

### 4.5 Versioning

The HTTP surface is unversioned in v1 (no `/v1/` prefix). API version exposed via `/openapi.json` comes from `plumb.__version__`.

---

## 5. Database Design

**No new tables, no new indexes, no migrations.** This slice is read-only. Existing v1 schema (TRD §7.1) and indexes are sufficient:

- `idx_runs_task_start` covers `WHERE task_id=? AND start_ts >= ?` — used by `/runs?task_id=&since=` and `/stats/task/{id}`.
- `idx_runs_kind_start` covers `WHERE kind=? AND start_ts >= ?` — used by `/runs?kind=&since=`.
- `idx_examples_task_active` covers `WHERE task_id=? AND active=?` — used by `/examples`.

### 5.1 Data access patterns


| Route              | SQL                                                                         |
| ------------------ | --------------------------------------------------------------------------- |
| `/runs`            | One `SELECT ... LIMIT ? OFFSET ?` + one `SELECT COUNT(*) ...` (same WHERE)  |
| `/runs/{id}`       | Three queries: runs, spans, scores                                          |
| `/examples`        | One `SELECT * FROM examples WHERE [task_id=? AND] [active=?]`               |
| `/stats/task/{id}` | Two queries: run-level aggregates + scored metrics grouped by `metric_name` |


All bindings are parameterized (NFR-Sec-3). No new `noqa: S608` suppressions added.

### 5.2 Migration strategy

None required. Schema unchanged.

---

## 6. Algorithm & Logic Design

### 6.1 `/stats/task/{task_id}` aggregation — full ten-metric cut

Pseudocode:

```
def compute_task_stats(reader, task_id, since) -> StatsOut:
    # 1. Run-level aggregates from `runs` table only
    agg = reader.aggregate_runs_for_task(task_id, since=since)
    if agg.run_count == 0:
        raise NotFoundError(f"No runs for task {task_id} since {since}")

    success_rate = (
        agg.success_count / (agg.success_count + agg.failure_count)
        if (agg.success_count + agg.failure_count) > 0 else None
    )

    p50 = percentile(agg.latency_ms_values, 0.50) if agg.latency_ms_values else None
    p95 = percentile(agg.latency_ms_values, 0.95) if agg.latency_ms_values else None

    tokens_per_resolved = (
        agg.successful_tokens_total / agg.success_count
        if agg.success_count > 0 and agg.successful_tokens_total is not None else None
    )

    # 2. Score-level aggregates from `scores` joined on the in-window run set
    score_rows = reader.aggregate_scores_for_task(task_id, since=since)

    metrics: list[MetricStatOut] = []
    intervention_rate: float | None = None
    for row in score_rows:
        if row.metric_name == "intervention" and row.scorer == "user_signal":
            intervened = sum(1 for v in row.value_label_list if v in {"true", "intervened"})
            intervention_rate = intervened / agg.run_count

        n = len(row.value_numeric_list) + len(row.value_label_list)
        v_mean = mean(row.value_numeric_list) if row.value_numeric_list else None
        v_p50 = percentile(row.value_numeric_list, 0.50) if row.value_numeric_list else None
        v_p95 = percentile(row.value_numeric_list, 0.95) if row.value_numeric_list else None

        pass_count = sum(1 for v in row.value_label_list if v == "pass")
        total_label = len(row.value_label_list)
        pass_rate = (pass_count / total_label) if total_label > 0 else None

        metrics.append(MetricStatOut(
            metric_name=row.metric_name, n=n,
            value_mean=v_mean, value_p50=v_p50, value_p95=v_p95,
            pass_rate=pass_rate, by_scorer={row.scorer: n},
        ))

    return StatsOut(
        task_id=task_id, since=since,
        run_count=agg.run_count,
        success_rate=success_rate,
        intervention_rate=intervention_rate,
        latency_ms_p50=p50, latency_ms_p95=p95,
        dollar_cost_total=agg.dollar_cost_total,
        tokens_in_total=agg.tokens_in_total,
        tokens_out_total=agg.tokens_out_total,
        tokens_per_resolved_task=tokens_per_resolved,
        metrics=metrics,
    )
```

Percentile algorithm: nearest-rank (`ceil(p * n)` index into sorted list) — avoids the linear-interpolation ambiguity in NumPy and matches SQL `PERCENTILE_DISC`. Pure-Python; no NumPy dep.

### 6.2 v1 ten-metric → endpoint field mapping


| Metric                   | Source                                                               | Endpoint field                  |
| ------------------------ | -------------------------------------------------------------------- | ------------------------------- |
| Task completion (binary) | `runs.status`                                                        | `success_rate`                  |
| End-to-end latency       | `runs.start_ts/end_ts`                                               | `latency_ms_p50/p95`            |
| Dollar cost              | `runs.dollar_cost`                                                   | `dollar_cost_total`             |
| Tokens-per-resolved-task | `runs.tokens_in/out` filtered by status=success                      | `tokens_per_resolved_task`      |
| Tool call validity       | `scores` where `metric_name='tool_call_validity'`                    | `metrics[].pass_rate`           |
| Tool arg hallucination   | `scores` where `metric_name='tool_arg_hallucination'`                | `metrics[].pass_rate`           |
| Routing top-1            | `scores` where `metric_name='routing_top1'`                          | `metrics[].pass_rate`           |
| Handoff round-trip       | `scores` where `metric_name='handoff_roundtrip'`                     | `metrics[].pass_rate`           |
| Intervention rate        | `scores` where `metric_name='intervention'` & `scorer='user_signal'` | `intervention_rate` (top-level) |
| pass^3                   | `scores` where `metric_name='pass_3'`                                | `metrics[].pass_rate`           |


Metrics with zero rows in the window appear in `metrics` with `n=0` and all values `None`.

### 6.3 `since` parsing

Reuse `plumb._time_utils.parse_since`. Supports `Nd`, `Nw`, `Nh`, `Nm`, ISO-8601. Validation errors return HTTP 422 (caught at the route boundary and re-raised as `HTTPException(422, ...)`).

### 6.4 Pagination logic

```
limit  = max(1, min(limit, 500))   # FastAPI Query(ge=1, le=500) handles this
offset = max(0, offset)            # FastAPI Query(ge=0)
total  = SELECT COUNT(*) FROM runs <where>
items  = SELECT ... FROM runs <where> ORDER BY start_ts DESC LIMIT ? OFFSET ?
```

Both queries execute on the same connection within the same dependency-injected lease, so under WAL they observe a consistent snapshot.

---

## 7. Error Handling & Edge Cases

### 7.1 Error matrix


| Trigger                                        | HTTP code | Body                                                                       | Notes                                        |
| ---------------------------------------------- | --------- | -------------------------------------------------------------------------- | -------------------------------------------- |
| Bad query/path param (type, regex, range)      | 422       | FastAPI default validation envelope                                        | Auto                                         |
| Unknown `run_id` in `/runs/{id}`               | 404       | `{"error_type": "not_found", "detail": "Run <prefix> not found"}`          | Includes only first 8 chars of ID            |
| Unknown task in `/stats/task/{id}` (zero runs) | 404       | `{"error_type": "not_found", "detail": "No runs for task '<task_id>'..."}` | task_id echoed verbatim                      |
| Bad `since` string                             | 422       | `{"error_type": "validation_error", "detail": "<msg from parse_since>"}`   | Catch `ValueError` at route boundary         |
| Bad `kind` value                               | 422       | FastAPI default                                                            | Auto via regex                               |
| `StorageError`                                 | 500       | `{"error_type": "plumb_internal_error", "detail": "Storage error"}`        | Stack trace logged at WARNING; never in body |
| Adapter timeout (busy lock > 5s)               | 503       | `{"error_type": "service_busy", "detail": "Database busy; retry"}`         | `sqlite3.OperationalError`                   |


### 7.2 Edge cases

- **Empty run list.** `GET /runs` with zero matches returns `{"items": [], "total": 0, ...}`, not 404. Lists never 404.
- **Spans with circular `parent_span_id`.** Schema FK cascade prevents this at write time; if it ever occurs, the route returns rows as-is — clients break the cycle on render.
- **Scores attached to span IDs not in the same run.** Schema permits via `span_id REFERENCES spans(span_id) ON DELETE SET NULL`. Returned as-is.
- **Run with `end_ts < start_ts`.** Domain entity validation prevents this at write; on read we trust the DB.
- `**since` in the future.** Returns empty list; not an error.
- `**limit=500, offset=10000` against a 100-row table.** Returns `{"items": [], "total": 100, ...}`.
- **Process kill during a request.** `uvicorn` aborts the connection; no partial DB writes (read-only).
- **Concurrent writes from `plumb.run` + reads from HTTP.** SQLite WAL handles writer/reader concurrency natively. Readers may observe a slightly stale snapshot — acceptable for an analytics surface.

### 7.3 Retry / fallback

- **No retries inside the service.** A transient SQLite lock returns 503 immediately and the client retries.
- **No request timeouts beyond uvicorn's defaults.**

### 7.4 Logging

- INFO: every request's method + path + status + duration_ms (uvicorn default access log).
- WARNING: any caught `StorageError`, with the SQL fragment + row count if available, **without** parameter values.
- DEBUG: per-route timings for `/stats` aggregation steps (gated by `PLUMB_LOG_LEVEL=DEBUG`).

Never logged: API keys (none read), SQL parameters where they could be sensitive.

---

> **Continued in `[v1-http-plan-part2.md](./v1-http-plan-part2.md)`** for §§8–13 (dependencies, security, testing, performance, implementation phases, pending decisions).


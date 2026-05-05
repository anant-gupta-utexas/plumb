# v1-http — Context, Decisions, Dependencies

**Feature:** v1 read-only HTTP service (`plumb/http.py` + helpers).
**Plan:** `[v1-http-plan.md](./v1-http-plan.md)` + `[v1-http-plan-part2.md](./v1-http-plan-part2.md)`
**Tasks:** `[v1-http-tasks.md](./v1-http-tasks.md)`

---

## Resolved decisions (TRS planning round, 2026-05-05)

These are decisions explicitly answered by the user during TRS planning. Each one closes a fork the plan would otherwise leave open.

### PD-1 — `/stats/task/{id}` aggregation scope: **full ten-metric cut**

- **Question:** What scope should `/stats` expose given the v1 ten-metric list (PRD §4 / SDD)?
- **Decision:** Aggregate the full ten-metric cut. Run-level metrics (latency p50/p95, dollar cost, tokens, completion rate, intervention rate) come from `runs`; scored metrics (tool call validity, tool arg hallucination, routing top-1, handoff round-trip, pass^3) come from `scores`. Metrics with no rows surface with `n=0` and `value_*=None` rather than being omitted, so the response shape is stable.
- **Rationale:** Highest TRD fidelity to FR-HTTP-2.4 ("aggregated metrics per the ten v1 cut"). Notebook users don't need to JOIN the four tables themselves.
- **Cost:** New `aggregate_scores_for_task` reader method; pseudocode in plan §6.1.
- **Revisit trigger:** If aggregation latency exceeds NFR-Perf-7 budget at scale, move scored-metric aggregation into a materialized view (deferred to v1.1).

### PD-2 — Pagination: `**limit` + `offset`**

- **Question:** Cursor vs offset vs limit-only.
- **Decision:** Simple `?limit=&offset=` with a hard cap of `limit ≤ 500`.
- **Rationale:** Matches the existing `StorageReader.list_runs(...)` signature shape; trivial to implement; familiar to notebook users. Cursor pagination is more robust under concurrent writes but adds plumbing the v1 single-user surface doesn't need.
- **Cost:** New `list_runs_with_counts_paged` returning `(rows, total)`. Two queries per request (SELECT + COUNT) on the same connection.
- **Revisit trigger:** If any user reports stale `total` counts or "missing rows" between pages under heavy concurrent writes, move to `(start_ts, run_id)` cursor pagination.

### PD-3 — `/runs/{id}` blob handling: **hashes only, no blob endpoint**

- **Question:** Inline blob bodies, or hashes only, or hashes + a `/blobs/{hash}` endpoint?
- **Decision:** Hashes only. No blob endpoint in v1. Clients open files from disk at `$PLUMB_DATA_DIR/blobs/<sha[:2]>/<sha[2:]>`.
- **Rationale:** Smallest v1 HTTP surface; loopback model means on-disk access is fine; bounded response size. A future `GET /blobs/{hash}` is a non-breaking add.
- **Cost:** Documentation note in `SpanOut` model docstring + getting-started guide.
- **Revisit trigger:** When a remote (non-loopback) deployment scenario appears, or when a notebook user reports filesystem access friction.

### PD-4 — OpenAPI docs: **enabled by default**

- **Question:** Enable Swagger UI / ReDoc / OpenAPI JSON?
- **Decision:** All three enabled at FastAPI defaults (`/docs`, `/redoc`, `/openapi.json`).
- **Rationale:** Matches FastAPI defaults; zero cost; helps notebook users explore endpoints. Loopback-only posture means there's no concern about exposing schema externally.
- **Cost:** None — defaults.
- **Revisit trigger:** None expected.

### PD-5 — Concurrency: **bounded connection pool (size 4)**

- **Question:** Single lazy adapter, per-request adapter, or pool?
- **Decision:** `StoragePool` of 4 `SQLiteStorageAdapter` instances guarded by an `asyncio.Semaphore`.
- **Rationale:** SQLite WAL allows concurrent readers but locks within a connection. Four readers exhausts useful parallelism for a single-user service while keeping startup cost bounded. Single-adapter would serialize all requests; per-request adapter pays open/close cost on every request.
- **Cost:** ~60 LOC in `plumb/_http_deps.py` plus pool tests.
- **Revisit trigger:** If a notebook fan-out generates >4 concurrent requests routinely, lift `_POOL_SIZE` (constant; no API change).

### PD-A — Single canonical row type for run summaries

- **Question:** Should the existing `plumb.adapters.storage_sqlite.RunSummary` (custom class with `__slots__`) be kept for the CLI while a separate `RunSummaryOut` is defined for HTTP, or should we unify?
- **Decision:** **Option 2** with a clean-architecture twist — unify, but place the canonical type in `plumb/core/entities.py` as a frozen dataclass `RunSummaryRow` (Pydantic-free, mypy-strict-clean). `RunSummaryOut` in `plumb/_http_schemas.py` is a thin Pydantic mirror with `model_validate(row)` for the HTTP `extra="forbid"` seam.
- **Rationale:** A single source of truth for the "run + counts" shape across CLI, adapter, and HTTP layers. Keeps `plumb/core/` free of Pydantic (NFR-Use-3) while preserving HTTP's strict validation. The CLI refactor is small (one consumer site in `plumb/cli.py::run_stats`).
- **Cost:** Add `RunSummaryRow` to entities; delete `plumb.adapters.storage_sqlite.RunSummary`; update the CLI consumer site; mirror in `_http_schemas.py`. All bundled into T2.1.
- **Revisit trigger:** If a future row-level field becomes performance-critical and Pydantic mirroring shows up in profiles, drop the mirror and have HTTP serialize the dataclass directly.

### PD-B — `/runs` `pending`-status filter default

- **Decision:** **Option 1** (recommendation) — include `status='pending'` runs by default. No filter logic added; clients can post-filter in v1.
- **Revisit trigger:** If notebook output is dominated by stale `pending` rows, add `?status=` query param in v1.1.

### PD-C — `/v1/` URL prefix

- **Decision:** **Option 1** (recommendation) — no `/v1/` prefix in v1. Matches TRD §3.6 verbatim.
- **Revisit trigger:** When v2 schema lands, add `/v2/` and keep unversioned routes as a v1 alias for one release.

### PD-D — `tokens_in`/`tokens_out` shape on `RunOut`

- **Decision:** **Option 1** (recommendation) — report `tokens_in` and `tokens_out` separately on `RunOut`, matching the `runs` table schema. The single-`tokens` quirk is span-only and tracked in `deferred-features.md`.
- **Revisit trigger:** None expected.

### PD-E — `/examples` pagination

- **Decision:** **Option 1** (recommendation) — no pagination in v1. Bounded table; TRD §3.6 lists no pagination params.
- **Revisit trigger:** If a user reports an examples table larger than ~5k rows, add `limit`+`offset` in v1.1.

---

## Key files to touch

### New files


| Path                                         | Purpose                                                                                                                                                                                            | LOC target |
| -------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------- |
| `plumb/_http_schemas.py`                     | Pydantic v2 response models (`HealthOut`, `RunOut`, `RunSummaryOut`, `SpanOut`, `ScoreOut`, `ExampleOut`, `RunDetailOut`, `RunListOut`, `ExampleListOut`, `MetricStatOut`, `StatsOut`, `ErrorOut`) | ~150       |
| `plumb/_http_deps.py`                        | `StoragePool`, lifespan, DI helpers                                                                                                                                                                | ~60        |
| `plumb/_http_stats.py`                       | `compute_task_stats` + percentile helpers                                                                                                                                                          | ~200       |
| `tests/http/conftest.py`                     | Seeded DB fixture, `FakeStoragePool`, `TestClient` factory                                                                                                                                         | ~120       |
| `tests/http/unit/test_schemas.py`            | Pydantic round-trip + `extra="forbid"` tests                                                                                                                                                       | ~80        |
| `tests/http/unit/test_pool.py`               | Pool acquire/release/close, idempotency                                                                                                                                                            | ~80        |
| `tests/http/unit/test_stats.py`              | `compute_task_stats` against `FakeReader`                                                                                                                                                          | ~150       |
| `tests/http/integration/test_health.py`      | `/health` smoke                                                                                                                                                                                    | ~30        |
| `tests/http/integration/test_runs.py`        | `/runs` happy + sad paths                                                                                                                                                                          | ~150       |
| `tests/http/integration/test_run_detail.py`  | `/runs/{id}` happy + sad paths                                                                                                                                                                     | ~120       |
| `tests/http/integration/test_examples.py`    | `/examples` filters                                                                                                                                                                                | ~60        |
| `tests/http/integration/test_stats.py`       | `/stats/task/{id}` end-to-end                                                                                                                                                                      | ~150       |
| `tests/http/integration/test_errors.py`      | Error handler behavior                                                                                                                                                                             | ~80        |
| `tests/http/property/test_runs_roundtrip.py` | Hypothesis round-trips                                                                                                                                                                             | ~80        |
| `tests/http/e2e/test_serve_smoke.py`         | Subprocess `plumb serve` smoke                                                                                                                                                                     | ~80        |
| `tests/http/perf/test_http_overhead.py`      | NFR-Perf-7 budget gate                                                                                                                                                                             | ~80        |
| `tests/adapters/test_list_runs_paged.py`     | Reader paging unit tests                                                                                                                                                                           | ~80        |
| `tests/adapters/test_aggregations.py`        | Reader aggregation unit tests                                                                                                                                                                      | ~120       |


### Modified files


| Path                               | Change                                                                                                                                                                                                                                  |
| ---------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `plumb/http.py`                    | Rewrite from 12-line stub to full app (≤ 250 LOC)                                                                                                                                                                                       |
| `plumb/core/entities.py`           | Add `RunSummaryRow` frozen dataclass (PD-A)                                                                                                                                                                                             |
| `plumb/core/ports.py`              | Add `list_runs_with_counts_paged`, `aggregate_runs_for_task`, `aggregate_scores_for_task` to `StorageReader`; replace `RunSummary` references with `RunSummaryRow` on the existing `list_runs_with_counts`                              |
| `plumb/adapters/storage_sqlite.py` | Implement the three new reader methods; add `TaskRunAggregate` + `ScoreAggregateRow` dataclasses; **delete** `RunSummary` class (PD-A); update `list_runs_with_counts` to return `list[RunSummaryRow]`                                  |
| `plumb/cli.py`                     | Update `run_stats` consumer to read from `RunSummaryRow` (PD-A; same field set, no behavior change)                                                                                                                                     |
| `docs/3_guides/getting_started.md` | Add curl examples per endpoint; link to loopback-security note                                                                                                                                                                          |


### Files explicitly NOT touched

- `plumb/cli.py::serve` command wiring — `plumb serve` already routes to `plumb.http:app`; no change to the `serve` command itself (only to `run_stats` per PD-A).
- `plumb/__init__.py` — no eager import of `plumb.http` (cold-import budget per NFR-Perf-6).
- `pyproject.toml` — no new deps.
- `plumb/api.py`, `plumb/autocapture/*` — write path; out of scope.

---

## Dependencies on prior slices

This slice consumes the following completed slices:


| Slice                                                   | What we consume                                                                                                                                        | Risk if it changes                                                                                                            |
| ------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------- |
| [v1-core-and-api](../../archive/v1-core-and-api/)       | `plumb.core.entities` (`Run`, `Span`, `Score`, `Example`, enums), `plumb.core.errors` (`NotFoundError`, `ValidationError`, `StorageError`)             | Low — entities are stable; new HTTP fields map onto entity fields                                                             |
| [v1-storage-adapter](../../archive/v1-storage-adapter/) | `SQLiteStorageAdapter` reader methods, schema indexes, WAL mode (note: this slice replaces the local `RunSummary` class with a core-level `RunSummaryRow` per PD-A)                                                                          | Medium — we extend the adapter; any breaking refactor of `_row_to_run` etc. ripples here                                      |
| [v1-cli](../../archive/v1-cli/)                         | `plumb._time_utils.parse_since`, `plumb.config.{Settings, ensure_data_dir}`, `_RealClock` (re-imported from `plumb.cli`), `plumb serve` command wiring | Low — `parse_since` and config are stable; we re-import `_RealClock` (consider extracting if both layers continue to need it) |
| [v1-autocapture](../../archive/v1-autocapture/)         | None directly — but the data we serve comes from autocapture writes                                                                                    | None                                                                                                                          |


This slice does NOT depend on:

- [v1-judge-adapters](../v1-judge-adapters/) — judges write `scores` rows but the HTTP layer reads them like any other score; no judge code is imported.
- The future `agentsview_attach` adapter — the HTTP layer reads from the DB regardless of write source.

---

## Integration points

### Upstream (callers of this slice)

- `**plumb serve` CLI command** — already invokes `uvicorn.run("plumb.http:app", host=..., port=...)`. No changes expected to `plumb/cli.py`.
- **Notebooks / ad-hoc dashboards** — call HTTP endpoints via `httpx`, `requests`, or browser fetch. Loopback only.
- `**/docs` Swagger UI** — interactive exploration for humans.

### Downstream (called by this slice)

- `**SQLiteStorageAdapter`** — instantiated 4× by the pool at startup; closed on shutdown. Each instance opens its own connection.
- `**Settings` / `ensure_data_dir**` — resolved once per app boot to find `plumb.db`.
- `**parse_since**` — invoked per request that supplies `?since=...`.

### Lifecycle

```
plumb serve --host 127.0.0.1 --port 8765
        │
        ▼
uvicorn.run("plumb.http:app", ...)
        │
        ▼
get_pool_lifespan(app)  ──── @asynccontextmanager
   ├─ startup: create StoragePool(db_path, size=4)
   │           ├─ open 4 × SQLiteStorageAdapter
   │           │  └─ each runs _bootstrap_schema + _sweep_stalled_runs
   │           └─ store on app.state.pool
   ├─ requests: routes Depend on get_pool → acquire → release
   └─ shutdown: pool.close() → close 4 adapters
```

---

## Risks & open questions

### Risks


| Risk                                                                         | Likelihood | Impact | Mitigation                                                                                                                                                                                             |
| ---------------------------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Pool initialization runs `_bootstrap_schema` four times redundantly          | Low        | Low    | DDL is `CREATE TABLE IF NOT EXISTS`; idempotent. Adds ~milliseconds to startup; acceptable.                                                                                                            |
| `_sweep_stalled_runs` fires four times at startup, racing on the same UPDATE | Medium     | Low    | The UPDATE is `WHERE status='pending' AND start_ts < ?` — second/third/fourth runs find zero rows. Worth verifying with a test that asserts only one logger.info line fires (or accepting up to four). |
| `aggregate_runs_for_task` returns latency_ms_values list that is large       | Low        | Medium | In-window filter + per-task scope keeps N small (hundreds, not millions). If a task accumulates >10k in-window runs, defer percentile to a SQL window function. Not a v1 concern.                      |
| `since` parsing differs between CLI and HTTP if `parse_since` is changed     | Low        | Medium | Single shared helper in `plumb/_time_utils.py`; covered by both CLI and HTTP tests.                                                                                                                    |
| `RunSummary` (custom class) vs `RunSummaryOut` (Pydantic) drift              | Medium     | Low    | PD-A explicitly tracks this. Mirror fields in tests; revisit at v1.1.                                                                                                                                  |
| FastAPI `app.state` is not type-checked                                      | Low        | Low    | Use a small typed accessor (`get_pool(request) -> StoragePool`) and `cast`. Documented in §3.7.                                                                                                        |
| Subprocess-based e2e test is flaky on CI                                     | Medium     | Low    | Use a free-port-finder helper; bound startup wait to 5s; skip on Windows.                                                                                                                              |


### Open questions

**None.** All five second-round decisions (PD-A through PD-E) are resolved above. Phase 1 can start without further input.

---

## Code review focus areas (for the eventual review)

When this slice goes to PR review, reviewers should pay particular attention to:

1. **No write paths.** Verify `git grep -nE "POST|PUT|DELETE|PATCH|app\.post|app\.put|app\.delete|app\.patch"` returns zero hits in `plumb/http.py`.
2. **Parameterized SQL only.** Any new SQL in `plumb/adapters/storage_sqlite.py` must use `?` bindings, no f-string interpolation of user values.
3. **Path leakage.** `/openapi.json` and 500 response bodies must not contain `$PLUMB_DATA_DIR` or any absolute path. Test `test_errors.py` should assert this.
4. **Stack-trace leakage.** 500 bodies must not include exception messages from `StorageError` — they go to the WARNING log, not the response.
5. **Pool lifecycle.** Lifespan must close all four adapters even if startup partially failed (try/finally inside lifespan).
6. `**run_id` regex.** The path-param regex must reject lengths 0, 31, 33, 64, and any non-hex characters before any DB call.
7. **Pydantic `extra="forbid"`.** All response models must reject unknown fields; tests should construct each model with an extra field and assert `ValidationError`.
8. `**interrogate` coverage.** `plumb/http.py` must hit ≥ 95% docstring coverage (existing TRD §10.2 gate).

---

## Acceptance recap (mapping to TRD)


| AC needed                            | TRD source           | Where tested                                                   |
| ------------------------------------ | -------------------- | -------------------------------------------------------------- |
| Loopback bind in default plumb serve | AC-SEC-2 (TRD §13.6) | Already covered in v1-cli tests; this slice doesn't regress    |
| `/health` returns `{"status":"ok"}`  | TRD §3.6 FR-HTTP-2   | `tests/http/integration/test_health.py`                        |
| All four read endpoints return JSON  | TRD FR-HTTP-3        | `tests/http/integration/`*                                     |
| No write verbs                       | TRD FR-HTTP-2        | `tests/http/integration/test_errors.py::test_no_write_methods` |
| Parameterized SQL                    | TRD NFR-Sec-3        | `ruff` rule `S608`; CI gate                                    |
| Docstring coverage                   | TRD NFR-Use-4        | `interrogate --fail-under 95 plumb/http.py`                    |


---

*End of context.*
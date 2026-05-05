# v1-http — Implementation Tasks

**Feature:** v1 read-only HTTP service (`plumb/http.py` + helpers).
**Plan:** [`v1-http-plan.md`](./v1-http-plan.md) + [`v1-http-plan-part2.md`](./v1-http-plan-part2.md)
**Context:** [`v1-http-context.md`](./v1-http-context.md)

**Status:** ⏳ Not started.

> Effort tags: S = ≤ 0.5d, M = 0.5–1d, L = 1–2d.

---

## Phase 1 — Schemas + Pool + Health passthrough

**Objective:** Ship the foundations (response models, pool, lifespan) with `/health` proven against the new architecture.

### T1.1 — Response models `[M]`

**Description:** Implement all Pydantic v2 models in `plumb/_http_schemas.py` per plan §3.4 with `extra="forbid"` configs and round-trip tests. Per PD-D, `RunOut` reports `tokens_in` and `tokens_out` separately.

**Acceptance Criteria:**

- [ ] Every model has `model_config = ConfigDict(extra="forbid")`.
- [ ] All field types match TRD §7.1 column types (datetimes are tz-aware; hashes are 64-char hex; IDs are 32-char hex).
- [ ] `RunOut` has separate `tokens_in` and `tokens_out` fields (PD-D Option 1) and a computed `duration_ms` field.
- [ ] All models documented with Google-style docstrings (interrogate-friendly).
- [ ] `mypy --strict plumb/_http_schemas.py` passes.
- [ ] Constructing any model with an unknown field raises `pydantic.ValidationError` (verified in `test_schemas.py`).

**Files:**

- `plumb/_http_schemas.py` — new
- `tests/http/unit/test_schemas.py` — new

**Dependencies:** none

**Tests:** Unit only.

---

### T1.2 — Storage pool + lifespan `[M]`

**Description:** Implement `StoragePool` and FastAPI lifespan per plan §3.7. Bound to `_POOL_SIZE = 4`. Settings-driven DB path resolution.

**Acceptance Criteria:**

- [ ] Pool opens 4 adapters at app startup, closes all 4 at shutdown (verified by counter or mock).
- [ ] `acquire()` blocks when 4 in flight; releases on `release()`.
- [ ] Idempotent close — calling `pool.close()` twice does not raise.
- [ ] `get_pool` dependency returns the same pool across requests (identity check).
- [ ] Schema bootstrap fires on each adapter (idempotent DDL); no crash.
- [ ] `_sweep_stalled_runs` fires at most once per adapter; aggregate log line count ≤ 4 (or 1 if guarded).
- [ ] Lifespan closes pool even if a route raises during a request (try/finally).

**Files:**

- `plumb/_http_deps.py` — new
- `tests/http/unit/test_pool.py` — new

**Dependencies:** T1.1

**Tests:** Unit + integration with `tmp_path`.

---

### T1.3 — Replace `http.py` stub with health-only app `[S]`

**Description:** Rewrite `plumb/http.py` to use lifespan + dependency injection, but only the `/health` route. Confirms wiring before adding read routes.

**Acceptance Criteria:**

- [ ] `GET /health` returns `{"status":"ok"}` with HTTP 200.
- [ ] `app.state.pool` is non-`None` after startup.
- [ ] `plumb serve` still works (CLI smoke test passes).
- [ ] `interrogate --fail-under 95 plumb/http.py` passes.
- [ ] `ruff check plumb/http.py` passes.

**Files:**

- `plumb/http.py` — rewrite
- `tests/http/integration/test_health.py` — new
- `tests/http/conftest.py` — new (TestClient + seeded DB factory)

**Dependencies:** T1.2

**Tests:** Integration via `TestClient`.

**Phase Deliverables:**

- App scaffold with pool + lifespan + health endpoint.
- CLI continues to work.
- `interrogate` passes on the new file.

---

## Phase 2 — `/runs` + `/runs/{run_id}` + `/examples`

**Objective:** Land the three read endpoints that map directly onto existing `StorageReader` methods.

### T2.1 — Migrate to `RunSummaryRow` + extend `StorageReader` with paged listing `[L]`

**Description:** Per PD-A, this task does two related things in one commit:

1. **Migrate** the existing local `plumb.adapters.storage_sqlite.RunSummary` class to a frozen dataclass `RunSummaryRow` in `plumb/core/entities.py` (Pydantic-free; mypy-strict-clean). Update the existing `list_runs_with_counts(...)` to return `list[RunSummaryRow]`. Update the CLI's `run_stats` consumer in `plumb/cli.py` to read from `RunSummaryRow` (same field set; no behavior change).
2. **Add** `list_runs_with_counts_paged(...) -> tuple[list[RunSummaryRow], int]` to the Protocol and `SQLiteStorageAdapter`. One SELECT + one COUNT, both parameterized.

**Acceptance Criteria:**

- [ ] `RunSummaryRow` frozen dataclass added to `plumb/core/entities.py` with all fields previously on `RunSummary` (and Google-style docstring).
- [ ] `plumb.adapters.storage_sqlite.RunSummary` class **deleted**.
- [ ] `list_runs_with_counts(...)` returns `list[RunSummaryRow]`.
- [ ] `plumb/cli.py::run_stats` updated to consume `RunSummaryRow`; `pytest tests/test_cli.py` (or equivalent) still green with no behavior change.
- [ ] Protocol method `list_runs_with_counts_paged` added to `plumb/core/ports.py` with full type hints.
- [ ] `SQLiteStorageAdapter.list_runs_with_counts_paged` implemented with parameterized SQL; `noqa: S608` only on static-string clauses.
- [ ] Returns `(rows, total)` where `total` is the count matching the same WHERE.
- [ ] Hypothesis property test: for any (since, task_id, kind, limit, offset), `len(rows) <= limit` AND `len(rows) <= max(0, total - offset)`.
- [ ] `mypy --strict plumb/core/` still passes.
- [ ] `EXPLAIN QUERY PLAN` confirms `idx_runs_task_start` / `idx_runs_kind_start` are used when filters are set.

**Files:**

- `plumb/core/entities.py` — add `RunSummaryRow`
- `plumb/core/ports.py` — add `list_runs_with_counts_paged`; replace `RunSummary` references with `RunSummaryRow` on existing reader signature
- `plumb/adapters/storage_sqlite.py` — delete `RunSummary`; update `list_runs_with_counts` return type; implement `list_runs_with_counts_paged`
- `plumb/cli.py` — update `run_stats` consumer
- `tests/adapters/test_list_runs_paged.py` — new
- `tests/test_cli.py` (or wherever `run_stats` is tested) — patch any `RunSummary` references

**Dependencies:** T1.3

**Tests:** Unit + property; existing CLI tests must remain green after the consumer-site update.

---

### T2.2 — `GET /runs` `[M]`

**Description:** Implement `list_runs` route per plan §3.3. `since` parsing via `parse_since`; bad strings → 422. Per PD-B, `status='pending'` runs are included by default (no filter logic). The route maps `list[RunSummaryRow]` → `list[RunSummaryOut]` via `RunSummaryOut.model_validate(row)`.

**Acceptance Criteria:**

- [ ] Empty result set returns 200 with `items=[]`, `total=0`.
- [ ] `limit=0` and `limit=501` return 422.
- [ ] `kind=offline` filter works; `kind=foo` returns 422.
- [ ] `since=7d`, `since=2026-01-01`, ISO with TZ all work; `since=garbage` returns 422 with `error_type='validation_error'`.
- [ ] Returns `RunSummaryOut` items with `span_count` + `score_count` populated.
- [ ] `status='pending'` runs are present in results when matching other filters (PD-B).
- [ ] Pagination invariant: `len(items) <= limit`; `total` independent of `offset`.

**Files:**

- `plumb/http.py` — add route
- `tests/http/integration/test_runs.py` — new

**Dependencies:** T2.1

**Tests:** Integration via `TestClient`.

---

### T2.3 — `GET /runs/{run_id}` `[M]`

**Description:** Implement detail route per plan §3.3. Path-param hex32 regex enforced via `Path(pattern=...)`.

**Acceptance Criteria:**

- [ ] Bad hex (31/33 chars, non-hex) → 422 before any DB call (verify via mock or counter).
- [ ] Valid hex but unknown ID → 404 with `error_type='not_found'`.
- [ ] Happy path returns full `RunDetailOut` with spans ordered (root spans first, then by `parent_span_id`, then by `span_id`).
- [ ] Hashes returned as 64-char hex; **never** the blob body.
- [ ] Run with zero spans returns `spans=[]`, not an error (FR-EDGE-3).
- [ ] Run with zero scores returns `scores=[]`.
- [ ] 404 detail string includes only first 8 chars of `run_id` (information minimization).

**Files:**

- `plumb/http.py` — add route
- `tests/http/integration/test_run_detail.py` — new

**Dependencies:** T1.3

**Tests:** Integration.

---

### T2.4 — `GET /examples` `[S]`

**Description:** Implement examples list route per plan §3.3. No pagination per PD-E (Option 1).

**Acceptance Criteria:**

- [ ] Filtering by `task_id` works.
- [ ] Filtering by `active=true|false` works (FastAPI converts query string to bool).
- [ ] Both filters combined work.
- [ ] Returns `ExampleListOut` with full row set (no truncation in v1).

**Files:**

- `plumb/http.py` — add route
- `tests/http/integration/test_examples.py` — new

**Dependencies:** T1.3

**Tests:** Integration.

**Phase Deliverables:**

- Three of four read endpoints live.
- Only `/stats` remaining.

---

## Phase 3 — `/stats/task/{task_id}` + ten-metric aggregation

**Objective:** Land the aggregation endpoint matching the v1 metric cut.

### T3.1 — Extend `StorageReader` with task aggregations `[L]`

**Description:** Add `aggregate_runs_for_task` and `aggregate_scores_for_task` methods. Pure SQL (no Python aggregation in adapter).

**Acceptance Criteria:**

- [ ] `aggregate_runs_for_task` returns a single `TaskRunAggregate` dataclass with all run-level counts/sums + `latency_ms_values` list.
- [ ] `aggregate_scores_for_task` returns score rows grouped by `(metric_name, scorer)` with value lists.
- [ ] Both methods use parameterized bindings; no f-string interpolation of user values.
- [ ] `EXPLAIN QUERY PLAN` confirms `idx_runs_task_start` and `idx_scores_run_metric` are used.
- [ ] Empty task returns aggregate with `run_count=0` and empty value lists.
- [ ] Hypothesis property test: aggregate counts equal raw row counts on randomly generated runs.

**Files:**

- `plumb/core/ports.py` — extend Protocol
- `plumb/adapters/storage_sqlite.py` — add `TaskRunAggregate`, `ScoreAggregateRow`, impls
- `tests/adapters/test_aggregations.py` — new

**Dependencies:** T2.1

**Tests:** Unit + property.

---

### T3.2 — Pure aggregation in `_http_stats` `[M]`

**Description:** Implement `compute_task_stats(reader, task_id, since)` per plan §6.1. Pure function over the reader.

**Acceptance Criteria:**

- [ ] Empty task raises `NotFoundError`.
- [ ] `success_rate` correctly excludes `pending` and `aborted` from the denominator (only `success`+`failure`).
- [ ] `intervention_rate` is `None` when no `user_signal` scores exist; populated otherwise.
- [ ] `tokens_per_resolved_task` is `None` when `success_count=0`.
- [ ] Percentile helper matches `numpy.percentile(... interpolation='nearest')` output on small inputs (Hypothesis-checked).
- [ ] Metrics with no rows show `n=0, value_*=None, pass_rate=None` rather than being omitted.
- [ ] All ten v1-cut metrics appear in the response (top-level fields or `metrics[]`).

**Files:**

- `plumb/_http_stats.py` — new
- `tests/http/unit/test_stats.py` — new

**Dependencies:** T3.1

**Tests:** Unit (FakeReader-driven) + property (Hypothesis on percentile).

---

### T3.3 — `GET /stats/task/{task_id}` `[S]`

**Description:** Wire the route, map `NotFoundError` to 404.

**Acceptance Criteria:**

- [ ] Happy path returns full `StatsOut`.
- [ ] Zero runs (after `since` filter) → 404 with `error_type='not_found'`.
- [ ] Bad `since` → 422 with `error_type='validation_error'`.
- [ ] All ten v1-cut metrics appear in response (top-level fields or `metrics[]`).
- [ ] `task_id` echoed verbatim in response body.

**Files:**

- `plumb/http.py` — add route
- `tests/http/integration/test_stats.py` — new

**Dependencies:** T3.2

**Tests:** Integration with seed fixtures.

**Phase Deliverables:**

- Full FR-HTTP-2 surface live.
- Smoke against the four-table fixture passes.

---

## Phase 4 — Hardening + Docs + E2E

**Objective:** Close out CI gates, error handling consistency, OpenAPI polish, and the e2e smoke.

### T4.1 — Error handler unification `[S]`

**Description:** Add app-level exception handlers for `NotFoundError`, `ValidationError`, `StorageError` → JSON envelopes per plan §7.1.

**Acceptance Criteria:**

- [ ] All routes raise domain exceptions; handlers convert to HTTP responses.
- [ ] 500 responses never leak stack traces or absolute paths (regex-checked).
- [ ] 503 fires on `sqlite3.OperationalError("database is locked")` (verified via fault injection / monkeypatch).
- [ ] 422 envelope (FastAPI default) preserved — not replaced.
- [ ] Test asserts `git grep -nE "POST|PUT|DELETE|PATCH" plumb/http.py` returns zero hits.

**Files:**

- `plumb/http.py` — add handlers
- `tests/http/integration/test_errors.py` — new

**Dependencies:** T3.3

**Tests:** Integration.

---

### T4.2 — OpenAPI tagging + descriptions `[S]`

**Description:** Tag routes (`runs`, `examples`, `stats`, `health`); add summary + description; ensure `/openapi.json` validates as OpenAPI 3.1.

**Acceptance Criteria:**

- [ ] `GET /openapi.json` returns 200 and parses as valid OpenAPI 3.1 (verified via `openapi-spec-validator` in test).
- [ ] `GET /docs` (Swagger UI) loads and lists every endpoint.
- [ ] All endpoints have a one-line `summary` and a description with at least one example.
- [ ] `interrogate --fail-under 95 plumb/http.py` passes.
- [ ] OpenAPI `info.version` matches `plumb.__version__`.

**Files:**

- `plumb/http.py` — annotate

**Dependencies:** T4.1

**Tests:** Integration.

---

### T4.3 — E2E smoke against `plumb serve` `[M]`

**Description:** Spawn `plumb serve --port <free>` in a subprocess; hit `/health`, `/runs`, `/runs/{id}`, `/examples`, `/stats/task/{id}` via `httpx.Client`; assert 200s and shape.

**Acceptance Criteria:**

- [ ] Subprocess starts within 5s (uses a free-port-finder helper).
- [ ] All five endpoints return 200 against a pre-seeded DB.
- [ ] Subprocess terminates cleanly on Ctrl-C / SIGTERM.
- [ ] Test is skipped on Windows (signal handling differs).
- [ ] Test is marked `@pytest.mark.e2e` and skipped by default unless explicitly invoked.

**Files:**

- `tests/http/e2e/test_serve_smoke.py` — new

**Dependencies:** T4.2

**Tests:** E2E (single test).

---

### T4.4 — Performance gate `[S]`

**Description:** Add `tests/http/perf/test_http_overhead.py` with seeded 10k-run DB; assert NFR-Perf-7 budgets from plan §11.2.

**Acceptance Criteria:**

- [ ] All five budgets met on CI runner with 2× headroom locally.
- [ ] Test marked `@pytest.mark.perf`; runs only under explicit `pytest tests/http/perf/`.
- [ ] Budget table from plan §11.2 reproduced as inline test data.

**Files:**

- `tests/http/perf/test_http_overhead.py` — new

**Dependencies:** T4.3

**Tests:** Perf (gated).

---

### T4.5 — Docs + getting-started update `[S]`

**Description:** Update `docs/3_guides/getting_started.md` to mention the HTTP surface, the four endpoints, and the loopback-only posture. Add a curl example per endpoint.

**Acceptance Criteria:**

- [ ] At least one curl example per route in the getting-started guide (`/health`, `/runs`, `/runs/{id}`, `/examples`, `/stats/task/{id}`).
- [ ] Loopback-only security note linked from the guide to TRD §5.3 Assumption 3.
- [ ] Blob-resolution path documented (`$PLUMB_DATA_DIR/blobs/<sha[:2]>/<sha[2:]>`).
- [ ] No stale references to the old 12-line stub.
- [ ] If `core_concepts.md` exists and references HTTP, it is also updated; otherwise a follow-up note is added to `dev/active/v1-http/v1-http-context.md`.

**Files:**

- `docs/3_guides/getting_started.md` — extend

**Dependencies:** T4.4

**Tests:** Manual review.

**Phase Deliverables:**

- CI green; `interrogate ≥ 95%` on `plumb/http.py`.
- E2E + perf tests pass.
- Docs updated.

---

## Final Definition of Done

This slice is "done" when ALL of the following hold:

- [ ] All Phase 1–4 tasks above checked off.
- [ ] `pytest` (full suite) passes locally and on CI.
- [ ] `pytest --cov=plumb --cov-fail-under=75` passes.
- [ ] `ruff check .` and `ruff format --check .` pass.
- [ ] `mypy --strict plumb/core/` passes.
- [ ] `interrogate --fail-under 95 plumb/api.py plumb/cli.py plumb/http.py` passes.
- [ ] `plumb serve` smoke from a fresh venv (`pip install -e .` + `plumb serve` + `curl 127.0.0.1:8765/health`) returns 200.
- [ ] All five PD-A through PD-E pending decisions either resolved or explicitly deferred to v1.1 in `deferred-features.md`.
- [ ] PR description references the relevant TRD IDs (FR-HTTP-1, FR-HTTP-2, FR-HTTP-3, NFR-Sec-3, NFR-Sec-4, NFR-Rel-1).
- [ ] `dev/active/v1-http/` moved to `dev/archive/v1-http/` after merge.

---

*End of tasks.*

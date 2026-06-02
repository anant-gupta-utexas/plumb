# TRS — `plumb/http.py` (v1 HTTP Read Service Slice) — Part 2 of 2

> **Continuation of `[v1-http-plan.md](./v1-http-plan.md)`** (§§1–7). This file covers §§8–13.

---

## 8. Dependencies & Interfaces

### 8.1 Internal dependencies


| Module                                               | Purpose                                                                    |
| ---------------------------------------------------- | -------------------------------------------------------------------------- |
| `plumb.config.Settings` / `ensure_data_dir`          | Resolves `$PLUMB_DATA_DIR`                                                 |
| `plumb.adapters.storage_sqlite.SQLiteStorageAdapter` | Reader implementation                                                      |
| `plumb.core.ports.StorageReader`                     | Port surface (extended in this slice)                                      |
| `plumb.core.entities`                                | `Run`, `Span`, `Score`, `Example` for response mapping                     |
| `plumb._time_utils.parse_since`                      | `since` string parsing                                                     |
| `plumb.core.errors`                                  | `NotFoundError`, `ValidationError`, `StorageError` mapped to HTTP statuses |


### 8.2 External dependencies (already declared in `pyproject.toml`)


| Package          | Floor                             | New?                             |
| ---------------- | --------------------------------- | -------------------------------- |
| `fastapi`        | ≥ 0.115                           | already declared (TRD §5.4)      |
| `uvicorn`        | ≥ 0.30                            | already declared                 |
| `pydantic`       | ≥ 2.6                             | already declared                 |
| `pytest-asyncio` | latest                            | already in dev extras            |
| `httpx`          | (transitive via openai/anthropic) | needed for `TestClient` in tests |


No new dependencies introduced by this slice.

### 8.3 Integration points

- `plumb serve` (CLI) launches `uvicorn.run("plumb.http:app", ...)` — already wired.
- `plumb.__init__` does not import `plumb.http` (HTTP cold-import would balloon the cold-import budget per NFR-Perf-6). Importing `plumb.http` is opt-in.

---

## 9. Security Considerations

### 9.1 Threat model

Single-user loopback service. Attackers in scope: local processes on the same machine that can `connect(127.0.0.1, 8765)`. Out of scope: network-borne attackers (the bind config rules them out by default).

### 9.2 Controls


| Control                    | Implementation                                                                                     |
| -------------------------- | -------------------------------------------------------------------------------------------------- |
| Loopback-only default      | Enforced at `plumb serve` (CLI), not in the app — app is host-agnostic by design                   |
| No auth                    | Documented in `/docs` description + README; loopback model                                         |
| Parameterized SQL          | Inherited from `SQLiteStorageAdapter` (NFR-Sec-3)                                                  |
| Path injection             | `run_id` validated as 32-char hex; `task_id` is opaque, used only as a parameter binding           |
| No filesystem path leakage | `$PLUMB_DATA_DIR` never appears in response bodies; error envelopes omit paths                     |
| No secret leakage          | The HTTP layer reads no API keys; error logs omit query-param values where they could be sensitive |
| DoS via large `limit`      | Query param capped at 500                                                                          |
| DoS via deep span trees    | Span tree returned flat (clients reconstruct); no recursion server-side                            |
| CORS                       | Not configured. Browsers from another origin cannot call the API; this is intentional.             |
| Open ports                 | `plumb serve` warns when port is non-default or host is non-loopback (CLI slice)                   |


### 9.3 Explicit non-controls

- No rate limiting (single-user).
- No request signing.
- No audit log of who queried what (single-user).
- No PII redaction in response bodies — content lives in blob store under hashes; the HTTP layer never returns blob bodies.

---

## 10. Testing Strategy

### 10.1 Test pyramid


| Layer       | Scope                                                                                                                | Where                                    |
| ----------- | -------------------------------------------------------------------------------------------------------------------- | ---------------------------------------- |
| Unit        | `_http_schemas` model validation, `_http_stats.compute_task_stats` pure function with FakeReader, percentile helper  | `tests/http/unit/`                       |
| Integration | `TestClient(app)` + real `SQLiteStorageAdapter` against `tmp_path` DB; full request → response cycle for every route | `tests/http/integration/`                |
| Property    | Hypothesis-generated runs/spans/scores asserted to round-trip through `/runs/{id}` without losing fields             | `tests/http/property/`                   |
| E2E         | `plumb serve` started in a subprocess, exercised via `httpx.Client`                                                  | `tests/http/e2e/` (one test, smoke-only) |


### 10.2 Coverage targets

- `plumb/_http_schemas.py`: ≥ 95% (small file, mostly dataclass-style models).
- `plumb/_http_stats.py`: ≥ 90% (pure functions; fully unit-testable).
- `plumb/http.py`: ≥ 85% (route bodies; error branches covered via `TestClient`).
- `plumb/_http_deps.py`: ≥ 80% (pool acquire/release happy + sad paths).

### 10.3 Test data

- Reuse the `tmp_path` SQLite fixture from `tests/conftest.py` if present; otherwise add `tests/http/conftest.py::http_app` that builds a fresh DB with N=10 runs, M=30 spans, K=12 scores, 4 examples, deterministically seeded.
- `FakeStoragePool` for unit tests in `tests/http/unit/`.

### 10.4 Mocking policy

- **No HTTP mocks.** This slice IS the HTTP layer; we test it with FastAPI's `TestClient`.
- **Time:** `freezegun` for stable `start_ts`/`end_ts` assertions in fixtures.
- **No real `plumb serve` in unit/integration.** Only the e2e smoke spawns uvicorn.

### 10.5 Negative tests (mandatory)

- Bad `run_id` (31 chars, 33 chars, non-hex) → 422.
- Unknown `run_id` (valid hex32, no row) → 404.
- `kind=foo` → 422 (regex).
- `limit=0`, `limit=501`, `offset=-1` → 422.
- `since=garbage` → 422.
- `task_id` with zero runs → 404 on `/stats`, empty list on `/runs`.
- DB file missing on disk → 500.
- DB schema version mismatch → 500.

---

## 11. Performance Considerations

### 11.1 Expected load

Single-user notebook + ad-hoc dashboard. Realistic load ~1 req/s peak; the service must not collapse under a notebook that hammers `/runs?limit=500` in a loop.

### 11.2 Performance budget (NFR-Perf-7, locally derived)


| Endpoint           | DB shape                       | Target p95 |
| ------------------ | ------------------------------ | ---------- |
| `/health`          | none                           | ≤ 1 ms     |
| `/runs?limit=100`  | 10k runs, indexed              | ≤ 50 ms    |
| `/runs/{id}`       | run with 100 spans, 5 scores   | ≤ 30 ms    |
| `/examples`        | 200 examples                   | ≤ 20 ms    |
| `/stats/task/{id}` | 200 in-window runs, 600 scores | ≤ 100 ms   |


Measured by `tests/http/perf/test_http_overhead.py` (one test file, optional in CI; gated locally).

### 11.3 Optimization strategies

- **Reuse existing indexes.** No new indexes; query plans already covered by §5.
- **Single-connection lease per request.** Avoid open/close-per-query overhead; the pool keeps four hot connections.
- **No JSON middleware allocation surprises.** Pydantic v2 is fast; `model_dump_json` is used directly where possible.
- **No N+1.** `/runs` paginates with one SELECT + one COUNT; `/runs/{id}` uses three SELECTs (runs, spans, scores) — flat and bounded.

### 11.4 Caching

None in v1. SQLite reads are fast enough on local disk; adding a cache layer adds a staleness contract that is not worth the complexity for a single-user tool.

---

## 12. Implementation Phases

> Per-task acceptance criteria with checkboxes are in `[v1-http-tasks.md](./v1-http-tasks.md)`. The phase summary below names tasks, effort, and dependencies; tasks.md owns the AC checklist.

### Phase 1 — Schemas + Pool + Health passthrough

**Objective:** Ship the foundations (response models, pool, lifespan) with `/health` proven against the new architecture.

**Tasks:**

- **T1.1 — Response models** [Effort: M]. New `plumb/_http_schemas.py` per §3.4 with `extra="forbid"` configs. Dependencies: none.
- **T1.2 — Storage pool + lifespan** [Effort: M]. New `plumb/_http_deps.py` per §3.7. Dependencies: T1.1.
- **T1.3 — Replace `http.py` stub with health-only app** [Effort: S]. Rewrite `plumb/http.py` to use lifespan + DI but only `/health`. Dependencies: T1.2.

**Phase Deliverables:** App scaffold with pool + lifespan + health endpoint. CLI continues to work. `interrogate` passes on the new file.

### Phase 2 — `/runs` + `/runs/{run_id}` + `/examples`

**Objective:** Land the three read endpoints that map directly onto existing `StorageReader` methods.

**Tasks:**

- **T2.1 — Extend `StorageReader` with paged listing** [Effort: M]. Add `list_runs_with_counts_paged` to Protocol + adapter. Dependencies: T1.3.
- **T2.2 — `GET /runs`** [Effort: M]. Implement route per §3.3. Dependencies: T2.1.
- **T2.3 — `GET /runs/{run_id}`** [Effort: M]. Implement detail route per §3.3. Dependencies: T1.3.
- **T2.4 — `GET /examples`** [Effort: S]. Implement examples list route. Dependencies: T1.3.

**Phase Deliverables:** Three of four read endpoints live; only `/stats` remaining.

### Phase 3 — `/stats/task/{task_id}` + ten-metric aggregation

**Objective:** Land the aggregation endpoint matching the v1 metric cut.

**Tasks:**

- **T3.1 — Extend `StorageReader` with task aggregations** [Effort: L]. Add `aggregate_runs_for_task` + `aggregate_scores_for_task`. Dependencies: T2.1.
- **T3.2 — Pure aggregation in `_http_stats`** [Effort: M]. Implement `compute_task_stats` per §6.1. Dependencies: T3.1.
- **T3.3 — `GET /stats/task/{task_id}`** [Effort: S]. Wire the route, map `NotFoundError` to 404. Dependencies: T3.2.

**Phase Deliverables:** Full FR-HTTP-2 surface live. Smoke against the four-table fixture passes.

### Phase 4 — Hardening + Docs + E2E

**Objective:** Close out CI gates, error handling consistency, OpenAPI polish, and the e2e smoke.

**Tasks:**

- **T4.1 — Error handler unification** [Effort: S]. App-level handlers for `NotFoundError`, `ValidationError`, `StorageError`. Dependencies: T3.3.
- **T4.2 — OpenAPI tagging + descriptions** [Effort: S]. Tags + summaries + examples. Dependencies: T4.1.
- **T4.3 — E2E smoke against `plumb serve`** [Effort: M]. Subprocess + `httpx.Client` against all five endpoints. Dependencies: T4.2.
- **T4.4 — Performance gate** [Effort: S]. `tests/http/perf/test_http_overhead.py` with §11.2 budgets. Dependencies: T4.3.
- **T4.5 — Docs + getting-started update** [Effort: S]. curl examples per route, link to TRD §5.3 Assumption 3. Dependencies: T4.4.

**Phase Deliverables:** CI green; `interrogate ≥ 95%` on `plumb/http.py`; E2E + perf tests pass; docs updated.

---

## 13. Resolved Decisions

> All TRS-time decisions (PD-1 to PD-5 from the original five clarifying questions, and PD-A to PD-E from the second round) are now **resolved**. They are mirrored in [`v1-http-context.md`](./v1-http-context.md) §"Resolved decisions" with full rationale. No open items block Phase 1.

### PD-A — Migrate `RunSummary` to a single canonical row type (RESOLVED 2026-05-05)

- **Decision:** **Option 2** — Migrate `plumb.adapters.storage_sqlite.RunSummary` → one canonical row type used by both CLI and HTTP. To keep `plumb/core/` Pydantic-free (NFR-Use-3), the canonical type is a frozen dataclass `RunSummaryRow` in `plumb/core/entities.py`; `RunSummaryOut` in `plumb/_http_schemas.py` is a Pydantic mirror constructed via `model_validate(row)` for the HTTP layer's `extra="forbid"` validation seam.
- **Per-task impact:**
  - **T1.1** adds `RunSummaryOut` (Pydantic mirror).
  - **T2.1** adds `RunSummaryRow` to `plumb/core/entities.py`, **deletes** `plumb.adapters.storage_sqlite.RunSummary`, and updates both `list_runs_with_counts` (used by CLI) and the new `list_runs_with_counts_paged` (used by HTTP) to return `list[RunSummaryRow]`.
  - **T2.1** also updates the CLI's `run_stats` command (`plumb/cli.py`) to consume `RunSummaryRow` instead of `RunSummary` in the same commit.
  - **T2.2** maps `list[RunSummaryRow]` → `list[RunSummaryOut]` at the route layer.

### PD-B — Default `pending` filter on `/runs` (RESOLVED 2026-05-05)

- **Decision:** **Option 1** — Include `status='pending'` runs by default. No filter logic added.
- **Per-task impact:** T2.2 AC list does not include "exclude pending".

### PD-C — `/v1/` URL prefix (RESOLVED 2026-05-05)

- **Decision:** **Option 1** — No `/v1/` prefix in v1. Matches TRD §3.6 verbatim.
- **Per-task impact:** None.

### PD-D — `tokens_in`/`tokens_out` on `RunOut` (RESOLVED 2026-05-05)

- **Decision:** **Option 1** — Report `tokens_in` and `tokens_out` separately on `RunOut`, matching the `runs` table schema.
- **Per-task impact:** Schemas in T1.1 already use this shape (§3.4); no change.

### PD-E — `/examples` pagination (RESOLVED 2026-05-05)

- **Decision:** **Option 1** — No pagination in v1. Re-evaluate at v1.1 if any user reports >5k rows.
- **Per-task impact:** T2.4 AC list excludes pagination tests.

---

*End of TRS v1 (Part 2 of 2).*
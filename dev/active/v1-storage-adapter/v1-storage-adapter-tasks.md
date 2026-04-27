# Tasks Checklist — `plumb/adapters/storage_sqlite.py` + `plumb/adapters/blobstore_fs.py`

**Companion to** [`v1-storage-adapter-plan.md`](./v1-storage-adapter-plan.md) and [`v1-storage-adapter-context.md`](./v1-storage-adapter-context.md).
**Total tasks:** 22 across 8 phases
**Effort scale:** S = ≤ 4h, M = ≤ 1 day, L = ≤ 2 days, XL = > 2 days
**Dependency rule:** phases are sequential. Within a phase, tasks may run in declared order.

Update this file as work progresses. Mark `[x]` when each acceptance criterion is met. **Do not mark a task complete unless every box under it is checked.**

---

## Phase 1 — Adapter package skeleton + DDL canonicalization

**Objective:** Stand up `plumb/adapters/` with empty modules, the canonical DDL strings, and pragma helpers.

### Task 1.1 — Create adapter package skeleton [S]

- [x] `plumb/adapters/__init__.py` exists and is empty (no eager imports)
- [x] `plumb/adapters/_schema.py` placeholder file exists
- [x] `plumb/adapters/_pragmas.py` placeholder file exists
- [x] `plumb/adapters/storage_sqlite.py` placeholder file exists
- [x] `plumb/adapters/blobstore_fs.py` placeholder file exists
- [x] `python -X importtime -c 'import plumb' 2>&1 | tail -5` shows no `plumb.adapters` line
- [x] Cold-import time still ≤ 200 ms (existing `tests/perf/test_cold_import.py` passes)
- [x] `from plumb.adapters import _schema, _pragmas` works on explicit import
- [x] `ruff check plumb/adapters/` exits 0

**Files to Create/Modify**
- `plumb/adapters/__init__.py`
- `plumb/adapters/_schema.py`
- `plumb/adapters/_pragmas.py`
- `plumb/adapters/storage_sqlite.py`
- `plumb/adapters/blobstore_fs.py`

**Dependencies:** none

**Testing Requirements:** Unit (import test only)

---

### Task 1.2 — Author canonical DDL in `_schema.py` [M]

- [x] `SCHEMA_VERSION: int = 1` defined
- [x] `DDL_STATEMENTS: tuple[str, ...]` defined with all 4 `CREATE TABLE` + 13 `CREATE INDEX` statements from TRD §7.1
- [x] All `CREATE TABLE` use `IF NOT EXISTS`
- [x] All `CREATE TABLE` use the `STRICT` keyword
- [x] All `CHECK` constraints from TRD §7.1 reproduced verbatim
- [x] Foreign-key clauses (`REFERENCES runs(run_id) ON DELETE CASCADE`, etc.) reproduced verbatim
- [x] `tests/unit/adapters/test_schema_ddl.py::test_ddl_matches_trd` compares `DDL_STATEMENTS` against a pinned copy of the TRD §7.1 SQL block; passes
- [x] `tests/unit/adapters/test_schema_ddl.py::test_each_statement_parses` runs every statement in an isolated `sqlite3.connect(':memory:')`; all pass
- [x] Coverage ≥ 90% on `_schema.py`

**Files to Create/Modify**
- `plumb/adapters/_schema.py`
- `tests/unit/adapters/__init__.py` (if needed for collection)
- `tests/unit/adapters/test_schema_ddl.py`

**Dependencies:** Task 1.1

**Testing Requirements:** Unit

---

### Task 1.3 — Implement `_pragmas.apply_pragmas` + `verify_pragmas` [S]

- [x] `apply_pragmas(conn)` sets `journal_mode=WAL`
- [x] `apply_pragmas(conn)` sets `synchronous=NORMAL`
- [x] `apply_pragmas(conn)` sets `busy_timeout=5000`
- [x] `apply_pragmas(conn)` sets `foreign_keys=ON`
- [x] `verify_pragmas(conn)` returns `None` when all four pragmas are correctly set
- [x] `verify_pragmas(conn)` raises `StorageError` if any pragma is wrong
- [x] Idempotent — calling `apply_pragmas` twice does not error and end state is identical
- [x] `tests/unit/adapters/test_pragmas.py` covers all four pragmas + idempotency + verify-fail path
- [x] Coverage ≥ 95% on `_pragmas.py`

**Files to Create/Modify**
- `plumb/adapters/_pragmas.py`
- `tests/unit/adapters/test_pragmas.py`

**Dependencies:** Task 1.1

**Testing Requirements:** Unit

---

**Phase 1 Deliverables:**
- [x] Adapter package importable but lazily loaded
- [x] Canonical DDL + pragma helpers in code with tests
- [x] Cold-import budget intact

---

## Phase 2 — `FilesystemBlobStore`

**Objective:** Ship the content-addressed blob store with full mode-bit and concurrency tests.

### Task 2.1 — Implement `FilesystemBlobStore.put` / `.get` / `.exists` [M]

- [x] `FilesystemBlobStore(root)` constructor stores `root` as `Path`; does NOT create dir eagerly (created on first `put`)
- [x] `put(content)` returns 64-char lowercase hex sha256 of `content`
- [x] `put` uses `os.open(target, O_CREAT|O_EXCL|O_WRONLY, 0o600)`, `os.write`, `os.fsync`, `os.close`
- [x] `put` of identical content twice returns same digest, no error, single file on disk
- [x] `put(b"")` works correctly (sha256 of empty bytes)
- [x] `get(hex)` returns the exact bytes that were `put`
- [x] `get(missing_hex)` raises `BlobNotFoundError` with the hex in the message
- [x] `get(malformed_hex)` (not 64 lowercase hex chars) raises `ValidationError`
- [x] `exists(hex)` returns `bool` correctly
- [x] Hypothesis property test: `get(put(b)) == b` for arbitrary `bytes` (length 0..1024)
- [x] Coverage ≥ 95% on `blobstore_fs.py`

**Files to Create/Modify**
- `plumb/adapters/blobstore_fs.py`
- `tests/unit/adapters/test_blobstore_put_get.py`

**Dependencies:** Task 1.1

**Testing Requirements:** Unit + property

---

### Task 2.2 — Mode-bit invariants [S]

- [x] After first `put`, `stat(root).st_mode & 0o777 == 0o700`
- [x] After first `put`, `stat(root / digest[:2]).st_mode & 0o777 == 0o700`
- [x] After first `put`, `stat(root / digest[:2] / digest[2:]).st_mode & 0o777 == 0o600`
- [x] Test marked `@pytest.mark.skipif(os.name == 'nt', reason='POSIX modes only')` — Windows skip
- [x] Mode bits hold even when run with permissive umask (e.g., `umask(0)` in fixture)

**Files to Create/Modify**
- `tests/unit/adapters/test_blobstore_modes.py`

**Dependencies:** Task 2.1

**Testing Requirements:** Unit

---

### Task 2.3 — Concurrency / `O_EXCL` race test [S]

- [x] `concurrent.futures.ThreadPoolExecutor` runs `put(same_content)` 10× in parallel
- [x] No exception raised in any thread
- [x] Final file count for that digest = 1
- [x] All 10 returned digests match
- [x] Test runs in < 1 second

**Files to Create/Modify**
- `tests/unit/adapters/test_blobstore_concurrency.py`

**Dependencies:** Task 2.1

**Testing Requirements:** Unit

---

**Phase 2 Deliverables:**
- [x] `FilesystemBlobStore` complete with ≥ 95% coverage
- [x] Mode-bit and concurrency invariants verified

---

## Phase 3 — `SQLiteStorageAdapter` writes

**Objective:** Ship `__init__`, `write_run`, `write_score`, `write_example` with full schema enforcement.

### Task 3.1 — Adapter `__init__` + schema bootstrap [M]

- [ ] `SQLiteStorageAdapter(db_path, clock=...)` opens connection successfully
- [ ] On fresh DB: tables + indexes created; `PRAGMA user_version` returns `1`
- [ ] On existing v1 DB: re-init is no-op (no error, schema unchanged)
- [ ] On existing v999 DB: raises `StorageError("Schema version mismatch: db=999 expected=1")`
- [ ] `apply_pragmas` called on the connection during init
- [ ] Stalled-run sweep runs once during init (Phase 5 will exhaustively test it; smoke check here)
- [ ] `plumb.db` file mode is `0o600` after first creation (POSIX-only check)
- [ ] `close()` is idempotent (calling twice does not error)
- [ ] Adapter usable as context manager: `with SQLiteStorageAdapter(...) as adapter: ...`
- [ ] `tests/unit/adapters/test_storage_lifecycle.py` covers fresh-init, re-init, version-mismatch, close-idempotency

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_lifecycle.py`

**Dependencies:** Task 1.2, Task 1.3

**Testing Requirements:** Unit

---

### Task 3.2 — `write_run(run, spans)` batched insert [M]

- [ ] Run with 0 spans → 1 `runs` row, 0 `spans` rows; valid (FR-EDGE-3)
- [ ] Run with 100 spans → 1 + 100 rows in one transaction
- [ ] Re-inserting same `run_id` raises `StorageError` (PK violation, wrapped with original `__cause__`)
- [ ] Inserting span with non-existent `run_id` raises `StorageError` (FK violation; defense-in-depth path)
- [ ] Tz-aware UTC `datetime` serializes to ISO-8601 string with `+00:00`
- [ ] Naive `datetime` (would have failed entity invariant; should be unreachable) — sanity raise of `StorageError` if it slips through
- [ ] Enum values serialize to their `.value` strings (not enum names)
- [ ] `None` for nullable columns persisted as SQL `NULL`
- [ ] Single transaction verified by `sqlite3.Connection.in_transaction` snapshotted under instrumentation hook
- [ ] `tests/unit/adapters/test_storage_writer.py` covers all of above

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_writer.py`

**Dependencies:** Task 3.1

**Testing Requirements:** Unit

---

### Task 3.3 — `write_score` + XOR CHECK enforcement [S]

- [ ] Valid score with `value_numeric` only inserts; row readable
- [ ] Valid score with `value_label` only inserts; row readable
- [ ] Constructed entity with both values would have failed at entity layer; bypass via raw SQL test confirms `IntegrityError` → `StorageError`
- [ ] `scorer_version=NULL` would fail (entity prevents but verify SQL also enforces NOT NULL)
- [ ] `scored_at` tz-aware UTC serializes correctly
- [ ] `tests/unit/adapters/test_storage_xor_check.py` covers SQL-boundary enforcement

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_xor_check.py`

**Dependencies:** Task 3.1

**Testing Requirements:** Unit

---

### Task 3.4 — `write_example` + FK to `runs` [S]

- [ ] Example with valid `origin_run_id` (existing run) inserts
- [ ] Example with `origin_run_id=None` inserts (column is nullable)
- [ ] Example with non-existent `origin_run_id` raises `StorageError` (FK violation)
- [ ] `active=0` and `active=1` both accepted; `active=2` rejected by CHECK → `StorageError`
- [ ] `source ∈ {'synthetic', 'production_promotion', 'human_authored'}` accepted; other values rejected
- [ ] Extends `tests/unit/adapters/test_storage_writer.py`

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_writer.py` (extends)

**Dependencies:** Task 3.2

**Testing Requirements:** Unit

---

**Phase 3 Deliverables:**
- [ ] All write paths complete
- [ ] CHECK + FK enforcement verified at SQL boundary
- [ ] Coverage ≥ 90% on `storage_sqlite.py` (writer paths)

---

## Phase 4 — `SQLiteStorageAdapter` reads

**Objective:** Ship `get_run`, `list_runs`, `get_spans_for_run`, `get_scores_for_run`, `list_examples`.

### Task 4.1 — Single-row readers [M]

- [ ] `get_run(run_id)` returns hydrated `Run` instance with all fields populated
- [ ] Tz-aware UTC `datetime` round-trips byte-identical (`written_run == get_run(written_run.run_id)`)
- [ ] Enum fields rehydrate to enum instances (not bare strings)
- [ ] `get_run("nonexistent")` returns `None`
- [ ] `get_spans_for_run(run_id)` returns spans ordered by `span_id` (deterministic)
- [ ] `get_spans_for_run("nonexistent")` returns `[]`
- [ ] `get_scores_for_run(run_id)` returns scores; XOR field reads correctly (numeric or label, never both)
- [ ] Hypothesis property test: round-trip equality for `Run`/`Span`/`Score`/`Example`
- [ ] `tests/unit/adapters/test_storage_reader.py` covers all of above

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_reader.py`

**Dependencies:** Task 3.2, Task 3.3

**Testing Requirements:** Unit + property

---

### Task 4.2 — List readers [M]

- [ ] `list_runs(limit=10)` returns ≤ 10 rows ordered by `start_ts DESC`
- [ ] `list_runs(since=dt)` filters `start_ts >= dt` (parameterized; no string concat)
- [ ] `list_runs(task_id="x")` filters correctly
- [ ] `list_runs(kind="online")` accepted; rehydrates to `RunKind.ONLINE`
- [ ] `list_runs(kind="invalid")` raises `ValidationError` BEFORE hitting SQL
- [ ] All filter combinators compose with `AND` (verify via SQL log capture or instrumented cursor)
- [ ] `list_examples(active=True)` filters `active=1`
- [ ] `list_examples(active=False)` filters `active=0`
- [ ] `list_examples(task_id="x", active=True)` combines filters
- [ ] `ruff check plumb/adapters/storage_sqlite.py` clean (S608 enforced)
- [ ] Test with hostile filter values (`"x' OR 1=1 --"`) — query parameterizes correctly, returns empty / matching only literal
- [ ] Extends `tests/unit/adapters/test_storage_reader.py`

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_reader.py` (extends)

**Dependencies:** Task 4.1

**Testing Requirements:** Unit

---

**Phase 4 Deliverables:**
- [ ] Reader surface complete with ≥ 90% coverage
- [ ] Round-trip property test passing for all four entity types
- [ ] SQL injection paths verified absent

---

## Phase 5 — Stalled-run sweep + lifecycle edge cases

**Objective:** Implement and verify FR-EDGE-2 + adapter teardown semantics.

### Task 5.1 — Stalled-run sweep [S]

- [ ] Run inserted with `end_ts=NULL` and `start_ts` 2 hours ago → marked `stalled` after re-init
- [ ] Run inserted with `end_ts=NULL` and `start_ts` 30 min ago → unchanged (within threshold)
- [ ] Run with `end_ts` set → unchanged regardless of age
- [ ] Run already `stalled`/`aborted`/`failure` → unchanged (status guard prevents double-mark)
- [ ] INFO log line emitted with the count of marked runs
- [ ] `stalled_threshold_seconds=60` constructor arg honored (allows fast tests)
- [ ] Sweep query parameterized (binds threshold_iso via `?`)
- [ ] Extends `tests/unit/adapters/test_storage_lifecycle.py`

**Files to Create/Modify**
- `plumb/adapters/storage_sqlite.py`
- `tests/unit/adapters/test_storage_lifecycle.py` (extends)

**Dependencies:** Task 3.1

**Testing Requirements:** Unit

---

### Task 5.2 — Concurrent-process opens (WAL semantics) [M]

- [ ] Two adapter instances on same `db_path` both open without error
- [ ] Reader sees data committed by writer after writer's `with conn:` exits
- [ ] Writer's open transaction does not block reader's `get_run` / `list_runs` (WAL semantics)
- [ ] Test runs in < 2 seconds
- [ ] `tests/integration/test_concurrent_adapters.py` covers both ordering paths

**Files to Create/Modify**
- `tests/integration/test_concurrent_adapters.py`

**Dependencies:** Task 4.1

**Testing Requirements:** Integration

---

**Phase 5 Deliverables:**
- [ ] FR-EDGE-2 implemented + tested
- [ ] Multi-adapter coexistence verified

---

## Phase 6 — `plumb.config` + `plumb.api` integration

**Objective:** Wire real adapters into the API layer so the v1 Core+API ACs all keep passing with no fakes.

### Task 6.1 — Extend `plumb.config` with `data_dir` + `ensure_data_dir` [S]

- [ ] `Settings.data_dir: Path` field added with default `~/.plumb`
- [ ] `PLUMB_DATA_DIR=/tmp/x` env var override resolves to `Path("/tmp/x")`
- [ ] `ensure_data_dir(settings)` creates dir with mode `0o700`
- [ ] `ensure_data_dir` idempotent on existing dir (does NOT change mode bits if user widened them)
- [ ] `ensure_data_dir` returns absolute, resolved Path
- [ ] Tilde expansion (`~/.plumb`) handled correctly
- [ ] `tests/unit/test_config.py` extended (or created) to cover all of above

**Files to Create/Modify**
- `plumb/config.py`
- `tests/unit/test_config.py`

**Dependencies:** none

**Testing Requirements:** Unit

---

### Task 6.2 — Lazy adapter init in `plumb.api` [M]

- [ ] `plumb.api._storage` and `plumb.api._blobstore` module-level singletons declared (initially `None`)
- [ ] `_init_storage_singletons()` lazy bootstrap function added
- [ ] Cold `import plumb` does NOT instantiate `SQLiteStorageAdapter` (verified via `ImportTime` snapshot or test that asserts `_storage is None` post-import)
- [ ] First `with run(...)` triggers `_init_storage_singletons` exactly once (instrumented via spy)
- [ ] Second `with run(...)` reuses the same singleton (spy not called again)
- [ ] All existing core-slice `configured_api` fixture tests still pass (monkeypatch path unchanged)
- [ ] Cold-import time still ≤ 200 ms
- [ ] `tests/unit/api/test_lazy_init.py` covers all of above

**Files to Create/Modify**
- `plumb/api.py`
- `tests/unit/api/test_lazy_init.py`

**Dependencies:** Task 6.1, Task 4.2, Task 2.1

**Testing Requirements:** Unit

---

### Task 6.3 — Integration test: full `@run` → real DB [M]

- [ ] `@run(task_id=...)` on sync function writes 1 `runs` row + spans + (if applicable) blobs to a `tmp_path` DB
- [ ] Async variant works (`@run` on `async def`)
- [ ] Nested decorator: 2 rows; child row has correct `parent_run_id` matching parent's `run_id`
- [ ] `r.add_score(...)` writes a `scores` row
- [ ] `r.abort("reason")` flushes partial buffer with `status='aborted'` and `error_type='reason'`
- [ ] All v1 Core+API ACs (AC-API-1, AC-API-2 sync + async) re-run green with real adapter
- [ ] `r.add_span(kind=SpanKind.HANDOFF, name=..., input_hash=h1, output_hash=h2)` round-trips both blob hashes through `FilesystemBlobStore`
- [ ] Storage-failure path: simulate `StorageError` via monkeypatched adapter; wrapped function's return value reaches caller unchanged (AC-REL-1 partial)
- [ ] `tests/integration/test_api_with_sqlite.py` and `tests/integration/test_api_with_blobstore.py` cover all of above

**Files to Create/Modify**
- `tests/integration/test_api_with_sqlite.py`
- `tests/integration/test_api_with_blobstore.py`

**Dependencies:** Task 6.2

**Testing Requirements:** Integration

---

**Phase 6 Deliverables:**
- [ ] Real adapters wired into `plumb.api`
- [ ] All prior-slice ACs still green
- [ ] First end-to-end integration test passing

---

## Phase 7 — Durability + performance gates

**Objective:** Verify NFR-Rel-2 (SIGKILL durability) and NFR-Perf-2 (run close p95 ≤ 50 ms).

### Task 7.1 — SIGKILL durability test [L]

- [ ] Helper script (separate file under `tests/integration/_sigkill_helper.py`) writes a sentinel run + spans, fsyncs, prints `READY` to stdout, then sleeps
- [ ] Parent test spawns `subprocess.Popen([sys.executable, helper_path, db_path])`, reads `READY`, sends `SIGKILL` via `os.kill(child.pid, signal.SIGKILL)`
- [ ] Parent re-opens `SQLiteStorageAdapter(db_path)`; sentinel run + spans intact and queryable
- [ ] `parent_run_id` and `start_ts` fields match exactly what helper wrote
- [ ] Test marked `@pytest.mark.skipif(os.name == 'nt', reason='SIGKILL not portable')`
- [ ] Test runs under 5 seconds end-to-end
- [ ] CI matrix runs it on `ubuntu-24.04` and `macos-14`

**Files to Create/Modify**
- `tests/integration/_sigkill_helper.py`
- `tests/integration/test_sigkill_durability.py`

**Dependencies:** Task 6.3

**Testing Requirements:** Integration (real subprocess)

---

### Task 7.2 — Run-close performance benchmark [M]

- [ ] `tests/perf/test_run_close_overhead.py` opens a `tmp_path` DB
- [ ] Loops 100 iterations: build a `Run` + 100 `Span` instances, call `write_run`, time the call
- [ ] Reports min / mean / p95 / max in test output (visible in CI logs)
- [ ] Asserts p95 ≤ 50 ms on CI runner
- [ ] Local convention: 2× headroom factor allowed for CI noise (assert ≤ 100 ms locally if `os.environ.get("CI") != "true"`)
- [ ] Marked with `pytest.mark.perf`
- [ ] CI job already includes `pytest tests/perf/` from core slice; this test runs automatically

**Files to Create/Modify**
- `tests/perf/test_run_close_overhead.py`

**Dependencies:** Task 6.3

**Testing Requirements:** Performance

---

**Phase 7 Deliverables:**
- [ ] NFR-Rel-2 acceptance criterion proven (SIGKILL durability)
- [ ] NFR-Perf-2 acceptance criterion proven (run close p95 ≤ 50 ms)

---

## Phase 8 — Documentation update + sign-off

**Objective:** Update evergreen docs; archive this slice.

### Task 8.1 — Update `docs/2_architecture/SYSTEM_DESIGN.md` [S]

- [ ] §3.2 storage row references `plumb/adapters/storage_sqlite.py` as implemented
- [ ] §4.3 blob row references `plumb/adapters/blobstore_fs.py` as implemented
- [ ] No dead links in the touched sections
- [ ] If the SDD has any "TODO" / "to be implemented" markers near storage, they're resolved

**Files to Create/Modify**
- `docs/2_architecture/SYSTEM_DESIGN.md`

**Dependencies:** Task 7.2

**Testing Requirements:** Docs review

---

### Task 8.2 — Update `docs/3_guides/getting_started.md` [S]

- [ ] Quick-start runs end-to-end on a fresh venv (`uv sync` → `python -c "from plumb import run; ..."`)
- [ ] After first `with run(...)` block, `~/.plumb/plumb.db` exists
- [ ] `~/.plumb/blobs/` exists (if any blobs written)
- [ ] Mode bits `0700` on `~/.plumb/`, `0600` on `plumb.db` documented
- [ ] iCloud / Dropbox warning added (mode bits do not survive sync providers)
- [ ] One-liner showing how to inspect: `sqlite3 ~/.plumb/plumb.db ".tables"`

**Files to Create/Modify**
- `docs/3_guides/getting_started.md`

**Dependencies:** Task 7.2

**Testing Requirements:** Docs smoke

---

### Task 8.3 — Archive this slice [S]

- [ ] PR merged to `main`
- [ ] `dev/active/v1-storage-adapter/` moved to `dev/archive/v1-storage-adapter/`
- [ ] All cross-links in other in-flight TRSes (autocapture, CLI, HTTP, judge, ATTACH) updated to `dev/archive/...`
- [ ] Final `tasks.md` state recorded (this file, fully checked)
- [ ] CHANGELOG entry added (if CHANGELOG.md exists)

**Files to Create/Modify**
- directory move
- cross-links in any sibling TRSes that exist

**Dependencies:** Task 8.1, Task 8.2

**Testing Requirements:** none

---

**Phase 8 Deliverables:**
- [ ] Evergreen docs reflect implemented storage layer
- [ ] Slice archived
- [ ] Ready for next TRS (autocapture / CLI / HTTP / judge / ATTACH)

---

## Final-acceptance checklist (run after Phase 8)

Before declaring this slice done, confirm:

- [ ] `pytest --cov=plumb --cov-fail-under=85 tests/unit/adapters tests/integration` passes
- [ ] `pytest tests/perf/test_run_close_overhead.py -m perf` passes
- [ ] `ruff check plumb/adapters/` clean (incl. `S608`)
- [ ] `ruff format --check plumb/adapters/` clean
- [ ] `mypy --strict plumb/core/` still clean (no regression from API integration)
- [ ] Cold import benchmark still ≤ 200 ms
- [ ] All v1 Core+API ACs (AC-API-1, AC-API-2 sync + async) green with real adapters
- [ ] AC-SCHEMA-1, AC-SCHEMA-2, AC-SCHEMA-3, AC-PERF-2, AC-REL-1 (partial), AC-REL-2 all green
- [ ] No `.db`, `.db-wal`, `.db-shm` accidentally committed (gitignore verified)
- [ ] No new third-party runtime dependencies in `pyproject.toml`

---

*End of tasks checklist.*

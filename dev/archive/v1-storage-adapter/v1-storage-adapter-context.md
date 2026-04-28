# Context — `plumb/adapters/storage_sqlite.py` + `plumb/adapters/blobstore_fs.py`

**Companion to** [`v1-storage-adapter-plan.md`](./v1-storage-adapter-plan.md) and [`v1-storage-adapter-tasks.md`](./v1-storage-adapter-tasks.md).
**Last updated:** 2026-04-26

This document captures the design rationale, integration points, and resolved decisions that shaped the TRS. Read this before authoring code or reviewing the plan to understand *why* the spec looks the way it does.

---

## 1. Files to touch

### 1.1 New files

| Path | Purpose |
|---|---|
| `plumb/adapters/__init__.py` | Empty package marker — must NOT eager-import to preserve cold-import budget (NFR-Perf-6) |
| `plumb/adapters/_schema.py` | Canonical DDL strings (4 CREATE TABLE + 13 CREATE INDEX); `SCHEMA_VERSION = 1` |
| `plumb/adapters/_pragmas.py` | `apply_pragmas` + `verify_pragmas` helpers (WAL, NORMAL, busy_timeout=5000, foreign_keys=ON) |
| `plumb/adapters/storage_sqlite.py` | `SQLiteStorageAdapter` — `StorageWriter` + `StorageReader` over one persistent SQLite connection |
| `plumb/adapters/blobstore_fs.py` | `FilesystemBlobStore` — content-addressed FS store with `O_CREAT\|O_EXCL` writes |
| `tests/unit/adapters/test_schema_ddl.py` | DDL parses + matches TRD §7.1 byte-for-byte |
| `tests/unit/adapters/test_pragmas.py` | All four pragmas verified on a fresh connection |
| `tests/unit/adapters/test_storage_writer.py` | `write_run`, `write_score`, `write_example` round-trips and edge cases |
| `tests/unit/adapters/test_storage_reader.py` | `get_run`, `list_runs`, `get_spans_for_run`, `get_scores_for_run`, `list_examples` |
| `tests/unit/adapters/test_storage_lifecycle.py` | `__init__` idempotency, schema-version mismatch, stalled-run sweep, `close()` |
| `tests/unit/adapters/test_storage_xor_check.py` | SQL CHECK rejects `value_numeric` ⊕ `value_label` violations |
| `tests/unit/adapters/test_blobstore_put_get.py` | Round-trip, dedup, hash correctness, empty-bytes |
| `tests/unit/adapters/test_blobstore_modes.py` | `0600` / `0700` mode-bit invariants (POSIX-only) |
| `tests/unit/adapters/test_blobstore_concurrency.py` | `O_CREAT\|O_EXCL` race semantics under threads |
| `tests/integration/test_api_with_sqlite.py` | Full `@run` cycle into real DB (sync + async + nested) |
| `tests/integration/test_api_with_blobstore.py` | Handoff blob round-trip via `RunHandle.add_span` (input_hash/output_hash) |
| `tests/integration/test_concurrent_adapters.py` | Two adapters open same DB; reader sees writer's commits |
| `tests/integration/test_sigkill_durability.py` | Subprocess SIGKILL after fsync; data intact on re-open |
| `tests/perf/test_run_close_overhead.py` | NFR-Perf-2 gate: 100-span run close p95 ≤ 50 ms |

### 1.2 Modified files

| Path | Change |
|---|---|
| `plumb/api.py` | Add `_storage` / `_blobstore` module-level singletons + `_init_storage_singletons()` lazy bootstrap on first `run(...)` call |
| `plumb/config.py` | Add `data_dir: Path` field to `Settings`; add `ensure_data_dir(settings)` helper that creates dir mode `0700` |
| `tests/conftest.py` | Add `tmp_db_adapter`, `tmp_blobstore`, `configured_api_real` fixtures alongside the existing fakes |
| `pyproject.toml` | (only if not already) add `S` / `S608` to `[tool.ruff.lint] select` to enforce parameterized SQL |
| `docs/2_architecture/SYSTEM_DESIGN.md` | Mark §3.2 storage rows + §4.3 blob row as "implemented in v1-storage-adapter slice" |
| `docs/3_guides/getting_started.md` | Update quick-start to reflect that `@run` actually persists to `~/.plumb/plumb.db` after this slice |

### 1.3 Files explicitly NOT touched

- `plumb/core/*` — pure-Python core; this slice depends on it but does not modify it.
- `plumb/__init__.py` — public surface unchanged. Adapters are not re-exported.
- `plumb/cli.py`, `plumb/http.py`, `plumb/autocapture/` — not yet exist; their slices will consume this adapter.

---

## 2. Key dependencies

### 2.1 Inward (this slice depends on)

- `plumb.core.entities` — `Run`, `Span`, `Score`, `Example`, `JudgeResult`, all enums (`RunKind`, `RunStatus`, `SpanKind`, `SpanStatus`, `ScorerKind`, `ExampleSource`).
- `plumb.core.ports` — `StorageWriter`, `StorageReader`, `BlobStore`, `Clock` Protocols.
- `plumb.core.errors` — `StorageError`, `BlobNotFoundError`, `ValidationError`.
- `pydantic-settings` — `Settings` model already in place from core slice; we extend it.
- Stdlib only otherwise: `sqlite3`, `pathlib`, `os`, `hashlib`, `datetime`, `logging`, `re`, `contextlib`.

### 2.2 Outward (consumers of this slice)

- `plumb.api` — replaces fake writer with `SQLiteStorageAdapter`; adds `FilesystemBlobStore`.
- (Future) `plumb.cli`, `plumb.http` — read via `StorageReader`.
- (Future) `plumb.adapters.judge_*` — write scores via `StorageWriter.write_score`.
- (Future) `plumb.adapters.agentsview_attach` — uses the SQLite connection for `ATTACH DATABASE` + `INSERT OR IGNORE`.

### 2.3 No new third-party packages

The slice introduces zero new runtime dependencies. Test extras (`pytest`, `hypothesis`, etc.) are already pulled in via the dev dependency group.

---

## 3. Resolved decisions

The user accepted all three recommendations on 2026-04-26 plus four authoring-time defense-in-depth choices.

### 3.1 Q1 — Blob store: separate adapter

**Decision:** `FilesystemBlobStore` is a distinct class from `SQLiteStorageAdapter`. Both are independently injectable into `plumb.api`.

**Why:** `BlobStore` and `StorageWriter` are already separate Protocols in `plumb.core.ports`. Bundling them would muddle the seam; downstream slices (judge, ATTACH) need the blob store but not necessarily the SQLite writer (or vice versa). Two ~150-line files beat one ~300-line file.

**How to apply:** Tests inject either independently. Production wiring in `plumb.api._init_storage_singletons()` instantiates both side-by-side under `$PLUMB_DATA_DIR`.

### 3.2 Q2 — Connection lifecycle: single persistent connection

**Decision:** One `sqlite3.Connection` per `SQLiteStorageAdapter` instance, opened in `__init__`, closed in `close()` / context-manager exit.

**Why:** Per-operation reconnect adds ~1-2 ms overhead per `write_run` — that's enough to threaten NFR-Perf-2 (≤ 50 ms with 100 spans includes other overhead). Single-user posture means contention is theoretical, not practical. WAL mode handles whatever multi-process contention does occur via `busy_timeout=5000`.

**How to apply:** Adapter is constructed once at `plumb.api` first-use; `check_same_thread=False` + connection-level lock in SQLite handles intra-process threading. Tests use `tmp_path` and call `.close()` in fixture teardown.

### 3.3 Q3 — Stalled-run sweep: on `__init__`

**Decision:** Sweep `runs WHERE end_ts IS NULL AND start_ts < now() - 1h` once during adapter `__init__`.

**Why:** FR-EDGE-2 says "on next startup" — adapter `__init__` is the natural startup boundary. One UPDATE statement on an indexed-ish scan is cheap (≤ 5 ms typical). Lazy-on-first-write is more complex without observable benefit (the HTTP read service has no `write` to trigger a lazy sweep).

**How to apply:** Sweep is a single parameterized UPDATE; threshold timestamp comes from injected `Clock`; logs at INFO with row count. Tests inject `FakeClock` to make the boundary deterministic.

### 3.4 Authoring-time decisions (recorded for reviewers)

| # | Decision | Rationale |
|---|---|---|
| 4 | `plumb.db` file `chmod 0o600` after first creation | TRD doesn't mandate (only NFR-Sec-5 covers blobs + dir), but consistency with `0600` blob posture is cheap defense-in-depth on shared machines. WAL/SHM files inherit umask (acceptable; SQLite manages them and they're not the durable store). |
| 5 | Schema-version mismatch → hard fail (`StorageError`) | TRD DATA-MIG-1: zero migrations after Week 4; v2 = major version bump with separate `plumb migrate` tool. Auto-migration is explicitly out of scope for v1; silent downgrade would corrupt data. |
| 6 | Empty-blob (`b""`) is valid | sha256 of empty bytes is well-defined (`e3b0c44...`). No special-casing avoids a class of bugs around "is this content meaningful." If a metric needs "content present" it can check `len(content) > 0` at the metric layer. |
| 7 | `:memory:` SQLite for unit tests, `tmp_path` for integration | `:memory:` databases bypass WAL and fsync — fine for query-shape unit tests, fatal for durability tests. NFR-Rel-2 (SIGKILL durability) and NFR-Perf-2 (run close fsync) both demand a real file. |

---

## 4. Pending decisions / clarifications

**None at TRS authoring time.** All architectural questions resolved per §3 above.

If during implementation any of these surface, escalate before coding:
- Discovery that NFR-Perf-2 (≤ 50 ms p95 with 100 spans) is unattainable on the CI runner with the current spec → consider relaxing `synchronous=NORMAL` to `OFF` with explicit durability tradeoff in deferred-features.md (do NOT ship without sign-off).
- Discovery that `executemany` is materially slower than per-row `execute` for ≤ 100 rows on Python 3.13 / SQLite 3.38+ → benchmark both, pick the winner; this is implementation choice within the spec, no TRS revision needed.
- Discovery that contextvars-based threading interacts badly with `check_same_thread=False` → fall back to a thread-local connection pool (1 conn per thread, shared db file via WAL); update the TRS.

---

## 5. Integration points

### 5.1 With v1 Core+API slice

The core slice's [`v1-core-and-api-plan.md` §3.6 "Public API"](../../archive/v1-core-and-api/v1-core-and-api-plan.md) declared module-level singletons in `plumb.api`:

```python
_clock: Clock = ...                     # already present
_id_gen: IdGenerator = ...              # already present
_storage_writer: StorageWriter = ...    # core slice used a FakeStorageWriter for tests
```

This slice replaces the fake `_storage_writer` with a lazy-init real `SQLiteStorageAdapter`, and adds a `_blobstore` singleton. The lazy guard means **all existing core-slice tests pass unchanged** (their `configured_api` fixture monkeypatches the singletons before any `run()` call, which short-circuits `_init_storage_singletons`).

### 5.2 With future autocapture slice

Autocapture writes spans via `RunHandle.add_span(...)`. That handle ends up calling `StorageWriter.write_run(...)` at run close. **No autocapture-specific changes** in this slice — the seam is already in place via the core slice's `RunHandle._builder`.

### 5.3 With future CLI / HTTP slices

`plumb run stats`, `plumb score write`, `plumb example promote`, and the FastAPI read endpoints all consume `StorageReader`. The reader surface this slice ships (`get_run`, `list_runs`, `get_spans_for_run`, `get_scores_for_run`, `list_examples`) is sufficient for [TRD §3.5 / §3.6](../../../docs/2_architecture/TRD.md#35-cli) without further extension.

If a CLI / HTTP query needs a method this adapter doesn't expose (e.g., aggregate stats across runs), that method goes on a follow-up TRS revision — **not** as a side-channel reach-around to the SQLite connection.

### 5.4 With future ATTACH-adapter slice

The `agentsview_attach` adapter (≤ 200 LOC per TRD INT-ATTACH-2) needs to issue `ATTACH DATABASE 'path' AS source; INSERT OR IGNORE INTO runs SELECT ...`. Two ways to expose the connection:

1. **Add `attach_source(path) -> Cursor` method** to `SQLiteStorageAdapter` that returns a cursor on the persistent connection with the source already attached.
2. Let the ATTACH adapter open its own connection on the same `db_path`.

**Decision deferred to the ATTACH TRS.** Option 1 is cleaner (one connection, one tx); Option 2 isolates blast radius. Either way, **this slice does not preempt the choice** — the persistent-connection design supports both.

---

## 6. Testing posture summary

- **Unit tests** dominate. Each method has a happy-path test + at least one edge-case test (empty input, duplicate insert, missing row, invalid filter).
- **Property tests (Hypothesis)** cover round-trip for `Run` / `Span` / `Example` and the XOR invariant for `Score`. Strategies live in `tests/conftest.py` for reuse.
- **Integration tests** spin up `SQLiteStorageAdapter` + `FilesystemBlobStore` against `tmp_path` and exercise the full `@run(...)` flow without fakes. This catches contract drift between the adapter and `RunHandle._builder`.
- **Durability test** is subprocess-based, POSIX-only. Skipped on Windows.
- **Performance test** runs in `tests/perf/` with the existing `pytest.mark.perf` marker. CI runs it on every PR.

**Coverage targets** are higher than the project-wide 75% gate because this slice is mostly testable I/O — there are no excuses for low coverage.

---

## 7. Risks specific to this slice

| Risk | Impact | Mitigation |
|---|---|---|
| `executemany` slower than expected on the CI runner → blows NFR-Perf-2 | High | Benchmark in Phase 7.2 reports p95 numbers; if regression, switch to a single big `INSERT INTO spans VALUES (...), (...), ...` — same wire shape, one statement. |
| `synchronous=NORMAL` not durable enough on a power-loss scenario | Low | TRD-mandated; documented as v1 trade-off. Users wanting full durability set `PLUMB_SQLITE_SYNCHRONOUS=FULL` (env var; deferred config addition if asked). |
| WAL files (`*-wal`, `*-shm`) leaked to git or backups | Low | `.gitignore` already covers `*.db`, `*.db-wal`, `*.db-shm` since core slice. Re-verify in Phase 1. |
| Schema drift between TRD §7.1 and `_schema.py` | Medium | Phase 1 task 1.2 includes a test that diffs the canonical TRD block against `DDL_STATEMENTS`. CI catches drift on every PR. |
| Stalled-run sweep slow on a DB with millions of runs (future) | Low | Out of v1 scope; if it materializes in v2, add `WHERE end_ts IS NULL` partial index. |
| Mode-bit test fails on macOS+iCloud-synced data dirs | Low | Document in `getting_started.md`: keep `~/.plumb/` outside iCloud / Dropbox to preserve POSIX modes. Tests use `tmp_path` so they're unaffected. |
| `O_CREAT\|O_EXCL` race semantics differ on network filesystems (NFS) | Low | v1 posture is "single-user local"; NFS is not a supported deployment. Documented under §11.3 of the plan. |

---

## 8. Memory aids — questions reviewers will ask

**"Why two adapter classes instead of one?"** → §3.1 (separate Protocols, separate concerns, smaller files).

**"Why a persistent connection?"** → §3.2 (per-op reconnect threatens NFR-Perf-2; single-user posture means contention is theoretical).

**"Why sweep stalled runs in `__init__`?"** → §3.3 (FR-EDGE-2 says "on next startup"; init *is* startup; cheap UPDATE).

**"Why `chmod 0o600` on `plumb.db` if TRD doesn't require it?"** → §3.4 #4 (consistency with blob `0600`; cheap defense-in-depth on shared machines).

**"Why does `list_runs(kind=...)` validate against the enum before SQL?"** → §3.4.5 (avoids wasted query on a guaranteed-empty result; gives `ValidationError` early; supports SQL-injection prevention by ruling out arbitrary string filters).

**"Why no migration tool in v1?"** → TRD DATA-MIG-1 (zero migrations after Week 4; any change = v2).

**"What happens if SIGKILL hits between BEGIN and COMMIT?"** → Plan §7 (transaction auto-rolls back on next open; no partial run row exists; no FR-EDGE-2 sweep needed).

**"Why is `mypy --strict` only on `plumb/core/`?"** → TRD §4.4 NFR-Use-3 (adapters use real I/O types like `sqlite3.Connection` whose stubs are loose; strict mode would create noise without catching real bugs).

---

*End of context document.*

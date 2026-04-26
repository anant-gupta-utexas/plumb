# TRS — `plumb/adapters/storage_sqlite.py` + `plumb/adapters/blobstore_fs.py` (v1 Storage Slice)

**Status:** Draft v1 — derived from [TRD](../../../docs/2_architecture/TRD.md) and [SDD](../../../docs/2_architecture/SYSTEM_DESIGN.md), follows [v1 Core+API TRS](../../archive/v1-core-and-api/v1-core-and-api-plan.md)
**Owner:** anant
**Last updated:** 2026-04-26
**Scope:** The second component slice of plumb v1: the SQLite-backed `StorageWriter`/`StorageReader` adapter and the content-addressed filesystem `BlobStore` adapter that satisfy the Protocols defined in `plumb/core/ports.py`.

> **What this is.** A Technical Requirements Specification (TRS) translating TRD-level FR/NFR IDs into class-level signatures, SQL DDL/DML, file-system layout, and acceptance tests for the storage layer. Implementation phases (with task-level effort, files, and AC checklists) are in [`v1-storage-adapter-tasks.md`](./v1-storage-adapter-tasks.md); design rationale and resolved decisions are in [`v1-storage-adapter-context.md`](./v1-storage-adapter-context.md).
>
> **What this is not.** Not the autocapture, CLI, HTTP, judge, or ATTACH-adapter slices. Each gets its own TRS folder. This slice replaces the in-memory `FakeStorageWriter` (used by the v1 core+api TRS) with the production SQLite + filesystem combo, and wires it into `plumb.api`'s module-level singletons.

---

## 1. Overview & Scope

### 1.1 What this slice delivers

The two production-grade adapters that satisfy `plumb.core.ports`:

- `plumb/adapters/__init__.py` — package marker; **no eager imports** to preserve cold-import budget (NFR-Perf-6).
- `plumb/adapters/storage_sqlite.py` — `SQLiteStorageAdapter` implementing both `StorageWriter` and `StorageReader` ([TRD §7.1](../../../docs/2_architecture/TRD.md#71-schema--authoritative-sql), [SDD §3.2](../../../docs/2_architecture/SYSTEM_DESIGN.md#32-component-responsibilities)).
- `plumb/adapters/blobstore_fs.py` — `FilesystemBlobStore` implementing `BlobStore` ([TRD DATA-BLOB-1..5](../../../docs/2_architecture/TRD.md#72-content-addressed-blob-store)).
- `plumb/adapters/_schema.py` — the canonical `CREATE TABLE` / `CREATE INDEX` DDL strings (source of truth for runtime schema creation).
- `plumb/adapters/_pragmas.py` — connection-time pragma helpers (`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`).
- `plumb/config.py` — extend the existing `Settings` model with `PLUMB_DATA_DIR` resolution + first-use directory creation (mode `0700`).
- `plumb/api.py` — replace the in-memory writer singleton with `SQLiteStorageAdapter`; introduce a `BlobStore` singleton; preserve all v1 Core+API ACs.

### 1.2 What this slice does NOT deliver

- No autocapture monkey-patching — `dev/active/v1-autocapture/` (separate TRS).
- No CLI or HTTP service — separate TRSes.
- No judge adapters — separate TRS.
- No ATTACH-based `agentsview` backfill — separate TRS (uses this adapter as a target).
- No schema migrations / `plumb migrate` tool — explicitly v2 (TRD DATA-MIG-1).
- No production-grade backup, retention, or purge — user-owned (TRD DATA-RET-1, DATA-BAK-1).

### 1.3 Why this slice next

1. **Unblocks every other slice.** Autocapture flushes via `StorageWriter`; CLI/HTTP read via `StorageReader`; ATTACH adapter writes through this adapter; judge adapter writes scores via this. Every downstream slice depends on the storage seam being real.
2. **Highest correctness risk after the API.** Schema constraints, foreign-key cascade, WAL durability under SIGKILL, and stalled-run sweeps must all be specified before any other I/O code lands.
3. **Specifiable end-to-end.** The DDL is canonical from TRD §7.1; no further design ambiguity. Acceptance criteria are testable against a real SQLite file in `tmp_path`.
4. **Performance gate.** This is the slice where `NFR-Perf-2` (run close ≤ 50 ms with 100 spans) is first measurable. Failing it here means the rest of the system inherits the regression.

### 1.4 Anchor TRD/SDD references

| TRD/SDD section | What it constrains here |
|---|---|
| TRD §7.1 | Authoritative DDL, CHECK constraints, indexes |
| TRD §7.2 | Blob layout, mode bits, immutability via `O_CREAT\|O_EXCL` |
| TRD §7.3 | Data-directory layout under `$PLUMB_DATA_DIR` |
| TRD NFR-Perf-2 | Run close p95 ≤ 50 ms for ≤ 100 spans |
| TRD NFR-Perf-3 | `journal_mode=WAL`, `synchronous=NORMAL`, `busy_timeout=5000` |
| TRD NFR-Perf-4 | Span buffering + single-transaction batched INSERT on close |
| TRD NFR-Sec-3 | Parameterized queries only (`ruff S608`) |
| TRD NFR-Sec-5 | Blob mode `0600`; data dir mode `0700` |
| TRD NFR-Rel-2 | Flushed writes survive SIGKILL post-fsync |
| TRD NFR-Rel-4 | `CREATE TABLE IF NOT EXISTS` is idempotent |
| TRD FR-EDGE-2 | Stalled-run sweep on adapter init — runs with `end_ts IS NULL` older than 1h → `status='stalled'` |
| SDD §4.2 | Hot-path data flow: in-memory buffer → batched INSERT → single fsync |
| SDD §4.3 | Storage strategy: SQLite STRICT + WAL + content-addressed FS blob store |

---

## 2. Requirements Summary

### 2.1 Functional requirements in scope

- **FR-EDGE-2 (MUST).** On adapter init, sweep `runs WHERE end_ts IS NULL AND start_ts < now() - 1h` and UPDATE `status='stalled'`.
- **FR-CLI-1 (partial).** `plumb run stats`, `plumb score write`, `plumb example promote` will read/write through this adapter (CLI itself is out of scope; the read methods this slice exposes must be sufficient).
- **FR-SCORE-3 (MUST).** Persisted `scores` rows enforce the `value_numeric XOR value_label` CHECK at the SQL boundary in addition to the entity-level invariant from the core slice (defense in depth).

### 2.2 NFRs in scope

- **NFR-Perf-2 (MUST).** p95 run close ≤ 50 ms over 100 iterations, run with 100 spans, on the CI runner.
- **NFR-Perf-3 (MUST).** Pragmas applied on every fresh connection.
- **NFR-Perf-4 (MUST).** Single transaction, single fsync per `write_run`.
- **NFR-Perf-6 (MUST).** Cold-import budget preserved — `import plumb` MUST NOT eager-import the adapter package.
- **NFR-Sec-3 (MUST).** All SQL parameterized; `ruff S608` clean.
- **NFR-Sec-5 (MUST).** Blob files `0600`; data dir `0700`. Verified by mode-bit test.
- **NFR-Rel-2 (MUST).** Flushed writes survive SIGKILL post-fsync (verified by subprocess kill test on macOS/Linux runners).
- **NFR-Rel-4 (MUST).** Schema creation is idempotent — running adapter init twice is a no-op.
- **NFR-Use-3 (relaxed).** `mypy --strict` clean on `plumb/core/`; permissive on `plumb/adapters/` (per TRD §4.4).

### 2.3 Out-of-scope NFRs

- NFR-Sec-1, NFR-Sec-2, NFR-Sec-4, NFR-Sec-6 — secrets, log redaction, HTTP loopback, telemetry — covered by judge / HTTP / config slices.
- NFR-Rel-3 (ATTACH idempotency) — that adapter's TRS, but this adapter must expose a mechanism (`INSERT OR IGNORE` or deterministic PKs) that the ATTACH adapter can use.

---

## 3. Detailed Component Design

### 3.1 Module layout

```
plumb/
├── adapters/
│   ├── __init__.py            # package marker, no eager imports
│   ├── _schema.py             # canonical DDL strings
│   ├── _pragmas.py            # PRAGMA helpers
│   ├── storage_sqlite.py      # SQLiteStorageAdapter (StorageWriter + StorageReader)
│   └── blobstore_fs.py        # FilesystemBlobStore (BlobStore)
├── api.py                     # MODIFIED: bind real adapters as singletons
└── config.py                  # MODIFIED: data-dir resolution + creation

tests/
├── unit/adapters/             # schema DDL, pragmas, writer/reader, lifecycle, blobstore
├── integration/               # api+sqlite, api+blobstore, sigkill durability, concurrent adapters
└── perf/test_run_close_overhead.py   # NFR-Perf-2 gate
```

### 3.2 `_schema.py` — canonical DDL

A single module exporting:

```python
SCHEMA_VERSION: int = 1                  # matches PRAGMA user_version
DDL_STATEMENTS: tuple[str, ...] = (...)  # the four CREATE TABLE + indexes
```

The `DDL_STATEMENTS` tuple is **byte-identical** to TRD §7.1 (verified by a test that diffs the canonical TRD block against `DDL_STATEMENTS`). `IF NOT EXISTS` on every CREATE so re-init is idempotent (NFR-Rel-4).

### 3.3 `_pragmas.py` — connection-time pragmas

```python
def apply_pragmas(conn: sqlite3.Connection) -> None: ...
def verify_pragmas(conn: sqlite3.Connection) -> None: ...
```

Settings applied:
- `PRAGMA journal_mode=WAL` (assert returned mode == `'wal'`)
- `PRAGMA synchronous=NORMAL`
- `PRAGMA busy_timeout=5000`
- `PRAGMA foreign_keys=ON`
- `PRAGMA temp_store=MEMORY` *(opt — keeps temp tables off disk; explicitly allowed by TRD silence)*

Idempotent — safe to call on a connection where some pragmas are already set.

### 3.4 `storage_sqlite.py` — `SQLiteStorageAdapter`

#### 3.4.1 Class signature

```python
class SQLiteStorageAdapter:
    """Implements StorageWriter + StorageReader against a single SQLite file.

    Single persistent connection per process (resolved decision Q2).
    Owns: pragmas, schema creation, stalled-run sweep, batched run-close writes.
    """

    def __init__(
        self,
        db_path: Path,
        *,
        clock: Clock,
        stalled_threshold_seconds: int = 3600,
    ) -> None: ...

    # StorageWriter
    def write_run(self, run: Run, spans: Sequence[Span]) -> None: ...
    def write_score(self, score: Score) -> None: ...
    def write_example(self, example: Example) -> None: ...

    # StorageReader
    def get_run(self, run_id: str) -> Run | None: ...
    def list_runs(self, *, since=None, task_id=None, kind=None, limit=100) -> list[Run]: ...
    def get_spans_for_run(self, run_id: str) -> list[Span]: ...
    def get_scores_for_run(self, run_id: str) -> list[Score]: ...
    def list_examples(self, *, task_id=None, active=None) -> list[Example]: ...

    # Lifecycle
    def close(self) -> None: ...
    def __enter__(self) -> "SQLiteStorageAdapter": ...
    def __exit__(self, *exc) -> None: ...
```

#### 3.4.2 `__init__` flow

1. Resolve `db_path`; ensure parent dir exists (mode `0700`) — delegated to `config.ensure_data_dir()`.
2. Open `sqlite3.Connection(db_path, isolation_level=None, check_same_thread=False, timeout=5.0)`.
3. `apply_pragmas(conn)`.
4. Run `DDL_STATEMENTS` inside a single transaction (idempotent via `IF NOT EXISTS`).
5. `PRAGMA user_version` — read; if 0, set to `SCHEMA_VERSION`; if non-zero and != `SCHEMA_VERSION`, raise `StorageError`.
6. **Sweep stalled runs** (FR-EDGE-2): one parameterized UPDATE; logs at INFO with the count.
7. `chmod 0o600` on the `plumb.db` file (defense-in-depth alignment with blob mode bits).
8. Stash `clock`, `db_path`, `stalled_threshold_seconds` on `self`.

#### 3.4.3 `write_run` flow (NFR-Perf-2 hot path)

```
BEGIN IMMEDIATE
  INSERT INTO runs(...) VALUES (?, ?, ..., ?)        -- 1 row, ~16 params
  -- batched span insert via executemany:
  INSERT INTO spans(...) VALUES (?, ?, ..., ?)       -- N rows
COMMIT                                                -- 1 fsync per NFR-Perf-4
```

- Serialization: tz-aware UTC `datetime` → ISO-8601 string; enums → `.value`; `None` for nullable columns.
- Spans inserted via `executemany` with rows pre-built as tuples.
- On any `sqlite3.Error`, the transaction is rolled back and the error is wrapped in `StorageError(...)` and re-raised. **`plumb.api` catches `StorageError` per NFR-Rel-1**; this adapter does not swallow.

#### 3.4.4 `write_score` and `write_example`

Single-row INSERT per call. No buffering — these arrive one at a time from CLI / `add_score` flush paths. Same parameterization rules. Same `StorageError` wrapping.

#### 3.4.5 Reader methods

- All readers open a fresh cursor on the persistent connection, execute a parameterized SELECT, and rehydrate via private `_row_to_*` helpers.
- `list_runs`: `ORDER BY start_ts DESC LIMIT ?`. Filter combinators add `AND` clauses; values bind via `?` placeholders only.
- `kind` filter pre-validated against `RunKind` (raises `ValidationError` before SQL).
- `row_factory = sqlite3.Row` for clarity in `_row_to_*`.

#### 3.4.6 Connection lifecycle

- **Single persistent connection per adapter instance** (resolved decision Q2). Created in `__init__`, closed via `close()` or context-manager exit.
- `check_same_thread=False`: WAL allows concurrent readers; writers serialize via SQLite's busy-timeout. plumb is single-process anyway.

### 3.5 `blobstore_fs.py` — `FilesystemBlobStore`

#### 3.5.1 Class signature

```python
class FilesystemBlobStore:
    def __init__(self, root: Path) -> None: ...
    def put(self, content: bytes) -> str: ...           # returns 64-char sha256 hex
    def get(self, sha256_hex: str) -> bytes: ...        # raises BlobNotFoundError if missing
    def exists(self, sha256_hex: str) -> bool: ...      # convenience for ATTACH adapter
```

#### 3.5.2 `put` algorithm (NFR-Sec-5, DATA-BLOB-3)

```
digest = hashlib.sha256(content).hexdigest()
target = root / digest[:2] / digest[2:]
target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

try:
    fd = os.open(target, O_CREAT|O_EXCL|O_WRONLY, 0o600)
except FileExistsError:
    return digest                  # idempotent — same hash ⇒ same content

try:
    os.write(fd, content)
    os.fsync(fd)
finally:
    os.close(fd)
return digest
```

`O_EXCL` is the atomic primitive for safe concurrent `put`. `os.fsync(fd)` per blob is fine — blob writes happen at most once per unique content.

#### 3.5.3 `get` flow

1. Validate `sha256_hex` shape (64 lowercase hex chars). `ValidationError` on shape failure.
2. Read file bytes; `BlobNotFoundError(sha256_hex)` on `FileNotFoundError`.
3. **No hash re-verification on read** — files are immutable on disk; integrity-on-read is deferred (see deferred-features.md).

#### 3.5.4 Mode-bit invariants

- Root dir: `0700`. Each fan-out subdir: `0700`. Each blob file: `0600`.
- Verified by `stat().st_mode & 0o777` unit test (POSIX-only; Windows skip).

### 3.6 `config.py` extensions

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="PLUMB_")
    data_dir: Path = Field(default_factory=lambda: Path.home() / ".plumb")
    log_level: str = "WARNING"
    autocapture: bool = True


def ensure_data_dir(settings: Settings | None = None) -> Path:
    """Resolve PLUMB_DATA_DIR; create with mode 0700 on first use; return absolute Path."""
```

`ensure_data_dir`:
- Idempotent. If the dir exists, leaves mode bits alone (don't downgrade if user widened them).
- If creating, uses `mkdir(mode=0o700, parents=True, exist_ok=True)` then explicit `os.chmod(path, 0o700)` to defeat permissive umasks.
- Returns absolute, resolved Path.

### 3.7 `api.py` integration

The v1 Core+API slice declared module-level singletons that tests monkeypatch. This slice replaces them at first use:

```python
# plumb/api.py (additions)
_storage: SQLiteStorageAdapter | None = None
_blobstore: FilesystemBlobStore | None = None

def _init_storage_singletons() -> None:
    """Lazy: invoked on first `run(...)` call. Allows tests to monkeypatch first."""
    global _storage, _blobstore
    if _storage is not None:
        return
    settings = get_settings()
    data_dir = ensure_data_dir(settings)
    _storage = SQLiteStorageAdapter(data_dir / "plumb.db", clock=_clock)
    _blobstore = FilesystemBlobStore(data_dir / "blobs")
```

Tests continue to monkeypatch `plumb.api._storage` (and now `plumb.api._blobstore`) with fakes; the lazy guard means production code uses real adapters automatically. **No `RunHandle` API changes.**

---

## 4. API Specifications

### 4.1 No new public Python surface

Adapters are **internal**. They satisfy `plumb.core.ports` Protocols but are not re-exported from `plumb.__init__`. Users instrument via `plumb.run`; they never construct an adapter directly.

For type hints, advanced users may import:

```python
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.adapters.blobstore_fs import FilesystemBlobStore
```

These are stable as the v1.x major-version contract; breaking changes = v2.

### 4.2 No HTTP / CLI in this slice

`plumb.cli`, `plumb.http` deferred. Their TRSes will consume `StorageReader` from this adapter.

### 4.3 Error surface (raised by adapter, caught by `plumb/api.py`)

| Raised | Cause |
|---|---|
| `StorageError` | Any `sqlite3.Error` during write or read — wrapped with original `__cause__` |
| `StorageError` | Schema-version mismatch on init |
| `BlobNotFoundError` | `get(hex)` for a missing file |
| `ValidationError` | Malformed `sha256_hex` shape on `BlobStore.get`; bad enum value on `list_runs(kind=...)` |

`plumb/api.py` catches `PlumbError` (parent class), logs WARNING, swallows per NFR-Rel-1.

---

## 5. Database Design

### 5.1 Schema

Exactly the four tables from TRD §7.1. `_schema.py` holds them as a `tuple[str, ...]` of CREATE statements. **No additions, no edits.** Any schema change = v2 major-version bump per TRD DATA-MIG-1.

### 5.2 `PRAGMA user_version`

- v1 sets `PRAGMA user_version = 1`.
- On adapter init: read; if `0`, set to `1` (first-time DB); if `1`, no-op; otherwise raise `StorageError`.
- Migration tripwire — a SQLite db touched by future v2 plumb fails loudly when v1 plumb opens it.

### 5.3 Indexes

All 13 indexes from TRD §7.1, no additions. Sized for ≤ 10k runs / ≤ 100k spans expected over v1's life (PRD Tier-1: ≥ 30 runs at v1 ship; 100× margin).

### 5.4 Data access patterns

| Method | Query shape | Index used |
|---|---|---|
| `write_run` | INSERT runs + executemany INSERT spans | n/a |
| `write_score` | INSERT scores | n/a |
| `write_example` | INSERT examples | n/a |
| `get_run(id)` | `SELECT * FROM runs WHERE run_id=?` | PK |
| `list_runs(...)` | `SELECT ... WHERE ... ORDER BY start_ts DESC LIMIT ?` | `idx_runs_task_start` / `idx_runs_kind_start` |
| `get_spans_for_run(id)` | `SELECT * FROM spans WHERE run_id=?` | `idx_spans_run` |
| `get_scores_for_run(id)` | `SELECT * FROM scores WHERE run_id=?` | `idx_scores_run_metric` |
| `list_examples(...)` | `SELECT * FROM examples WHERE ...` | `idx_examples_task_active` |
| Stalled-run sweep | `UPDATE runs SET status='stalled' WHERE end_ts IS NULL AND start_ts < ?` | full scan acceptable at v1 scale |

EXPLAIN QUERY PLAN spot-checks live in `tests/integration/test_query_plans.py` (informational, not blocking).

### 5.5 Migration strategy

**None in v1.** Adapter init refuses to open a db with a different `user_version`. The `plumb migrate v1-to-v2` tool is v2 work.

---

## 6. Algorithm & Logic Design

### 6.1 Stalled-run sweep (FR-EDGE-2)

```
threshold_iso = (clock.now() - timedelta(seconds=stalled_threshold_seconds)).isoformat()

UPDATE runs
SET status = 'stalled'
WHERE end_ts IS NULL
  AND status NOT IN ('stalled', 'aborted', 'failure', 'success')
  AND start_ts < ?              -- threshold_iso
```

- Status-NOT-IN guard is defensive — `end_ts IS NULL` should already imply non-terminal status, but explicit is safer.
- ISO-8601 lex order = chronological order under tz-aware UTC with consistent precision.
- Logs at INFO: `"Stalled-run sweep marked N runs as 'stalled' (threshold=...)"`.

### 6.2 `write_run` algorithm (hot path; NFR-Perf-2)

```
run_row     = _run_to_row(run)
span_rows   = [_span_to_row(s) for s in spans]

with conn:                                   # implicit BEGIN/COMMIT or ROLLBACK on error
    conn.execute(INSERT_RUN_SQL, run_row)
    if span_rows:
        conn.executemany(INSERT_SPAN_SQL, span_rows)
```

`with conn:` triggers a single COMMIT (one fsync under `synchronous=NORMAL`) on success and ROLLBACK on exception. Pre-building rows out of the transaction minimizes lock-held time.

### 6.3 Cold-import preservation (NFR-Perf-6)

- `plumb/__init__.py` does NOT import from `plumb.adapters`. The `_init_storage_singletons` helper imports lazily inside the function body.
- `plumb/adapters/__init__.py` is an empty package marker.
- Re-asserted by `tests/perf/test_cold_import.py` (already in core slice) after this slice lands.

---

## 7. Error Handling & Edge Cases

| Scenario | Behavior |
|---|---|
| `db_path` parent dir does not exist | `ensure_data_dir()` creates it (mode `0700`); no error |
| `db_path` parent dir read-only | `sqlite3.OperationalError` → `StorageError`; `plumb.api` swallows per NFR-Rel-1 |
| Schema-version mismatch | `StorageError("Schema version mismatch: db=N expected=1")` at init |
| `INSERT` violates CHECK | `IntegrityError` → `StorageError`; unreachable in practice (entity invariants pre-validate) |
| `INSERT` violates FK (orphan span) | `IntegrityError` → `StorageError`; unreachable in practice (run inserted in same tx) |
| Disk full during `write_run` | `OperationalError` → `StorageError`; tx auto-rolled back |
| SIGKILL between BEGIN and COMMIT | Buffered writes lost; no partial run row. FR-EDGE-2 sweep not relevant (no row exists) |
| SIGKILL after COMMIT, before next write | Committed data durable per WAL + fsync (NFR-Rel-2) |
| Process opens DB while another holds writer lock | `busy_timeout=5000` retries 5s; otherwise `OperationalError` → `StorageError` |
| `write_run` with `spans=[]` | Valid (FR-EDGE-3); insert run, skip executemany |
| `BlobStore.put` race: same content from two processes | `O_EXCL` makes one win; loser catches `FileExistsError`, returns digest |
| `BlobStore.get` for missing file | `BlobNotFoundError(hex)` |
| `BlobStore.put` of empty bytes | Valid; `e3b0c44...`; size 0 OK |
| `list_runs(kind="invalid")` | Pre-validated against `RunKind`; `ValidationError` before SQL |
| Adapter `close()` called twice | No-op (idempotent) |

**Retry strategy:** None at adapter layer. `busy_timeout` is the only retry. **Fallbacks:** None. The adapter is the source of truth.

---

## 8. Dependencies & Interfaces

### 8.1 Runtime dependencies (this slice adds nothing)

Stdlib only: `sqlite3`, `pathlib`, `os`, `hashlib`, `datetime`, `logging`, `re`, `contextlib`. The `pydantic` / `pydantic-settings` already pulled in by the core slice cover `Settings`. **No new third-party packages.**

### 8.2 Internal interfaces

- **Provides:** `StorageWriter`, `StorageReader`, `BlobStore` Protocol implementations consumed by `plumb/api.py`, future `plumb/cli.py`, future `plumb/http.py`, future `plumb/adapters/agentsview_attach.py`, future `plumb/adapters/judge_*.py`.
- **Consumes:** `plumb.core.entities`, `plumb.core.ports.Clock`, `plumb.core.errors`.

### 8.3 Test-only

`pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis` (already pulled). No new mocks; tests use real SQLite files in `tmp_path`.

---

## 9. Security Considerations

### 9.1 SQL injection prevention (NFR-Sec-3)

All SQL uses `?` placeholders. DDL strings in `_schema.py` are static. Filter values bind via params; column names are baked into query strings. Filter enums (`kind`, `active`) pre-validated against entity enums. `ruff S608` enabled in `pyproject.toml`; CI fails on string-concat SQL.

### 9.2 File-system permissions (NFR-Sec-5)

- `$PLUMB_DATA_DIR` created mode `0700`; explicit `os.chmod` after `mkdir` to defeat permissive umasks.
- Blob files mode `0600`; fan-out dirs mode `0700` — verified by mode-bit unit test.
- `plumb.db`, `plumb.db-wal`, `plumb.db-shm` — TRD does not mandate `0600`, but for defense-in-depth this slice explicitly `chmod 0o600` on `plumb.db` after creation. WAL/SHM files inherit umask (acceptable; SQLite manages them).

### 9.3 No PII leakage in errors

`StorageError` messages may include `db_path` (filesystem path; non-secret) but never row payload content. `BlobNotFoundError(hex)` includes only sha256 hex (irreversible). Tests assert error messages contain no control characters or unbounded user content.

### 9.4 Deferred to other slices

Secrets (NFR-Sec-1, NFR-Sec-2) → judge slice. HTTP loopback (NFR-Sec-4) → HTTP slice. Telemetry (NFR-Sec-6) → n/a (we do nothing outbound).

---

## 10. Testing Strategy

### 10.1 Coverage targets

| Module | Target |
|---|---|
| `plumb/adapters/_schema.py` | ≥ 90% |
| `plumb/adapters/_pragmas.py` | ≥ 95% |
| `plumb/adapters/storage_sqlite.py` | ≥ 90% |
| `plumb/adapters/blobstore_fs.py` | ≥ 95% |
| `plumb/config.py` (additions) | ≥ 90% |

Slice-wide: **≥ 85%** (project-wide gate is 75%; this slice is more I/O-heavy than core but still highly testable).

### 10.2 Test categories

- **Unit (`tmp_path` SQLite):** schema DDL parses, pragmas applied, CRUD round-trip per entity, CHECK enforcement, FK cascade, list filters, stalled-run sweep, reader rehydration matches written entities byte-for-byte.
- **Property (Hypothesis):** generate Runs+Spans, write+read, assert equality. Generate Scores, assert XOR enforcement at SQL boundary.
- **Integration:** full `@run(...)` cycle using real adapters (no fakes). Async variant. Nested-run variant produces correct `parent_run_id`.
- **Durability (subprocess):** spawn child Python, kill mid-run via `os.kill(pid, signal.SIGKILL)` after sentinel write, parent re-opens DB, asserts data intact. macOS-14 + ubuntu-24.04. Windows skip.
- **Performance:** `tests/perf/test_run_close_overhead.py` — 100-span run close, p95 ≤ 50 ms over 100 iters on CI runner.

### 10.3 Fakes / fixtures

- `tmp_db_adapter`: `tmp_path / "plumb.db"`, fresh `SQLiteStorageAdapter` with `FakeClock`, `.close()` on teardown.
- `tmp_blobstore`: `tmp_path / "blobs"`, fresh `FilesystemBlobStore`.
- `configured_api_real`: monkeypatches `plumb.api._storage` and `plumb.api._blobstore` with the two above; yields an API writing to a real-but-isolated DB.

### 10.4 Acceptance criteria coverage

| TRD AC | Test |
|---|---|
| AC-SCHEMA-1 (zero migrations after Week 4) | `test_storage_lifecycle.py::test_init_idempotent_on_existing_db_v1` |
| AC-SCHEMA-2 (judge drift guard — `scorer_version` on every row) | `test_storage_writer.py::test_score_requires_scorer_version_at_sql_layer` |
| AC-SCHEMA-3 (offline → online link via `examples.origin_run_id`) | `test_storage_writer.py::test_example_origin_run_id_fk_round_trip` |
| AC-PERF-2 (run close ≤ 50 ms / 100 spans p95) | `tests/perf/test_run_close_overhead.py` |
| AC-REL-1 (storage-failure swallowing, partial) | `tests/integration/test_api_with_sqlite.py::test_storage_error_does_not_raise_into_caller` |
| AC-REL-2 (SIGKILL durability) | `tests/integration/test_sigkill_durability.py` |

(AC-API-*, AC-INT-*, AC-SEC-* outside this slice's scope.)

### 10.5 Mocking policy

- **Time:** `FakeClock` from core slice's `conftest.py` — no `freezegun`.
- **Filesystem:** `tmp_path` for DB and blob root. **No SQLite `:memory:`** for integration / durability tests — `:memory:` does not exercise WAL or fsync; allowed only in unit tests targeting query shape.
- **Subprocess:** stdlib `subprocess` for the SIGKILL test; no third-party harness.

---

## 11. Performance Considerations

### 11.1 Hot-path budgets

| Operation | Budget | Strategy |
|---|---|---|
| `__init__` (cold; first run of process) | ≤ 20 ms | Single CONNECT + 14 DDL stmts + 1 sweep UPDATE |
| `write_run` for 100-span run | ≤ 50 ms p95 | `executemany` batched INSERT, single transaction, single fsync |
| `write_score` | ≤ 5 ms p95 | Single-row INSERT |
| `write_example` | ≤ 5 ms p95 | Single-row INSERT |
| `BlobStore.put` for ≤ 10 KB | ≤ 5 ms p95 | One `O_CREAT\|O_EXCL` + write + fsync |
| `get_run` | ≤ 1 ms p95 | PK lookup |

### 11.2 Memory

Adapter holds one `sqlite3.Connection`; SQLite cache size at default (~2 MB). `executemany` builds row tuples in Python — for 100 spans of typical shape that's ~50 KB transient. Blob store streams writes; no full-content buffering beyond the `bytes` argument the caller already has.

### 11.3 Concurrency

WAL + `busy_timeout=5000` handles SQLite's "one writer at a time" naturally for single-process posture. `check_same_thread=False` + connection-level lock from SQLite is sufficient for multi-thread; the API layer's contextvars guarantee no two threads write to the same `RunHandle`. Multi-process (e.g., `plumb run stats` while a `@run` script runs) supported via WAL.

### 11.4 Caching

No application-level row cache. SQLite's page cache is the cache. `get_settings()` from core slice already memoizes env-var reads via `lru_cache`.

### 11.5 Monitoring

None. Library, no runtime surface. Stalled-sweep INFO log is the closest thing.

---

## 12. Pending Decisions & Clarifications

All non-trivial decisions for this slice were resolved at TRS authoring time per user direction (recommendations accepted on 2026-04-26):

| # | Decision | Resolution |
|---|---|---|
| 1 | Blob store: separate adapter or bundled with SQLite adapter? | **Separate** — `FilesystemBlobStore` distinct from `SQLiteStorageAdapter`; matches ports-and-adapters layout |
| 2 | Connection lifecycle: persistent or per-operation? | **Single persistent connection per adapter instance**; pragmas applied once; closed on `.close()` or context-manager exit |
| 3 | Stalled-run sweep timing: `__init__` or first write? | **Sweep on `__init__`** — one cheap UPDATE per process start; semantically aligned with FR-EDGE-2 "on next startup" |
| 4 | `plumb.db` file mode | **Explicit `chmod 0o600` after first creation** to match `0600` posture of the rest of `$PLUMB_DATA_DIR` |
| 5 | Schema-version check failure mode | **Hard fail** with `StorageError` on adapter init; never auto-migrate, never silently downgrade |
| 6 | Empty-blob handling | **Allow** — sha256 of empty bytes is well-defined; no special case needed |
| 7 | `:memory:` SQLite usage | **Unit tests only** for query-shape work; integration / durability tests use `tmp_path` for real WAL semantics |

**Open for user input only if user wants to revisit any of the above.** Otherwise: Phase 1 may begin.

---

## 13. Implementation Phases

Full task breakdown with effort, files, AC checklists, and dependencies is in [`v1-storage-adapter-tasks.md`](./v1-storage-adapter-tasks.md). Summary:

| Phase | Objective | Effort |
|---|---|---|
| **1** | Adapter package skeleton + canonical DDL + pragma helpers | S+M+S |
| **2** | `FilesystemBlobStore` (put/get/exists, mode bits, concurrency) | M+S+S |
| **3** | `SQLiteStorageAdapter` writes (init, `write_run`, scores, examples) | M+M+S+S |
| **4** | `SQLiteStorageAdapter` reads (single-row + list) | M+M |
| **5** | Stalled-run sweep + multi-adapter coexistence | S+M |
| **6** | `plumb.config` + `plumb.api` integration (lazy real-adapter init) | S+M+M |
| **7** | Durability (SIGKILL) + performance (run close) gates | L+M |
| **8** | Doc updates + slice archive | S+S+S |

Phases are sequential; within a phase, tasks may run in declared order.

---

## 14. Forward Pointers (Other TRSes)

| Follow-up TRS | Consumes from this slice |
|---|---|
| `v1-autocapture/` | `RunHandle.add_span` → `StorageWriter.write_run` (no direct adapter touch) |
| `v1-cli/` | `StorageReader.{get_run, list_runs, get_spans_for_run, get_scores_for_run, list_examples}` |
| `v1-http/` | `StorageReader` (same set as CLI) |
| `v1-judge-adapters/` | `StorageWriter.write_score` for judge results |
| `v1-attach-adapter/` | Direct SQL on the adapter's connection (or new `attach_database` method); `INSERT OR IGNORE` on dedup PK |

---

*End of TRS v1 — `plumb/adapters/storage_sqlite.py` + `plumb/adapters/blobstore_fs.py` storage slice.*

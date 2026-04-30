# Code Review — `v1-storage-adapter` Implementation

**Reviewer persona:** Code Reviewer
**Review date:** 2026-04-27
**Scope reviewed:**
- `plumb/adapters/__init__.py`
- `plumb/adapters/_schema.py`
- `plumb/adapters/_pragmas.py`
- `plumb/adapters/storage_sqlite.py`
- `plumb/adapters/blobstore_fs.py`
- `plumb/api.py` (integration delta)
- `plumb/config.py` (integration delta)
- `plumb/core/ports.py` (Protocol delta)

**Reference docs:** TRD §7, SDD §3.2/§4.3, [`v1-storage-adapter-plan.md`](./v1-storage-adapter-plan.md), [`v1-storage-adapter-context.md`](./v1-storage-adapter-context.md), [`v1-storage-adapter-tasks.md`](./v1-storage-adapter-tasks.md).

---

## Executive Summary

The slice is **well-implemented overall** and meets the TRS contract: ports-and-adapters separation is clean, DDL is byte-faithful to TRD §7.1, the two-phase write protocol (`open_run` / `finalize_run`) is a thoughtful upgrade that resolves FR-GRAPH-1 without leaking concerns into the API, and durability/perf gates are wired and passing per the tasks file. Coverage targets met (94% adapter coverage; p95 ~6 ms — well under the 50 ms budget).

That said, there are a small number of **correctness drift issues** between entity model, DDL, and serialization that I want to flag — none are showstoppers in normal flow, but each violates the "data round-trip is identity" property the TRS implicitly relies on, and they will confuse downstream consumers (CLI, HTTP, judge slices). There are also a few **defense-in-depth gaps** vs the TRS spec (e.g., `verify_pragmas` is defined but never called; `chmod` of fan-out subdir is invoked redundantly on every `put`).

| Severity | Count | Themes |
|---|---|---|
| Critical | 0 | — |
| Important | 5 | span tokens lossy round-trip; Example field drift; Connection lock semantics; FR-EDGE-2 stalled-status handling for non-pending; verify_pragmas dead code |
| Minor | 7 | Redundant chmod on every put; sqlite3.IntegrityError caught twice; `_NoopStorageWriter` unused fields; `# noqa: S608` mis-applied; etc. |

The slice is **mergeable as archived** (it has been merged) but the issues below should be tracked as follow-up work — particularly the span-tokens round-trip, which silently loses `tokens_out` data on read.

---

## Critical Issues (must fix)

*None.* No data-corruption, security, or system-failure issues identified.

---

## Important Improvements (should fix)

### I-1. `Span.tokens_in` / `tokens_out` round-trip is lossy

**File:** [plumb/adapters/storage_sqlite.py:73-92](plumb/adapters/storage_sqlite.py#L73), [plumb/adapters/storage_sqlite.py:144-168](plumb/adapters/storage_sqlite.py#L144)

The `spans` table has a single `tokens INTEGER` column (TRD §7.1). The entity, however, has both `tokens_in` and `tokens_out`. On write:

```python
tokens = (span.tokens_in or 0) + (span.tokens_out or 0)
```

On read:
```python
if row["tokens"] is not None:
    tokens_in = row["tokens"]   # full sum is surfaced as tokens_in
# tokens_out always None on read
```

**Impact:**
- A span written with `tokens_in=10, tokens_out=20` reads back as `tokens_in=30, tokens_out=None`.
- The Hypothesis property test in Phase 4 (`test_storage_reader.py::test_round_trip_run_span`) is supposed to assert byte-identical round-trip per [TRS §10.2](./v1-storage-adapter-plan.md#102-test-categories). If it actually passes, the strategy is probably only generating one of the two (i.e., the property is silently weaker than the spec claims).
- This is **exactly the smell** the [Agent Working Rules §1](../../../CLAUDE.md#1-tests-assert-behavior--never-edit-a-test-to-make-it-green) warns about — round-trip equality assertion likely weakened to accommodate the schema.

**Why the production code is wrong, not the test (in spirit):**
The TRD schema is authoritative and only specifies `tokens` (singular). The entity layer carries finer-grained data than the wire format. The right fix is one of:
1. **Collapse the entity** to a single `tokens: int | None` field (matches schema; loses input/output split — discuss product implications).
2. **Split the column** in DDL (`tokens_in`, `tokens_out`) — but that's a v2 schema change per DATA-MIG-1, off the table for v1.
3. **Document the contract** clearly: "spans persist total tokens only; the in/out split is informational at the entity layer and not durable." Update the property test to assert `read.tokens_in == write.tokens_in + write.tokens_out` (sum) and `read.tokens_out is None`. This is consistent with what's implemented today but needs to be visibly documented.

**Recommendation:** Option 3 in v1 (cheapest, no schema change), and add a docstring on `Span` and `_row_to_span` explaining the asymmetry. Add a deferred-features.md entry for option 1 or 2 in v2.

**Severity reasoning:** Important, not Critical, because no data is corrupted *on disk* (the sum is what TRD specified). But the user-visible entity API silently lies, and consumers (CLI `run stats`, HTTP) will display bogus splits.

---

### I-2. `Example` ↔ schema field drift: `rubric`, `origin_run_id`, `tags`

**File:** [plumb/adapters/storage_sqlite.py:109-120](plumb/adapters/storage_sqlite.py#L109), [plumb/adapters/storage_sqlite.py:185-195](plumb/adapters/storage_sqlite.py#L185)

The `examples` table has columns `rubric` and `origin_run_id` (TRD §7.1; AC-SCHEMA-3 explicitly relies on `origin_run_id`). The Python `Example` entity has neither — and has a `tags` field that the schema doesn't.

```python
def _example_to_row(example: Example) -> tuple[Any, ...]:
    return (
        ...
        None,  # rubric — not in entity; stored as NULL
        ...
        None,  # origin_run_id — not in entity
        ...
    )
```

```python
def _row_to_example(row: sqlite3.Row) -> Example:
    return Example(
        ...
        tags=None,
    )
```

**Impact:**
- **AC-SCHEMA-3** (offline → online link via `examples.origin_run_id`) is checked off in the tasks file — but with `_example_to_row` hardcoding `None`, **no caller can ever populate `origin_run_id`** through this adapter. The acceptance test must be either:
  - directly inserting via raw SQL (bypassing the adapter), or
  - asserting on the column shape only (not the data flow).

  Either way, the *real* offline→online link the AC describes does not work end-to-end. This deserves a follow-up issue.
- The `rubric` column is similarly dead — it can only ever be `NULL` from the adapter path.
- The entity's `tags` field is a phantom — never persisted, never read.

**Recommendation:**
- Add `origin_run_id: str | None` and `rubric: str | None` to `Example` entity (frozen dataclass; default `None` so existing tests don't churn). Pipe them through `_example_to_row` / `_row_to_example`.
- Decide whether `tags` is something v1 supports. If yes, add to schema (= v2 schema change, deferred). If no, **remove from the entity** rather than keeping a phantom field.

**Severity:** Important. AC-SCHEMA-3's claimed-green status is misleading until this is fixed. No data corruption, but a meaningful feature gap.

---

### I-3. `check_same_thread=False` + single `sqlite3.Connection` is not thread-safe for writers

**File:** [plumb/adapters/storage_sqlite.py:270-275](plumb/adapters/storage_sqlite.py#L270)

```python
self._conn = sqlite3.connect(
    str(self._db_path),
    isolation_level=None,
    check_same_thread=False,
    ...
)
```

The TRS asserts ([§3.4.6](./v1-storage-adapter-plan.md#346-connection-lifecycle)):

> `check_same_thread=False`: WAL allows concurrent readers; writers serialize via SQLite's busy-timeout. plumb is single-process anyway.

This is **partially true and partially wrong**. `check_same_thread=False` lets multiple Python threads share the connection — but *not* simultaneously. Python's `sqlite3` module serializes access internally via a `Lock` on the connection only when both threads use the same `Cursor`; concurrent `execute` from two threads on the same connection can interleave and produce `OperationalError: cannot start a transaction within a transaction` or worse. This is a known SQLite-Python footgun.

The contextvars argument in the TRS ("the API layer's contextvars guarantee no two threads write to the same `RunHandle`") is **not** the relevant invariant — the relevant invariant is "no two threads concurrently call `_storage_writer.{open_run,finalize_run,write_score,write_example}`." Two `with run(...)` blocks running in two threads writing to *different* runs will both contend on this single connection.

**Concrete failure mode:** Thread A is mid-`finalize_run` (BEGIN issued, executemany running). Thread B calls `write_score`. Thread B's `INSERT INTO scores` becomes part of A's open transaction (because `isolation_level=None` + `with conn:` uses the *connection's* transaction, not the thread's). On A's COMMIT, B's row is silently included — a transactional-isolation violation between unrelated logical operations.

**Recommendation (any of):**
1. Use a `threading.Lock` around all writer methods (`open_run`, `finalize_run`, `write_score`, `write_example`). Cheap; correct; preserves single-connection design.
2. Move to a thread-local connection pool — one `sqlite3.Connection` per thread, all opened against the same DB file. Each thread's `apply_pragmas` runs once. Exposes a contextmanager `_with_conn()` everywhere.
3. Document the constraint as "the adapter is not safe for concurrent multi-thread writers; use one adapter per thread or one thread per process." This is honest and defers the work — but is a regression vs. what the TRS implies.

**Severity:** Important. Today's tests don't exercise the broken path (the integration test uses one event-loop thread; the durability test uses one process), but autocapture or any future async worker pool will hit this. **The risk window is small now and grows fast as soon as autocapture lands.**

---

### I-4. FR-EDGE-2 sweep also marks already-`success`/`failure`/`aborted` rows when their `end_ts` is NULL — but those are unreachable, so the guard is just dead code (or it isn't, in which case it's masking a bug)

**File:** [plumb/adapters/storage_sqlite.py:300-321](plumb/adapters/storage_sqlite.py#L300)

```sql
UPDATE runs
SET status = 'stalled'
WHERE end_ts IS NULL
  AND status NOT IN ('stalled', 'aborted', 'failure', 'success')
  AND start_ts < ?
```

Per `_FINALIZE_RUN`, every terminal status (`success`/`failure`/`aborted`) is set together with `end_ts`. So `end_ts IS NULL AND status IN ('success', 'failure', 'aborted')` is **structurally unreachable**.

The guard is defended in the TRS ([§6.1](./v1-storage-adapter-plan.md#61-stalled-run-sweep-fr-edge-2)) as defense-in-depth. That's fine, but:

- If a future bug ever produces such a row, the sweep will silently skip it instead of fixing it. The "defense" hides the bug.
- The cleaner posture is: assert `end_ts IS NULL ⇒ status='pending'` as an invariant, and the sweep query becomes `WHERE status='pending' AND start_ts < ?`. That uses the existing `idx_runs_kind_start` only loosely — but at v1 scale (PRD Tier-1 ≥ 30 runs) it's free.

**Recommendation:** Tighten the sweep to `WHERE status='pending' AND start_ts < ?`. If the defense-in-depth posture is preferred, add a sibling `LOG.warning` for any `end_ts IS NULL AND status NOT IN ('pending')` row, so the bug surfaces instead of being masked. (And add a unit test that fails if such a row appears via `INSERT OR REPLACE`.)

**Severity:** Important. Not a live bug today but a long-term observability hazard.

---

### I-5. `verify_pragmas` is defined and tested but never called in production

**File:** [plumb/adapters/_pragmas.py:31-37](plumb/adapters/_pragmas.py#L31)

`verify_pragmas` exists, has a test, and verifies post-conditions on a connection — but `SQLiteStorageAdapter.__init__` only calls `apply_pragmas`, never `verify_pragmas`. If a future SQLite version silently rejects one of the pragmas (e.g., `journal_mode=WAL` falling back to `journal_mode=DELETE` on a network filesystem), nothing in the adapter detects it, and NFR-Perf-3 silently degrades.

**Recommendation:** Call `verify_pragmas(self._conn)` immediately after `apply_pragmas(self._conn)` in `__init__`. Cheap (4 PRAGMA reads), satisfies NFR-Perf-3 in spirit, and the existing test of `verify_pragmas` becomes load-bearing.

**Severity:** Important. The function exists for exactly this reason; not wiring it up is a missed seam.

---

## Minor Suggestions (nice to have)

### M-1. `os.chmod` on root and fan-out called on every `put`

**File:** [plumb/adapters/blobstore_fs.py:33-37](plumb/adapters/blobstore_fs.py#L33)

```python
target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
os.chmod(target.parent.parent, 0o700)  # root
os.chmod(target.parent, 0o700)  # fan-out subdir
```

Mode bits don't change between `put`s; the redundant `chmod` is two extra syscalls per blob write. At blob-store-write rates that's negligible, but it also overrides whatever the user might have set (e.g., `0o750` for a shared group). The TRS says ([§3.5.4](./v1-storage-adapter-plan.md#354-mode-bit-invariants)) "verified by `stat().st_mode & 0o777`" — i.e. enforce on creation, not on every write.

**Recommendation:** Move the explicit `chmod` calls inside the `if not exists:` path of `mkdir(... exist_ok=True)`. Use `try: mkdir(... exist_ok=False); chmod(...) except FileExistsError: pass` for the subdir, and chmod root only once at first `put`.

---

### M-2. `sqlite3.IntegrityError` is caught and re-raised twice

**File:** [plumb/adapters/storage_sqlite.py:401-404](plumb/adapters/storage_sqlite.py#L401) (and similar blocks)

```python
except sqlite3.IntegrityError as exc:
    raise StorageError(str(exc)) from exc
except sqlite3.Error as exc:
    raise StorageError(str(exc)) from exc
```

`IntegrityError` is a subclass of `sqlite3.Error`; the second clause already covers it, and both arms do the same thing. The double clause is dead code and obscures intent (suggests the author wanted distinct handling but didn't end up needing it).

**Recommendation:** Drop the `IntegrityError` arm; keep only `except sqlite3.Error`. Or, if distinct handling is desired (e.g., FK violations as `ValidationError`), implement it.

---

### M-3. `_NoopStorageWriter` is dead once `_init_storage_singletons` runs

**File:** [plumb/api.py:60-101](plumb/api.py#L60)

`_NoopStorageWriter` is set as the initial `_storage_writer`, then `_init_storage_singletons` overwrites it with the real `SQLiteStorageAdapter`. The only path where `_NoopStorageWriter` survives is when a test monkeypatches `_storage` to a fake before any `with run(...)` runs. The Noop class is therefore reachable only through tests that *don't* override.

**Recommendation:** Confirm the Noop class is intended for that narrow case. If yes, add a docstring example of the test pattern. If no (i.e., production code paths could ever see Noop), that's a quiet bug — `add_score` etc. would silently no-op.

---

### M-4. `# noqa: S608` on parameterized queries that don't actually trigger S608

**File:** [plumb/adapters/storage_sqlite.py:463](plumb/adapters/storage_sqlite.py#L463), [plumb/adapters/storage_sqlite.py:501](plumb/adapters/storage_sqlite.py#L501)

```python
f"SELECT * FROM runs {where} ORDER BY start_ts DESC LIMIT ?",  # noqa: S608
```

`where` is a string built from a fixed alphabet of clauses (`"task_id = ?"`, `"kind = ?"`, etc.) — values bind via `?`. Ruff's `S608` heuristic flags any f-string that looks like SQL; the `# noqa` is necessary to suppress the false positive. This is fine, but — per project policy on suppressions — add an inline comment justifying *why* it's safe:

```python
f"SELECT * FROM runs {where} ORDER BY start_ts DESC LIMIT ?",  # noqa: S608 - clauses are static; values bind via ?
```

Also relevant: the `# noqa: S608` in `_pragmas.py` is on `f"PRAGMA {name}={value}"` where `name` and `value` come from a module-level literal dict — that's *also* safe but worth the same justification comment so the suppression doesn't propagate culturally.

---

### M-5. Schema-version error message could leak schema-knowledge details

**File:** [plumb/adapters/storage_sqlite.py:298](plumb/adapters/storage_sqlite.py#L298)

```python
raise StorageError(f"Schema version mismatch: db={version} expected={SCHEMA_VERSION}")
```

This is fine — `version` is an integer, not user input. Just noting for completeness against [Plan §9.3](./v1-storage-adapter-plan.md#93-no-pii-leakage-in-errors): no PII risk here.

---

### M-6. `_dt_to_iso` raises `StorageError` for naive datetimes — but the code path should be unreachable

**File:** [plumb/adapters/storage_sqlite.py:38-43](plumb/adapters/storage_sqlite.py#L38)

```python
def _dt_to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        raise StorageError("datetime must be timezone-aware before storage")
```

Per TRS, the entity layer enforces tz-awareness (frozen dataclass `__post_init__`). The adapter check is defensive — fine. Two micro-improvements:

1. Make this a `ValidationError` instead of `StorageError`, since the cause is a malformed input, not a storage failure. `plumb.api` catches both anyway, but it's semantically cleaner.
2. Include the field name in the message (`"datetime field <name> must be timezone-aware"`) — but that requires plumbing the name through, may not be worth it.

---

### M-7. `os.chmod(self._db_path, 0o600)` after schema bootstrap — but WAL/SHM files are not chmod'd

**File:** [plumb/adapters/storage_sqlite.py:282-286](plumb/adapters/storage_sqlite.py#L282)

```python
if os.name != "nt":
    import contextlib
    with contextlib.suppress(OSError):
        os.chmod(self._db_path, 0o600)
```

[Plan §3.4.2](./v1-storage-adapter-plan.md#342-__init__-flow) and [Plan §9.2](./v1-storage-adapter-plan.md#92-file-system-permissions-nfr-sec-5) explicitly accept that WAL/SHM files inherit umask. Today the user's umask is typically `022`, producing `0644` WAL/SHM files. On a multi-user system, that means anyone reading the WAL file can see uncommitted-then-committed payloads. This was discussed in TRS §9.2 and accepted; just calling out for visibility.

**Recommendation:** Add a chmod loop for `*.db-wal`, `*.db-shm` after the DB is opened — they're created lazily by SQLite, but the path is deterministic. Or document explicitly in `getting_started.md` (already pending in Phase 8 docs) that umask matters.

---

## Architecture Considerations

### A-1. `SQLiteStorageAdapter` plays both `StorageWriter` and `StorageReader` roles

This is *fine* (and economical) for v1 — one connection, one set of pragmas, one persistent file handle. But future slices (CLI `run stats`, HTTP) will spin up `StorageReader`-only consumers in different processes (CLI is short-lived; HTTP is long-lived). The current design forces them to either:

1. Construct a full `SQLiteStorageAdapter`, paying the schema-bootstrap + stalled-sweep cost on every CLI invocation, or
2. Skip those lifecycle steps with an undocumented bypass.

**Recommendation for the next slice:** Either factor a `_BaseConnection` mixin out, or add a `read_only=True` constructor flag that:
- skips DDL bootstrap (assert schema already exists with the right `user_version`),
- skips stalled sweep,
- skips `chmod 0o600` on the DB file.

Not a v1 blocker; please track on the CLI/HTTP TRS.

### A-2. `BlobStore` Protocol does not include `exists`, but the adapter exposes it

**File:** [plumb/core/ports.py:95-99](plumb/core/ports.py#L95) vs [plumb/adapters/blobstore_fs.py:66-69](plumb/adapters/blobstore_fs.py#L66)

The `BlobStore` Protocol declares only `put` and `get`. The adapter adds `exists` as a public method — which the TRS calls out as "convenience for ATTACH adapter." Fine, but right now the Protocol and the adapter are out of sync. When the ATTACH slice arrives, it will type-hint against `BlobStore` and not see `exists`.

**Recommendation:** Either add `exists` to the Protocol, or make it a private `_exists` until ATTACH lands. Today's state is the worst-of-both — public method, not in the contract.

### A-3. Lazy adapter init in `plumb.api` is good but the test isolation story is implicit

The lazy-init guard in `_init_storage_singletons` (`if _storage is not None: return`) is correct and preserves the cold-import budget. Tests monkeypatch `_storage` and `_storage_writer` to fakes *before* calling `run(...)`. That's clean.

But two things to watch:

1. After test 1 runs the real adapter, `_storage` is set globally (process-wide). Test 2 either reuses test 1's adapter (wrong DB path!) or has to reset `_storage = None` in a fixture. Looking at the conftest (out of review scope but inferable from the tests file naming `configured_api_real`), this is presumably handled — verify in a follow-up that the fixture resets *all three*: `_storage`, `_blobstore`, `_storage_writer`.
2. The `_storage_writer = _storage` assignment in `_init_storage_singletons` ties the writer to the same instance as the reader — good. But a test that monkeypatches only `_storage_writer` (not `_storage`) leaves a mismatch. This isn't a bug, just a possible footgun for future test authors. A note in the test fixture's docstring would help.

---

## Next Steps

1. **Fix I-1 (span tokens round-trip)** — either revisit the entity model or document the asymmetry and tighten the property test. Highest priority since it silently corrupts user-observable data.
2. **Fix I-2 (Example field drift)** — add `origin_run_id` + `rubric` to the entity; remove or persist `tags`. Required for AC-SCHEMA-3 to be honestly green.
3. **Decide on I-3 (thread safety)** — pick lock vs. thread-local vs. document-the-limit. Important to land before autocapture.
4. **Wire up `verify_pragmas` (I-5)** — one-line change, enforces NFR-Perf-3.
5. **Tighten FR-EDGE-2 sweep predicate (I-4)** — surface invariant violations instead of masking them.
6. **Minor cleanups (M-1..M-7)** — bundle into a single follow-up PR; none individually merit attention.

---

**Code review saved to:** `./dev/archive/v1-storage-adapter/v1-storage-adapter-code-review.md`

---

## Implementation Status — All Findings Addressed (2026-04-29)

**I-1: Span tokens round-trip asymmetry**
- ✅ Added docstrings to `Span` and `_row_to_span` documenting the sum behavior.
- ✅ Added v2 deferred-features entry `v2 — Span tokens_in / tokens_out column split`.

**I-2: Example entity field drift**
- ✅ Added `origin_run_id: str | None` and `rubric: str | None` to `Example` entity with `_require_hex32` validation.
- ✅ Removed phantom `tags` field.
- ✅ Wired both through `_example_to_row` and `_row_to_example`.
- ✅ Added entity tests for new fields.

**I-3: Thread safety — check_same_thread=False**
- ✅ Added `self._write_lock = threading.Lock()` in `__init__`.
- ✅ Wrapped all five writer methods (`open_run`, `finalize_run`, `write_run`, `write_score`, `write_example`) with the lock.

**I-4: FR-EDGE-2 sweep predicate masking invariant**
- ✅ Tightened query from `WHERE end_ts IS NULL AND status NOT IN (...)` to `WHERE status = 'pending'`.
- ✅ Added comment explaining the invariant enforcement.

**I-5: verify_pragmas never called**
- ✅ Imported `verify_pragmas` and called it immediately after `apply_pragmas` in `__init__`.

**M-1: Redundant chmod on every put**
- ✅ Moved `os.chmod` calls to creation-only path in `blobstore_fs.py`.

**M-2: Double-caught IntegrityError (done as part of I-3)**
- ✅ Removed redundant `except sqlite3.IntegrityError` arms; all writer methods now have single `except sqlite3.Error`.

**M-3: _NoopStorageWriter docstring**
- ✅ Expanded docstring explaining test-isolation purpose.

**M-4: # noqa: S608 justifications**
- ✅ Added inline comments to all four S608 suppressions in `_pragmas.py` and `storage_sqlite.py`.

**M-6: _dt_to_iso exception type**
- ✅ Changed to raise `ValidationError` instead of `StorageError` for naive datetimes.
- ✅ Updated corresponding test.

**M-7: WAL/SHM file permissions**
- ✅ Added v1.1 deferred-features entry `v1.1 — WAL/SHM file permissions`.

**A-2: BlobStore Protocol exists() method**
- ✅ Added `exists(self, sha256_hex: str) -> bool` to `BlobStore` Protocol.
- ✅ Updated `FakeBlobStore` in ports compliance test.

**Test Results:** All 340 tests pass. Source code (`plumb/`) is ruff-clean.

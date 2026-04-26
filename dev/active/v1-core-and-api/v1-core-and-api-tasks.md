# Tasks Checklist — `plumb/core/` + `plumb/api.py`

**Companion to** [`v1-core-and-api-plan.md`](./v1-core-and-api-plan.md)
**Total tasks:** 22 across 8 phases
**Effort scale:** S = ≤ 4h, M = ≤ 1 day, L = ≤ 2 days, XL = > 2 days
**Dependency rule:** phases are sequential. Within a phase, tasks may run in declared order.

Update this file as work progresses. Mark `[x]` when each acceptance criterion is met. **Do not mark a task complete unless every box under it is checked.**

---

## Phase 1 — `src/` cleanup + `plumb/` skeleton

**Objective:** Remove the legacy Clean-Architecture scaffold; create the empty `plumb/` package layout.

### Task 1.1 — Delete legacy `src/` tree [S]

- [x] `src/` directory deleted
- [x] `tests/unit/domain/`, `tests/unit/application/` deleted
- [x] `tests/conftest.py` has no `from src.* import` lines
- [x] `pytest --collect-only` succeeds with zero collection errors
- [x] `main.py` checked for `src.*` references; updated if present

### Task 1.2 — Create `plumb/` package skeleton [S]

- [x] `plumb/__init__.py` exists with `__version__ = "0.1.0"`
- [x] `plumb/core/__init__.py`, `entities.py`, `ports.py`, `stats.py`, `errors.py` created (placeholders OK)
- [x] `plumb/api.py`, `plumb/config.py` created (placeholders OK)
- [x] `pyproject.toml` declares `packages = ["plumb"]`
- [x] `python -c "import plumb; print(plumb.__version__)"` prints `0.1.0`

### Task 1.3 — Wire `ruff` + `mypy --strict` config [S]

- [x] `pyproject.toml` has `[tool.ruff]` block (line-length, target-version 3.13)
- [x] `pyproject.toml` has `[tool.mypy]` block with `strict = true` for `plumb/core/`
- [x] `ruff check plumb/` exits 0
- [x] `mypy --strict plumb/core/` exits 0
- [x] `pyproject.toml` has `[tool.pytest.ini_options]` registering `perf` marker

**Phase 1 deliverables:**
- [x] Empty `plumb/` package importable
- [x] Legacy `src/` removed
- [x] Lint + type tooling configured

---

## Phase 2 — Entities + Errors

**Objective:** Implement frozen dataclasses with full invariant enforcement and the exception hierarchy.

### Task 2.1 — Implement `plumb/core/errors.py` [S]

- [x] `PlumbError`, `StorageError`, `BlobNotFoundError`, `ValidationError`, `JudgeError` defined
- [x] All inherit from `PlumbError` (verified by `isinstance` test)
- [x] All have docstrings
- [x] `tests/unit/core/test_errors.py` exists; tests pass
- [x] Coverage ≥ 90%

### Task 2.2 — Implement enums in `plumb/core/entities.py` [S]

- [x] `RunKind`, `RunStatus`, `SpanKind`, `SpanStatus`, `ScorerKind`, `ExampleSource` defined as `StrEnum`
- [x] Each enum value matches TRD §7.1 CHECK string literal exactly (verified by per-enum test)
- [x] `tests/unit/core/test_entities.py::test_enum_values_match_trd_check_constraints` passes

### Task 2.3 — Implement entity dataclasses [M]

- [x] `Run`, `Span`, `Score`, `Example`, `JudgeResult`, `McNemarResult` defined
- [x] All `@dataclass(frozen=True, slots=True)`
- [x] `__post_init__` enforces invariants per plan §3.2.2
- [x] Each invariant has at least one failing-input test
- [x] `dataclasses.replace(run, end_ts=...)` produces a valid new `Run`
- [x] `Score` XOR (`value_numeric` xor `value_label`) enforced; both/neither raise `ValidationError`
- [x] Hash-format invariants (32-hex IDs, 64-hex content hashes) enforced
- [x] `mypy --strict plumb/core/entities.py` clean
- [x] Hypothesis property test: valid-input round-trip
- [x] Coverage ≥ 95%

**Phase 2 deliverables:**
- [x] All entities + errors implemented
- [x] Coverage targets met
- [x] `mypy --strict plumb/core/` still clean

---

## Phase 3 — Ports + Stats

**Objective:** Declare Protocols (no implementations) and implement pure-function statistics helpers.

### Task 3.1 — Implement `plumb/core/ports.py` [S]

- [x] All six Protocols defined: `Clock`, `IdGenerator`, `StorageWriter`, `StorageReader`, `BlobStore`, `JudgeAdapter`
- [x] No imports from `plumb.adapters.*` or `plumb.api`
- [x] `mypy --strict plumb/core/ports.py` clean
- [x] `tests/unit/core/test_ports_compliance.py`: hand-built fakes satisfy each Protocol via `isinstance` (with `@runtime_checkable` decoration on Protocols that need it)

### Task 3.2 — Implement `mcnemar_paired` [M]

- [x] Function signature matches plan §3.4
- [x] Algorithm matches algorithms doc §6.3
- [x] Uses `math.erf` (no SciPy dep)
- [x] Five known-answer reference cases pass within 1e-6
- [x] Cross-check against scipy's reference values (gated behind `pytest.importorskip("scipy")`)
- [x] Raises `ValueError` if input lengths differ or `n_discordant < 1`
- [x] Hypothesis property test: p-value monotone w.r.t. `|b - c|` for fixed total

> **Note:** Reference values in algorithms doc §6.3 were incorrect for the Yates-corrected formula. Correct values (verified against `scipy.stats.chi2.sf`): b=10,c=2 → p≈0.04331; b=5,c=5 → p≈0.7518; b=20,c=0 → p≈2.152e-5; b=100,c=50 → p≈6.312e-5.

### Task 3.3 — Implement `benjamini_hochberg` [S]

- [x] Function signature matches plan §3.4
- [x] Algorithm matches algorithms doc §6.4
- [x] Three reference cases pass (doc's case 1 corrected: only p=0.01 of [0.01,0.04,0.03,0.5] is rejected)
- [x] Edge: empty input → empty output (no error)
- [x] Edge: all p-values > alpha → all False
- [x] Hypothesis property: rejected p-values are a prefix in sorted order

> **Note:** Algorithms doc §6.4 reference case 1 was wrong. For `[0.01, 0.04, 0.03, 0.5]` at α=0.05: only index 0 (p=0.01) is rejected; the BH threshold for rank 2 is 0.025 < 0.03.

**Phase 3 deliverables:**
- [x] All ports declared
- [x] McNemar + BH-FDR working with golden tests
- [x] Coverage ≥ 95% on `stats.py` (100% achieved)

---

## Phase 4 — Config

**Objective:** Implement `plumb/config.py` with `pydantic-settings`.

### Task 4.1 — Implement `Settings` + `get_settings` [S]

- [x] `Settings(BaseSettings)` with `env_prefix="PLUMB_"`, `case_sensitive=False`
- [x] Three fields: `data_dir: Path`, `log_level: str`, `autocapture: bool` (defaults per plan §3.7)
- [x] `get_settings()` is `@lru_cache(maxsize=1)`
- [x] Test: `monkeypatch.setenv("PLUMB_DATA_DIR", "/tmp/test"); get_settings.cache_clear()` produces matching settings
- [x] Test: `data_dir` resolves to `Path`, not `str`
- [x] `tests/unit/test_config.py` passes
- [x] Coverage ≥ 85% (100% achieved)

**Phase 4 deliverables:**
- [x] Env-driven config working

---

## Phase 5 — API: sync decorator + context manager

**Objective:** Ship sync `@run` and `with run(...)` with full FR/AC coverage.

> **Decisions resolved 2026-04-25** (see context §3 and §6):
> - DI pattern: module-level singletons in `plumb.api` (`_clock`, `_id_gen`, `_storage_writer`)
> - `RunHandle`: public for type hints, with `__init__` `TypeError` guard against direct construction
> - `abort()`: flushes already-buffered spans before close
> - Cold-import: warn at 200 ms, hard-fail at 400 ms

### Task 5.1 — Implement `_RunBuilder` [M]

- [ ] Mutable builder class in `plumb/api.py` (private, leading underscore)
- [ ] Holds: `run_id`, `task_id`, `kind`, `parent_run_id`, `start_ts`, `spans: list[Span]`, `scores: list[Score]`, model fields, `aborted: bool`, `abort_reason: str | None`, `status: RunStatus | None`, `end_ts: datetime | None`
- [ ] `freeze() -> Run` produces immutable `Run` with proper field mapping
- [ ] `tests/unit/api/test_run_builder.py` passes

### Task 5.2 — Implement `RunHandle` [M]

- [ ] Class wrapping `_RunBuilder` with the four user-facing methods (`add_score`, `add_span`, `set_models`, `abort`)
- [ ] Read-only properties: `run_id`, `parent_run_id`, `task_id`
- [ ] `add_score` enforces XOR validation; raises `ValidationError` on both/neither
- [ ] `add_score` returns `score_id`; `add_span` returns `span_id`
- [ ] After `abort("reason")`, subsequent `add_span`/`add_score` are no-ops, **but already-buffered spans are preserved** (decision §3.3)
- [ ] `set_models` is last-call-wins
- [ ] **Construct guard:** `RunHandle.__init__` requires non-None `_builder`; raises `TypeError("RunHandle is not user-constructible; obtain one via `with run(...) as r:`")` otherwise (decision §3.2)
- [ ] Test asserts `RunHandle()` (no args) raises `TypeError`
- [ ] Test asserts `RunHandle(_builder=None)` raises `TypeError`
- [ ] `tests/unit/api/test_run_handle.py` passes

### Task 5.3 — Implement sync `__enter__`/`__exit__` on `_RunFactory` [L]

- [ ] `__enter__` per algorithms §6.1: parent from contextvar, fallback to explicit `parent_run_id` arg, FR-EDGE-4 dedup
- [ ] `__exit__` per algorithms §6.1: status determination, builder freeze, write_run + write_score loop, NFR-Rel-1 swallow on `PlumbError`, finally-reset contextvar
- [ ] **AC** (FR-EDGE-1): `with run(): raise UserErr` re-raises `UserErr` unchanged AND writes one row with `status='failure'`, `error_type='UserErr'`
- [ ] **AC** (FR-EDGE-3): `with run(): pass` writes one row with `status='success'` and zero spans
- [ ] **AC** (FR-EDGE-5): `with run() as r: r.add_span(...); r.abort("x"); r.add_span(...)` writes one row with `status='aborted'`, `error_type='x'`, AND the first span (buffered before `abort`) is persisted, AND the second span (added after `abort`) is NOT persisted (decision §3.3: flush partial buffer)
- [ ] **AC** (FR-GRAPH-1): nested `with run()` → child's `parent_run_id` matches outer's `run_id`
- [ ] **AC** (FR-GRAPH-2): explicit `parent_run_id="abc..."` populated when no outer run
- [ ] **AC** (NFR-Rel-1): when `FakeStorageWriter.write_run` raises `StorageError`, the user's return value/exception is unchanged AND a WARNING log line with `extra={"plumb_internal_error": True}` is emitted
- [ ] `tests/unit/api/test_run_context_manager.py` passes (≥ 12 tests)
- [ ] `tests/unit/api/test_edge_cases.py` passes

### Task 5.4 — Implement sync decorator path [M]

- [ ] `_RunFactory.__call__(fn)` returns `functools.wraps(fn)`-decorated wrapper
- [ ] Sync detection via `inspect.iscoroutinefunction(fn)`; async raises `NotImplementedError("async support lands in Phase 6")` placeholder
- [ ] `@run(task_id="t")` on a sync function produces one row per call
- [ ] **AC** (FR-API-2 sync side): wrapped function returns same value as bare function; `__name__`, `__doc__`, `__wrapped__` preserved
- [ ] **AC** (FR-EDGE-4): nested decorator dedup — only the inner call writes a row
- [ ] `tests/unit/api/test_run_decorator_sync.py` passes

### Task 5.5 — Wire public re-export + cold-import test [S]

- [ ] `plumb/__init__.py` matches plan §4.1 verbatim (includes `RunHandle` in re-exports + `__all__`)
- [ ] `from plumb import run` works
- [ ] `from plumb import RunHandle` works (for type hints)
- [ ] `plumb.RunHandle()` raises `TypeError` (construct guard)
- [ ] `plumb.__all__` matches plan §4.1
- [ ] `__version__ = "0.1.0"` is a hardcoded literal (decision §6 item 1)
- [ ] `tests/unit/api/test_public_surface.py::test_only_run_is_public_entry_point` passes (AC-API-1; the test must explicitly allow `RunHandle` because of the construct guard)
- [ ] `tests/perf/test_cold_import.py` passes (warn at 200ms, fail at 400ms — decision §3.4)
- [ ] No eager imports of `anthropic`, `openai`, `httpx`, `fastapi`, `uvicorn`, `typer`, `sqlite3` from `plumb/__init__.py` (verified by grep test)

**Phase 5 deliverables:**
- [ ] Sync `@run` and `with run(...)` working end-to-end
- [ ] All sync FRs and ACs in scope passing
- [ ] Public surface enforcement test green
- [ ] Coverage ≥ 90% on `api.py`

---

## Phase 6 — API: async support

**Objective:** Add async parity. Separate phase to keep the diff reviewable.

### Task 6.1 — Implement async ctx-mgr [M]

- [ ] `__aenter__` and `__aexit__` defined on `_RunFactory`
- [ ] Both delegate to sync `__enter__`/`__exit__` (acceptable because no `await` in lifecycle — see algorithms §6.2)
- [ ] **AC** (FR-API-2 async side): `async with run(...) as r:` produces same row shape as sync
- [ ] All FR-EDGE/FR-GRAPH cases from Task 5.3 work in async form
- [ ] `tests/unit/api/test_run_async_context_manager.py` passes (`pytest-asyncio` marked)

### Task 6.2 — Replace async decorator placeholder [M]

- [ ] When `inspect.iscoroutinefunction(fn)` is True, return `async def` wrapper using `async with self:`
- [ ] **AC** (FR-API-2 fully): `@run` on `async def` produces same row shape as sync
- [ ] `functools.wraps` preserves metadata on async functions
- [ ] `tests/unit/api/test_run_decorator_async.py` passes

### Task 6.3 — Concurrent-task contextvar test [S]

- [ ] Test uses `asyncio.gather` to run three nested-run hierarchies concurrently
- [ ] Each task opens 2 nested runs (6 total)
- [ ] All 6 runs persisted; parent_run_id chains correct per-task; no cross-task pollution
- [ ] `tests/unit/api/test_nesting_contextvars.py::test_concurrent_async_tasks` passes

**Phase 6 deliverables:**
- [ ] AC-API-2 fully green (sync + async)
- [ ] Coverage on `api.py` ≥ 90%

---

## Phase 7 — Performance benchmark + cold-import gate

**Objective:** Enforce NFR-Perf-1 (against fake) and NFR-Perf-6 in CI.

### Task 7.1 — Implement `tests/perf/test_span_overhead.py` [M]

- [ ] 10,000 `add_span` calls inside one `with run(...)` block
- [ ] Backed by `FakeStorageWriter` (no I/O)
- [ ] Wall time per call measured with `time.perf_counter_ns`
- [ ] Test marked `@pytest.mark.perf`
- [ ] **AC** (AC-PERF-1 — fake-writer variant): p95 ≤ 1 ms locally on M-series; p95 ≤ 2 ms on CI runners (2× headroom)
- [ ] Test runs in < 5 s on local hardware
- [ ] Output reports p50, p95, p99 in test log

### Task 7.2 — Implement `tests/perf/test_cold_import.py` [S]

- [ ] Subprocess `python -X importtime -c 'import plumb'`
- [ ] Parse cumulative time from final `import time:` line for `plumb`
- [ ] Warn at > 200 ms; hard-fail at > 400 ms (recommendation B from context §3.4)
- [ ] Passes locally

### Task 7.3 — CI workflow [S]

- [ ] `.github/workflows/test.yml` exists (or updated) with steps:
  - `uv sync`
  - `ruff check plumb/`
  - `ruff format --check plumb/`
  - `mypy --strict plumb/core/`
  - `pytest --cov=plumb --cov-fail-under=90 tests/unit/ tests/perf/`
  - Reports p95 from perf test in build log
- [ ] Matrix: `ubuntu-24.04` + `macos-14`, Python 3.13
- [ ] CI fails if any of the six gates fail

**Phase 7 deliverables:**
- [ ] NFR-Perf-1 (fake-writer variant) and NFR-Perf-6 verified in CI
- [ ] Six quality gates wired

---

## Phase 8 — Documentation update + sign-off

**Objective:** Reflect the new core+API in evergreen docs.

### Task 8.1 — Rewrite `docs/3_guides/core_concepts.md` [M]

- [ ] Document references actual entities (`Run`, `Span`, `Score`, `Example`), not legacy `User`/`UserCRUD`
- [ ] At least one diagram or code snippet showing ports-and-adapters layout
- [ ] Worked example using `with run(...) as r:` from plan §3.6
- [ ] User signs off

### Task 8.2 — Update `docs/3_guides/getting_started.md` quickstart [S]

- [ ] Quickstart shows `pip install plumb` (or `uv sync`), then a 10-line `@run` script
- [ ] Notes that storage is in-memory until storage TRS lands (or shows expected output)
- [ ] Runs end-to-end on a fresh checkout

### Task 8.3 — Archive this slice [S]

- [ ] PR merged to `main`
- [ ] `dev/active/v1-core-and-api/` moved to `dev/archive/v1-core-and-api/`
- [ ] Per CLAUDE.md workflow

**Phase 8 deliverables:**
- [ ] Evergreen docs accurate
- [ ] Slice archived

---

## Cross-phase quality gates (must all be green at end of Phase 7)

- [ ] `ruff check plumb/` — zero errors
- [ ] `ruff format --check plumb/` — zero diffs
- [ ] `mypy --strict plumb/core/` — zero errors
- [ ] `pytest tests/unit/ tests/perf/` — all pass
- [ ] `pytest --cov=plumb --cov-report=term --cov-fail-under=90` — threshold met
- [ ] No eager imports of network/HTTP libraries from `plumb/__init__.py`
- [ ] Cold import ≤ 200 ms (warn) / ≤ 400 ms (hard fail)

## Decisions resolved (2026-04-25)

All seven decisions signed off; Phase 5 is unblocked.

- [x] **DI pattern for `plumb/api.py`** — module-level singletons (`_clock`, `_id_gen`, `_storage_writer`)
- [x] **`RunHandle` importable for type hints** — yes, with `__init__` `TypeError` construct guard
- [x] **`r.abort()` flushes partial buffer** — yes (already-buffered spans persisted; future `add_*` no-op)
- [x] **Cold-import gate** — warn at 200 ms, hard-fail at 400 ms
- [x] **`__version__` source** — hardcoded `"0.1.0"` literal; switch to `importlib.metadata` at PyPI ship
- [x] **`StorageWriter.write_run` signature** — `(run: Run, spans: Sequence[Span]) -> None` (separate args)
- [x] **`tests/regression/` placeholder** — defer to CLI TRS

---

*Last updated: 2026-04-25 — Phase 3 + 4 complete*

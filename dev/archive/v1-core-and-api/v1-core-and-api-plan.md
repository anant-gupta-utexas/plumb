# TRS — `plumb/core/` + `plumb/api.py` (v1 Foundation)

**Status:** Draft v1 — derived from [TRD](../../../docs/2_architecture/TRD.md) and [SDD](../../../docs/2_architecture/SYSTEM_DESIGN.md)
**Owner:** anant
**Last updated:** 2026-04-25
**Scope:** The first component slice of plumb v1: pure-Python core (entities, ports, stats) + the `run` decorator/context-manager API.

> **What this is.** A Technical Requirements Specification (TRS) translating TRD-level FR/NFR IDs into class-level signatures, contracts, and acceptance tests. Implementation phases are in [`v1-core-and-api-tasks.md`](./v1-core-and-api-tasks.md); design rationale and resolved decisions are in [`v1-core-and-api-context.md`](./v1-core-and-api-context.md).
>
> **What this is not.** Not the full v1 spec. Adapters, CLI, HTTP, autocapture each get their own TRS folder under `dev/active/`. This slice deliberately leaves the storage adapter as a `StorageWriter` Protocol with an in-memory test fake.

---

## 1. Overview & Scope

### 1.1 What this slice delivers

The foundational, dependency-inverted core of plumb v1:

- `plumb/core/entities.py` — `Run`, `Span`, `Score`, `Example` frozen dataclasses ([TRD §7.1](../../../docs/2_architecture/TRD.md#71-schema--authoritative-sql)).
- `plumb/core/ports.py` — `StorageWriter`, `StorageReader`, `JudgeAdapter`, `BlobStore`, `Clock`, `IdGenerator` Protocols ([SDD §3.2](../../../docs/2_architecture/SYSTEM_DESIGN.md#32-component-responsibilities)).
- `plumb/core/stats.py` — paired McNemar + Benjamini-Hochberg FDR helpers ([TRD §10.4](../../../docs/2_architecture/TRD.md#104-regression-gate-on-the-200-task-set-week-6)).
- `plumb/core/errors.py` — `PlumbError` exception hierarchy.
- `plumb/api.py` — public `run` callable (decorator + context manager, sync + async) and `Run` handle exposing `add_score`, `add_span`, `set_models`, `abort` ([TRD §3.1, §3.3, §3.8](../../../docs/2_architecture/TRD.md#31-public-api-surface)).
- `plumb/config.py` — `pydantic-settings` `Settings` model for `PLUMB_*` env vars.
- `plumb/__init__.py` — re-exports `run` and `__version__`. **Nothing else public for instrumentation.**

### 1.2 What this slice does NOT deliver

- No SQLite adapter — `dev/active/v1-storage-adapter/` (next TRS).
- No content-addressed blob store — same.
- No autocapture monkey-patching — `dev/active/v1-autocapture/`.
- No CLI or HTTP service — `dev/active/v1-cli/`, `dev/active/v1-http/`.
- No judge adapters — `dev/active/v1-judge-adapters/`.
- No `agentsview` ATTACH adapter — `dev/active/v1-attach-adapter/`.

### 1.3 Why this slice first

1. **Everything depends on it.** Adapters implement ports defined here; CLI/HTTP read entities defined here; autocapture writes through the `Run` handle defined here.
2. **Highest correctness risk.** Contextvars semantics, sync/async parity, NFR-Rel-1 error swallowing, and parent_run_id propagation are subtle. Specifying them precisely first prevents downstream rework.
3. **Specifiable without I/O.** Acceptance criteria are unit-testable with no SQLite, no FastAPI, no network mocks.

### 1.4 Anchor TRD/SDD references

| TRD/SDD section | What it constrains here |
|---|---|
| TRD FR-API-1..4 | Public surface = `run` only (decorator + ctx mgr, sync + async); `Run` handle methods |
| TRD FR-GRAPH-1..3 | Nested runs → `parent_run_id`; cross-process via explicit arg; handoff spans |
| TRD FR-EDGE-1..5 | Exception flow; SIGKILL → `stalled`; zero-span runs; nested decorator dedup; `abort()` |
| TRD NFR-Perf-1..6 | p95 ≤ 1 ms/span; ≤ 50 ms run close; in-memory buffer; cold import ≤ 200 ms |
| TRD NFR-Rel-1 | plumb internal failures NEVER raise into caller |
| TRD NFR-Use-3 | `mypy --strict` clean on `plumb/core/` |
| TRD §7.1 | Entity field types match STRICT-table SQL types |
| SDD §3.3 | Dependency rule: arrows point inward to `plumb/core/` |
| SDD §5.1 | Orchestrator → sub-agent → handoff → run-close sequence |

---

## 2. Requirements Summary

### 2.1 Functional requirements in scope

- **FR-API-1** — `plumb.run` is the only public instrumentation entry point.
- **FR-API-2** — `@run(...)` works on sync AND async functions; produces exactly one `Run` row on exit.
- **FR-API-3** — `with run(...) as r:` exposes the active `Run` handle.
- **FR-API-4** — `Run` handle exposes exactly: `add_score`, `add_span`, `set_models`, `abort`.
- **FR-GRAPH-1** — nested runs auto-populate `parent_run_id` via contextvars.
- **FR-GRAPH-2** — explicit `parent_run_id=` argument for cross-process parenting.
- **FR-GRAPH-3** — handoff representation as `kind='handoff'` span (the API surface; hash population needs blob store, deferred).
- **FR-EDGE-1** — wrapped function raises → `status='failure'`, `error_type=<class name>`, re-raise unchanged.
- **FR-EDGE-3** — zero-span runs are valid.
- **FR-EDGE-4** — nested `@run` on the same function = exactly one row (inner wins).
- **FR-EDGE-5** — `r.abort(reason=...)` → `status='aborted'`.

### 2.2 NFRs in scope

- **NFR-Perf-1** — p95 ≤ 1 ms per `add_span` call **measured against the in-memory fake `StorageWriter`**.
- **NFR-Perf-4** — span writes buffered in memory; flushed on run close in one batch.
- **NFR-Perf-5** — zero synchronous network I/O on the hot path (verified by import graph).
- **NFR-Perf-6** — cold import of `plumb` ≤ 200 ms.
- **NFR-Rel-1** — plumb internal failure never raises into caller.
- **NFR-Use-1** — Python 3.13+ only.
- **NFR-Use-3** — `mypy --strict plumb/core/` clean.

### 2.3 Out-of-scope NFRs (deferred to follow-up TRS)

NFR-Perf-2 (run close ≤ 50 ms — needs SQLite fsync), NFR-Perf-3 (pragmas), NFR-Sec-* (secrets, file modes, loopback), NFR-Rel-2..4 (process-kill recovery, ATTACH idempotency, schema-creation idempotency).

---

## 3. Detailed Component Design

### 3.1 Module layout

```
plumb/
├── __init__.py            # re-exports `run`, `__version__`. No other public names.
├── api.py                 # public `run` callable + Run handle
├── config.py              # pydantic-settings (subset for this slice)
└── core/
    ├── __init__.py        # explicit re-export list
    ├── entities.py        # frozen dataclasses for Run, Span, Score, Example + enums
    ├── ports.py           # Protocol declarations
    ├── stats.py           # paired McNemar + BH-FDR
    └── errors.py          # PlumbError hierarchy

tests/
├── conftest.py            # shared fixtures (FakeStorageWriter, FakeClock, FakeIdGenerator)
├── unit/
│   ├── core/              # entities, ports compliance, stats, errors
│   └── api/               # decorator (sync+async), ctx-mgr, handle, edge cases, public surface
└── perf/
    └── test_span_overhead.py
    └── test_cold_import.py
```

### 3.2 Entities (`plumb/core/entities.py`)

All entities are `@dataclass(frozen=True, slots=True)`. Field types match TRD §7.1 SQL types: `TEXT` → `str`, `INTEGER` → `int`, `REAL` → `float`. Timestamps are tz-aware UTC `datetime` on the Python side; serialization to ISO-8601 strings happens at the storage boundary.

#### 3.2.1 Enums

Six `StrEnum`s — values match TRD CHECK string literals exactly:

| Enum | Values |
|---|---|
| `RunKind` | `OFFLINE = "offline"`, `ONLINE = "online"` |
| `RunStatus` | `SUCCESS`, `FAILURE`, `ABORTED`, `STALLED` (all lowercase) |
| `SpanKind` | `LLM`, `TOOL`, `SUBAGENT`, `HANDOFF`, `PLAN`, `VERIFY` |
| `SpanStatus` | `SUCCESS`, `FAILURE`, `ABORTED` |
| `ScorerKind` | `DETERMINISTIC`, `JUDGE`, `HUMAN`, `USER_SIGNAL` (note: `"user_signal"` value) |
| `ExampleSource` | `SYNTHETIC`, `PRODUCTION_PROMOTION`, `HUMAN_AUTHORED` |

#### 3.2.2 Dataclass field tables

`Run` — full TRD §7.1 column set; invariants enforced in `__post_init__`:
- `run_id` matches `^[0-9a-f]{32}$`
- `start_ts.tzinfo is not None`
- if `end_ts is not None`: `end_ts >= start_ts`
- `task_id` non-empty

`Span`:
- `span_id`, `run_id` 32-hex; `name` non-empty
- `latency_ms >= 0` if not None
- `input_hash`/`output_hash` 64-char lowercase hex (sha256) if not None

`Score`:
- **Exactly one** of `value_numeric`, `value_label` is non-None (XOR; matches TRD CHECK `((value_numeric IS NULL) <> (value_label IS NULL))`)
- `scorer_version`, `metric_name` non-empty
- `scored_at` tz-aware UTC

`Example`:
- `inputs_hash` 64-hex required; `expected_output_hash` 64-hex if not None
- `task_id` non-empty
- `created_at` tz-aware UTC

`JudgeResult` (frozen dataclass, used by `JudgeAdapter` Protocol; lives here for symmetry):
- `metric_name`, `scorer_version`, `value_numeric` xor `value_label`, `rationale`, `tokens_in`, `tokens_out`, `latency_ms`

`McNemarResult` (frozen dataclass):
- `b: int`, `c: int`, `statistic: float`, `p_value: float`, `n_discordant: int`

**Mutation policy:** all entities are frozen. State transitions produce new instances via `dataclasses.replace`.

### 3.3 Ports (`plumb/core/ports.py`)

All ports are `typing.Protocol`. No imports from `plumb/adapters/`, `plumb/api.py`, or any third-party library beyond stdlib `typing`.

```python
class Clock(Protocol):
    def now(self) -> datetime: ...

class IdGenerator(Protocol):
    def new_run_id(self) -> str: ...
    def new_span_id(self) -> str: ...
    def new_score_id(self) -> str: ...
    def new_example_id(self) -> str: ...

class StorageWriter(Protocol):
    def write_run(self, run: Run, spans: Sequence[Span]) -> None: ...
    def write_score(self, score: Score) -> None: ...
    def write_example(self, example: Example) -> None: ...

class StorageReader(Protocol):
    def get_run(self, run_id: str) -> Run | None: ...
    def list_runs(self, *, since=None, task_id=None, kind=None, limit=100) -> list[Run]: ...
    def get_spans_for_run(self, run_id: str) -> list[Span]: ...
    def get_scores_for_run(self, run_id: str) -> list[Score]: ...
    def list_examples(self, *, task_id=None, active=None) -> list[Example]: ...

class BlobStore(Protocol):
    def put(self, content: bytes) -> str: ...                # returns sha256 hex
    def get(self, sha256_hex: str) -> bytes: ...

class JudgeAdapter(Protocol):
    name: str
    version: str
    def score(self, *, metric_name, prompt, content, model, timeout_s=60.0) -> JudgeResult: ...
```

`StorageReader` is declared here for the HTTP/CLI follow-up TRS. **No method on `StorageReader` is called from `plumb/api.py`** — the API surface only writes.

### 3.4 Stats (`plumb/core/stats.py`)

Two pure functions; no I/O; `mypy --strict` clean. Algorithms in §6.

```python
def mcnemar_paired(
    baseline_outcomes: Sequence[bool],
    candidate_outcomes: Sequence[bool],
    *,
    continuity_correction: bool = True,
) -> McNemarResult: ...

def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> list[bool]: ...
```

### 3.5 Errors (`plumb/core/errors.py`)

```python
class PlumbError(Exception): ...
class StorageError(PlumbError): ...
class BlobNotFoundError(PlumbError): ...
class ValidationError(PlumbError): ...
class JudgeError(PlumbError): ...
```

`PlumbError` and subclasses are **never** propagated past `plumb/api.py` per NFR-Rel-1. The API layer catches `PlumbError`, logs WARNING, records `error_type='plumb_internal_error'`, lets the wrapped function's own return/exception flow to the caller unchanged.

### 3.6 Public API (`plumb/api.py`)

#### 3.6.1 `run` factory

```python
def run(
    *,
    task_id: str,
    kind: RunKind | Literal["offline", "online"] = "online",
    parent_run_id: str | None = None,
    orchestrator_model: str | None = None,
    sub_agent_model: str | None = None,
    prompt_version: str | None = None,
    tool_schema_version: str | None = None,
    git_sha: str | None = None,
) -> _RunFactory: ...
```

`_RunFactory` is the returned object: callable (decorator path) AND a context manager (sync + async). Public surface is `run` only.

#### 3.6.2 `RunHandle` (yielded by `with run(...) as r:`)

| Method | Purpose | Returns |
|---|---|---|
| `add_score(metric_name, scorer, *, value_numeric=None, value_label=None, span_id=None, scorer_version=None)` | Buffer a score | `score_id: str` |
| `add_span(kind, name, *, parent_span_id=None, input_hash=None, output_hash=None, tokens=None, latency_ms=None, status=None, error_type=None)` | Buffer a span | `span_id: str` |
| `set_models(*, orchestrator_model=None, sub_agent_model=None)` | Late-bind models | `None` |
| `abort(reason: str)` | Mark aborted | `None` |

Properties (read-only): `run_id`, `parent_run_id`, `task_id`.

`add_score` enforces XOR validation (raises `ValidationError` on both/neither value). After `abort()`, subsequent `add_*` calls become no-ops. `set_models` last-call-wins.

**Public-for-types-only:** `RunHandle` IS exported in `plumb.__all__` so users can write `def my_helper(r: RunHandle): ...`. The `__init__` requires a non-None `_builder` argument — direct construction by user code raises `TypeError("RunHandle is not user-constructible; obtain one via `with run(...) as r:`")`. This satisfies AC-API-1 (no third *instrumentation* entry point) while permitting type annotations.

#### 3.6.3 Decorator semantics

`@run(task_id="...", kind="online")` wraps via `functools.wraps`. Sync vs async detected via `inspect.iscoroutinefunction(fn)`. Async dispatch uses `async def` wrapper around `async with self:`.

#### 3.6.4 Contextvars

```python
_active_run: ContextVar[RunHandle | None] = ContextVar("plumb_active_run", default=None)
```

- On run open: read current `_active_run`. If non-None, child's `parent_run_id` = parent handle's `run_id` (FR-GRAPH-1).
- On run exit: restore prior token via stored `_token`.
- **FR-EDGE-4 nested-decorator dedup:** if a `RunHandle` exists in the contextvar AND its `_open_frame_id == id(wrapped_fn)`, the outer call is a no-op (returns the parent handle from `__enter__`, doesn't shadow it).

### 3.7 Config (`plumb/config.py`)

Subset for this slice: `PLUMB_DATA_DIR`, `PLUMB_LOG_LEVEL`, `PLUMB_AUTOCAPTURE`. Pattern: `BaseSettings` with `env_prefix="PLUMB_"`; `lru_cache(maxsize=1)` on `get_settings()` to read env once at import.

---

## 4. API Specifications

### 4.1 Public Python surface

```python
# plumb/__init__.py
from plumb.api import run, RunHandle
from plumb.core.entities import (
    RunKind, RunStatus, SpanKind, SpanStatus, ScorerKind, ExampleSource,
    Run, Span, Score, Example, JudgeResult, McNemarResult,
)
from plumb.core.errors import (
    PlumbError, StorageError, BlobNotFoundError, ValidationError, JudgeError,
)

__version__ = "0.1.0"  # hardcoded per context §6 item 1; switch to importlib.metadata at PyPI ship

__all__ = [
    "run",
    "RunHandle",  # public for type hints only; direct construction raises TypeError
    "RunKind", "RunStatus", "SpanKind", "SpanStatus", "ScorerKind", "ExampleSource",
    "Run", "Span", "Score", "Example", "JudgeResult", "McNemarResult",
    "PlumbError", "StorageError", "BlobNotFoundError", "ValidationError", "JudgeError",
    "__version__",
]
```

Entities and `RunHandle` re-exported for type-hinting only — they are *not* alternative entry points. AC-API-1 enforced by `tests/unit/api/test_public_surface.py::test_only_run_is_public_entry_point` (which excludes `RunHandle` because its `__init__` rejects user construction).

### 4.2 Method specs

See §3.6.2 for the table. Validation errors raised synchronously at call site:
- `add_score` with both/neither of `value_numeric`/`value_label` → `ValidationError`
- `add_score` with empty `metric_name` → `ValidationError`
- `add_span` with empty `name` or invalid `latency_ms`/hash → `ValidationError`
- `abort` with empty reason → `ValidationError`

### 4.3 No HTTP/CLI surface in this slice

Both `plumb/cli.py` and `plumb/http.py` are out of scope. Their TRSes will reference entities and ports defined here.

---

## 5. Database Design

**Out of scope.** TRD §7.1 SQL schema is canonical; concrete `CREATE TABLE` execution, pragmas, indexes, and the SQLite adapter are specified in `dev/active/v1-storage-adapter/`.

This slice only requires that:
- Entities' Python types match TRD §7.1 SQL types.
- Enum values match TRD `CHECK` constraint string literals exactly (`"offline"` not `"OFFLINE"`).

---

## 6. Algorithm & Logic Design

See [`v1-core-and-api-algorithms.md`](./v1-core-and-api-algorithms.md) for full pseudocode of:
- §6.1 Run lifecycle (sync) — `__enter__` / `__exit__` flow with NFR-Rel-1 swallowing
- §6.2 Run lifecycle (async) — `__aenter__` / `__aexit__` parity
- §6.3 McNemar's paired test — `(|b-c|-1)^2 / (b+c)` form, `math.erfc` for chi-squared CDF (no SciPy dep)
- §6.4 Benjamini-Hochberg FDR — sorted-rank rejection threshold
- §6.5 ID generation — `uuid.uuid4().hex` (32-char lowercase hex)
- §6.6 Cold-import budget enforcement — lazy adapter imports

---

## 7. Error Handling & Edge Cases

| Scenario | TRD ref | Behavior |
|---|---|---|
| User function raises | FR-EDGE-1 | `status='failure'`, `error_type=<class name>`, re-raise unchanged |
| User function returns normally | — | `status='success'` |
| `r.abort("user cancelled")` | FR-EDGE-5 | `status='aborted'`, `error_type='user cancelled'`; subsequent adds no-op |
| Run with zero spans | FR-EDGE-3 | Valid; `Run` row written with empty span list |
| Nested `@run` on same function | FR-EDGE-4 | Inner wins; outer is no-op |
| StorageWriter raises during close | NFR-Rel-1 | Catch, log WARNING, swallow; user code's return/raise unaffected |
| `add_score` with both values set | FR-SCORE-3 | `ValidationError` synchronously |
| `add_score` with neither value | FR-SCORE-3 | `ValidationError` synchronously |
| `add_span` with `name=""` | Entity invariant | `ValidationError` |
| Nested run inside `async` context | FR-GRAPH-1 | contextvars handle async correctly |
| Cross-process child via `parent_run_id=` | FR-GRAPH-2 | Caller passes parent's run_id; plumb does not auto-thread |
| `clock.now()` returns naive datetime | Entity invariant | `__post_init__` raises `ValidationError` |

**Retry strategy:** None at this layer. Storage retries are an adapter concern; judge retries are in the judge-adapter TRS.

**Fallbacks:** None. plumb is a recorder; if it can't record, it logs and steps aside.

---

## 8. Dependencies & Interfaces

### 8.1 Runtime dependencies (this slice only)

| Package | Floor | Why |
|---|---|---|
| `pydantic` | ≥ 2.6 | `JudgeResult` and `Settings` validation |
| `pydantic-settings` | ≥ 2.2 | `Settings` model |

**Not in this slice:** `anthropic`, `openai`, `fastapi`, `uvicorn`, `typer`, `httpx`, `rich`. These are pulled in by their owning slice.

### 8.2 Stdlib

`dataclasses`, `enum`, `typing`, `contextvars`, `inspect`, `functools`, `uuid`, `datetime` (with `UTC`), `logging`, `math`, `pathlib`.

### 8.3 Test-only

`pytest`, `pytest-asyncio` ≥ 0.23, `pytest-cov`, `hypothesis` ≥ 6.100.

### 8.4 Internal interfaces (consumed by follow-up slices)

- Storage TRS implements `StorageWriter`, `StorageReader`, `BlobStore`.
- CLI/HTTP TRSes read entities from `StorageReader`.
- Autocapture TRS calls `RunHandle.add_span()` from monkey-patched SDKs; reads `_active_run`.

---

## 9. Security Considerations

Most security NFRs are out of scope (no I/O, no network, no secrets). Two that DO apply:

### 9.1 Input validation

Entity invariants in `__post_init__` reject malformed input at the boundary. Hashes 64-hex; IDs 32-hex; timestamps tz-aware. Catches accidental injection (e.g., user passing a path as `run_id`).

### 9.2 No log injection

`PlumbError` subclasses MUST NOT include user content in exception messages. Rationale: WARNING log line on internal failure is structured JSON; bare-string messages risk newlines or terminal control codes if `task_id` is hostile. Test asserts `\n`, `\r`, `\x1b` in `task_id` get escaped by the formatter.

### 9.3 Deferred to other slices

Secret handling (NFR-Sec-1, NFR-Sec-2) → judge-adapter TRS. File modes (NFR-Sec-5) → blob-store TRS. HTTP loopback (NFR-Sec-4) → HTTP TRS. SQL injection (NFR-Sec-3) → storage TRS.

---

## 10. Testing Strategy

### 10.1 Coverage targets

| Module | Target |
|---|---|
| `plumb/core/entities.py` | ≥ 95% |
| `plumb/core/ports.py` | N/A (Protocols, no logic) |
| `plumb/core/stats.py` | ≥ 95% |
| `plumb/core/errors.py` | ≥ 90% |
| `plumb/api.py` | ≥ 90% |
| `plumb/config.py` | ≥ 85% |

Overall (this slice): **≥ 90%** (higher than the TRD's 75% slice-wide gate, because the core has no I/O excuses).

### 10.2 Test categories

- **Unit:** entity invariants, enum-value parity with TRD CHECK strings, error hierarchy, McNemar known-answer cases, BH-FDR vs R `p.adjust(method="BH")` golden values.
- **Property (Hypothesis):** entity round-trip, `add_score` XOR legality, BH-FDR monotonicity.
- **Async (`pytest-asyncio`):** `@run` on `async def`, `async with run(...)`, concurrent `asyncio.gather` with three nested-run hierarchies.
- **Performance (`tests/perf/`):** 10k `add_span` cycles against fake writer; subprocess `python -X importtime`.

### 10.3 Fakes (shared `tests/conftest.py`)

`FakeClock` (deterministic increment), `FakeIdGenerator` (sequential hex), `FakeStorageWriter` (in-memory lists). The `configured_api` fixture monkeypatches these into `plumb.api`'s module-level singletons.

### 10.4 Acceptance criteria coverage

| TRD AC | Test |
|---|---|
| AC-API-1 | `test_public_surface.py::test_only_run_is_public_entry_point` |
| AC-API-2 (sync) | `test_run_decorator_sync.py::test_sync_function_produces_one_run_row` |
| AC-API-2 (async) | `test_run_decorator_async.py::test_async_function_produces_one_run_row` |
| AC-PERF-1 | `tests/perf/test_span_overhead.py::test_p95_span_overhead_under_1ms` |
| AC-REL-1 (partial) | `test_edge_cases.py::test_storage_failure_does_not_raise_into_caller` |

(AC-PERF-2, schema/integration ACs deferred to follow-up TRSes.)

### 10.5 Mocking policy

Time → `FakeClock` (no `freezegun`). IDs → `FakeIdGenerator`. Storage → `FakeStorageWriter`. **No SQLite in this slice's tests.**

---

## 11. Performance Considerations

### 11.1 Hot-path budgets

| Operation | Budget | Strategy |
|---|---|---|
| `run.__enter__` | ≤ 100 µs | Construct `_RunBuilder`, set contextvar, no I/O |
| `add_span` | ≤ 100 µs amortized | `list.append`; defer hashing to caller |
| `add_score` | ≤ 100 µs amortized | `list.append`; XOR check is two `is None` comparisons |
| `run.__exit__` (success path) | ≤ 200 µs (excl. storage write) | Iterate buffered lists, freeze, hand to writer |

The 1 ms NFR-Perf-1 budget is for `add_span` plus its share of flush cost. This slice exercises it against `FakeStorageWriter.write_run` (O(1) `list.append`); the real test of the budget happens in storage TRS with the SQLite adapter.

### 11.2 Memory

In-memory span/score buffers. Typical run: ≤ 100 spans × ~200 bytes/span = ~20 KB per open run. Pathological (10k spans × 1 KB hashes) = ~10 MB — well within process headroom.

### 11.3 Caching

`get_settings()` is `lru_cache`-decorated to cache env-var reads. No other caching.

### 11.4 Monitoring

None — library, no runtime surface. Cold-import time measured in CI.

---

## 12. Resolved Decisions

All pending decisions were resolved on 2026-04-25 with the recommended options. Full rationale lives in [`v1-core-and-api-context.md`](./v1-core-and-api-context.md) §3 and §6. Summary:

| # | Decision | Resolution |
|---|---|---|
| 1 | API dependency-injection pattern | **Module-level singletons** (`plumb.api._clock`, `_id_gen`, `_storage_writer`); tests use `monkeypatch.setattr` |
| 2 | `RunHandle` importable for type hints | **Yes**, exported in `__all__`; runtime guard in `__init__` raises `TypeError` if user constructs directly |
| 3 | `r.abort()` flush vs discard | **Flush** the partial buffer; mark `status='aborted'`, `error_type=reason`; future `add_*` calls become no-ops |
| 4 | Cold-import gate | **Warn** at 200 ms, **fail** at 400 ms (matches NFR-Perf-1's 2× headroom convention) |
| 5 | `__version__` source | Hardcoded `"0.1.0"` literal for now; switch to `importlib.metadata` at PyPI ship |
| 6 | `StorageWriter.write_run` signature | Separate args: `write_run(run: Run, spans: Sequence[Span]) -> None` |
| 7 | `tests/regression/` placeholder | Defer to CLI TRS (it owns the runner) |

**Status:** Phase 5 unblocked. All implementation phases can proceed.

---

## 13. Implementation Phases

Full task breakdown with effort, files, AC checklists, dependencies, and testing requirements lives in [`v1-core-and-api-tasks.md`](./v1-core-and-api-tasks.md). Summary:

| Phase | Objective | Effort |
|---|---|---|
| **1** | `src/` cleanup + `plumb/` skeleton | S+S+S |
| **2** | Entities + Errors | S+S+M |
| **3** | Ports + Stats | S+M+S |
| **4** | Config | S |
| **5** | API — sync decorator + ctx mgr | M+M+L+M+S |
| **6** | API — async support | M+M+S |
| **7** | Performance benchmark + cold-import gate | M+S+S |
| **8** | Documentation update + sign-off | M+S+S |

Phases are sequential (dependency-ordered per Q3=A); no parallel work in this slice.

---

## 14. Forward Pointers (Other TRSes)

| Follow-up TRS | Implements / consumes |
|---|---|
| `v1-storage-adapter/` | Implements `StorageWriter`, `StorageReader`, `BlobStore`; replaces fake writer |
| `v1-autocapture/` | Calls `RunHandle.add_span` from patched SDKs; reads `_active_run` |
| `v1-cli/` | Reads via `StorageReader`; uses `plumb.core.stats` |
| `v1-http/` | Reads via `StorageReader` |
| `v1-judge-adapters/` | Implements `JudgeAdapter` |
| `v1-attach-adapter/` | Uses `StorageWriter` via INSERT...SELECT |

---

*End of TRS v1 — `plumb/core/` + `plumb/api.py` foundation slice.*

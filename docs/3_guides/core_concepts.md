# Core Concepts

## What plumb does

plumb is a measurement spine for orchestrator + sub-agent systems. It records every run, span, score, and evaluation example to a four-table SQLite schema, exposing two public entry points — `plumb.run` (decorator + context manager) and `plumb.resume_run` (context-manager-only, for cross-process hand-off) — without requiring any framework code in your business logic.

---

## Architecture: ports and adapters

plumb uses a ports-and-adapters layout. The inner core (`plumb/core/`) is pure Python with no I/O. The outer adapters (`plumb/adapters/`) implement the port Protocols defined by the core. Dependency arrows point inward: adapters depend on ports; the core never imports adapters.

```
┌─────────────────────────────────────────────────┐
│  plumb/core/                                    │
│                                                 │
│   entities.py   ports.py   stats.py   errors.py│
│       ↑            ↑                            │
└───────┼────────────┼────────────────────────────┘
        │            │  (ports only; no impl)
┌───────┼────────────┼────────────────────────────┐
│  plumb/api.py                                   │
│   (calls StorageWriter port; never an adapter)  │
└─────────────────────────────────────────────────┘
        │
┌───────▼────────────────────────────────────────┐
│  plumb/adapters/                               │
│   storage_sqlite.py  (implements StorageWriter) │
│   blobstore_fs.py    (implements BlobStore)     │
│   judge_anthropic.py (implements JudgeAdapter)  │
│   ...                                           │
└────────────────────────────────────────────────┘
```

This separation means:
- **The core is always unit-testable with simple fakes** — no SQLite, no network.
- **Adapters can be swapped** without touching `plumb/api.py` or any caller code.
- **`plumb/api.py` only imports from `plumb/core/`** — it depends on the `StorageWriter` Protocol, not on `StorageWriterSQLite`.

---

## Core entities

All four domain entities are `@dataclass(frozen=True, slots=True)`. Once constructed, they cannot be mutated. State transitions produce new instances via `dataclasses.replace`.

### `Run`

Represents a single instrumented execution. A run has a `task_id` (what kind of work this is), a `kind` (offline evaluation vs online production), and a `status` set on close.

```python
from plumb import Run, RunKind, RunStatus
```

Key fields: `run_id` (32-char hex), `task_id`, `kind`, `status`, `start_ts`, `end_ts`, `parent_run_id` (for nested/child runs), `orchestrator_model`, `sub_agent_model`, `tokens_in`, `tokens_out`, `dollar_cost` (all three set via `RunHandle.set_usage`; `dollar_cost` is explicit-only, never auto-filled).

`run_id` is a `uuid4().hex` — 32 lowercase hex characters, not a UUID string. `start_ts` must be a timezone-aware `datetime`; passing a naive datetime raises `ValidationError`.

### `Span`

A single unit of work within a run — an LLM call, a tool invocation, a subagent dispatch, a handoff, a planning step, or a verification step. Each span belongs to exactly one `Run` via `run_id`, and can be nested under a parent span via `parent_span_id`.

```python
from plumb import Span, SpanKind, SpanStatus
```

Key fields: `span_id`, `run_id`, `kind` (one of `SpanKind`), `name`, `parent_span_id`, `tokens_in`, `tokens_out`, `latency_ms`, `input_hash`, `output_hash` (SHA-256 hex, 64 chars), `attributes` (optional JSON-serializable `dict`, ~8KB soft cap, validated fail-closed on write and surfaced as `None` rather than raised on a malformed legacy read).

### `Score`

A metric recorded against a run or a specific span. Exactly one of `value_numeric` or `value_label` must be set — never both, never neither. This XOR constraint mirrors the SQLite `CHECK` clause and is enforced in `__post_init__`.

```python
from plumb import Score, ScorerKind
```

Key fields: `score_id`, `run_id`, `metric_name`, `scorer_kind` (deterministic / judge / human / user_signal), `scorer_version`, `scored_at`, `value_numeric` XOR `value_label`, `rationale`.

### `Example`

A stored input for offline evaluation. Examples are promoted from production runs or authored synthetically. `inputs_hash` and `expected_output_hash` are SHA-256 content hashes (64 hex chars) that address the actual bytes stored in the blob store.

```python
from plumb import Example, ExampleSource
```

### Supporting types

| Type | Purpose |
|---|---|
| `JudgeResult` | Return value of a `JudgeAdapter.score()` call |
| `McNemarResult` | Result of a paired McNemar statistical test |
| `RunKind` | `"offline"` / `"online"` |
| `RunStatus` | `"success"` / `"failure"` / `"aborted"` / `"stalled"` |
| `SpanKind` | `"llm"` / `"tool"` / `"subagent"` / `"handoff"` / `"plan"` / `"verify"` |
| `ScorerKind` | `"deterministic"` / `"judge"` / `"human"` / `"user_signal"` |

Enum values are lowercase strings (matching the SQLite `CHECK` literals). You can pass either the enum member or its string value to any plumb API.

---

## Port Protocols

Ports are `typing.Protocol` classes defined in `plumb/core/ports.py`. They are the contracts that adapters implement. You never import adapters directly in instrumentation code — the `plumb/api.py` module holds a module-level `_storage_writer` singleton that tests and integration code swap out.

| Protocol | Responsibility |
|---|---|
| `StorageWriter` | Write a run+spans batch, a score, or an example |
| `StorageReader` | Read runs, spans, scores, examples (used by CLI and HTTP service) |
| `BlobStore` | Content-addressed storage: `put(bytes) -> sha256_hex`, `get(sha256_hex) -> bytes` |
| `JudgeAdapter` | LLM-as-judge: `score(metric_name, prompt, content, model) -> JudgeResult` |
| `Clock` | `now() -> datetime` — injectable for deterministic testing |
| `IdGenerator` | `new_run_id()`, `new_span_id()`, `new_score_id()`, `new_example_id()` |

All protocols are `@runtime_checkable`, so you can use `isinstance(obj, StorageWriter)` in tests.

---

## The `run` API

`plumb.run` is the primary instrumentation entry point. It returns a `_RunFactory` object that is usable as a context manager (sync or async) and as a decorator. `plumb.resume_run` (below) is the only other public instrumentation entry point — context-manager-only, for re-opening a run that a different process left `pending`.

### Context manager

```python
from plumb import run, SpanKind

with run(task_id="summarise-document", kind="online") as r:
    # r is a RunHandle
    span_id = r.add_span(SpanKind.LLM, "generate-summary", latency_ms=312.4, tokens=(820, 210))
    r.add_score("answer_relevance", "deterministic", value_numeric=0.91, span_id=span_id)
    r.set_models(orchestrator_model="claude-sonnet-4-6")
# Run is written to storage here, on __exit__
```

### Decorator

```python
from plumb import run

@run(task_id="classify-intent", kind="online", orchestrator_model="claude-haiku-4-5")
def classify(text: str) -> str:
    # plumb opens/closes the run around this function call
    return "question"
```

### Async

Both the context manager and decorator work with `async def` functions and `async with` — the `__aenter__`/`__aexit__` methods delegate to the same sync path.

```python
async with run(task_id="eval-async") as r:
    r.add_span("llm", "generate")
```

### Nested runs and parent resolution

When one `with run(...)` block is nested inside another, plumb automatically propagates `parent_run_id` via a `ContextVar`. You do not need to pass the parent's `run_id` explicitly for in-process nesting:

```python
with run(task_id="orchestrator") as orch:
    with run(task_id="sub-agent") as sub:
        # sub.parent_run_id == orch.run_id  (set automatically)
        sub.add_span("subagent", "tool-call")
```

For cross-process parenting (the orchestrator and sub-agent run in different processes), pass `parent_run_id` explicitly:

```python
with run(task_id="sub-agent", parent_run_id=received_run_id) as r:
    ...
```

### `plumb.resume_run` — cross-process hand-off

`resume_run(run_id)` re-opens an existing `pending` run in a *different* process from the one that opened it — for example, a supervisor process that starts a run and hands the `run_id` off to a worker, which resumes it, adds its own spans/scores, and closes it. It is context-manager-only (no decorator form), since resuming needs an existing `run_id` that isn't known at decoration time.

```python
from plumb import resume_run, SpanKind

# Process A: opens the run, hands run_id to process B, does not close it.
# Process B, sometime later:
with resume_run(received_run_id) as r:
    r.add_span(SpanKind.LLM, "generate")
    r.set_usage(dollar_cost=0.004)
# finalize_run fires here — original start_ts is preserved, end_ts reflects this exit
```

Raises `NotFoundError` if `run_id` doesn't exist, or `ValidationError` if the run is already terminal (`success`/`failure`/`aborted`/`stalled` all count as terminal-for-resume — a `stalled` run has already been given up on by the 1-hour stalled-sweep and resuming it would race that sweep).

### `RunHandle` methods

| Method | Returns | Notes |
|---|---|---|
| `add_span(kind, name, *, latency_ms, tokens, attributes, status, ...)` | `span_id: str` | Buffers span in memory; `attributes` is an optional JSON-serializable dict (~8KB soft cap) |
| `add_score(metric_name, scorer, *, value_numeric, value_label, span_id, rationale, idempotency_key, ...)` | `score_id: str` | XOR: exactly one of `value_numeric` / `value_label`. `idempotency_key` is advisory only — the real dedup guarantee is a storage-layer unique index |
| `add_example(inputs_hash, *, source, expected_output_hash, rubric, ...)` | `example_id: str` | Writes an `examples` row tied to the active run (`origin_run_id`); same shape as `plumb example promote` |
| `set_models(*, orchestrator_model, sub_agent_model)` | `None` | Late-bind; last call wins |
| `set_usage(*, tokens_in, tokens_out, dollar_cost)` | `None` | Late-bind run-level usage/cost; last call wins per-field. If never called, `tokens_in`/`tokens_out` auto-fill from the buffered spans' token totals at close time — `dollar_cost` is **never** auto-filled, only ever set explicitly |
| `abort(reason: str)` | `None` | Sets status to `"aborted"`; subsequent `add_*`/`set_*` calls become no-ops |

Properties (read-only): `run_id`, `task_id`, `parent_run_id`.

```python
with run(task_id="summarise-document") as r:
    span_id = r.add_span(SpanKind.LLM, "generate-summary", tokens=(820, 210))
    r.add_score("answer_relevance", "deterministic", value_numeric=0.91, rationale="on-topic, concise")
    r.add_example("a1b2c3...".rjust(64, "0"), source="production_promotion")
    r.set_usage(dollar_cost=0.0031)  # tokens_in/out auto-fill from the span above; cost is explicit-only
```

### Error handling

plumb never raises into caller code due to its own internal failures (NFR-Rel-1). If the storage write fails on `__exit__`, plumb logs a structured `WARNING` and silently steps aside. Your function's own return value or exception is always returned/re-raised unchanged.

User-code exceptions inside a `with run(...)` block cause `status="failure"` and `error_type=<ExceptionClassName>` on the resulting `Run`, but the exception is still re-raised to the caller.

---

## Storage wiring

The storage writer is a module-level singleton in `plumb/api.py`:

```python
import plumb.api as _api

# Point plumb at a real SQLite writer (once the storage adapter is available)
from plumb.adapters.storage_sqlite import StorageSQLite
_api._storage_writer = StorageSQLite(db_path="~/.plumb/plumb.db")
```

Until the storage adapter is wired, plumb uses `_NoopStorageWriter` — all writes are accepted and discarded. For testing, replace the singleton with a `FakeStorageWriter` (see `tests/conftest.py`).

---

## Stats helpers

`plumb/core/stats.py` provides two pure functions for offline evaluation analysis:

```python
from plumb.core.stats import mcnemar_paired, benjamini_hochberg

# Compare two systems on a shared test set
result = mcnemar_paired(baseline_outcomes, candidate_outcomes)
# result.p_value, result.statistic, result.b, result.c

# Correct for multiple comparisons
rejections = benjamini_hochberg(p_values, alpha=0.05)
# list[bool] — True where the null hypothesis is rejected
```

Both functions are dependency-free (stdlib math only) and `mypy --strict` clean.

---

## Configuration

plumb reads its runtime settings from `PLUMB_*` environment variables via `pydantic-settings`:

| Variable | Default | Purpose |
|---|---|---|
| `PLUMB_DATA_DIR` | `~/.plumb` | Where SQLite and blobs are stored |
| `PLUMB_LOG_LEVEL` | `WARNING` | Python logging level |
| `PLUMB_AUTOCAPTURE` | `false` | Enable import-time SDK monkey-patching |

Settings are cached after the first read (`lru_cache`). Access them via `from plumb.config import get_settings`.

---

## Key principles

**Dependency inversion.** The core defines interfaces; adapters implement them. `plumb/api.py` calls `StorageWriter.write_run`, not `StorageSQLite.write_run`.

**Immutability.** All four domain entities are frozen dataclasses. The `_RunBuilder` inside the API is the only mutable staging area; it is discarded as soon as `freeze()` is called on run close.

**Never raise into caller.** plumb internal errors (`PlumbError` and subclasses) are caught at the `__exit__` boundary and swallowed with a structured log warning.

**Testability without I/O.** Because the core has no external dependencies, every entity, port compliance test, and API behaviour test runs against in-memory fakes — no SQLite, no network, no filesystem.

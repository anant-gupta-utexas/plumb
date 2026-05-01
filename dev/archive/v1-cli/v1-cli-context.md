# v1-cli — Context, Decisions & Integration Points

**Plan:** [v1-cli-plan.md](./v1-cli-plan.md) | **Tasks:** [v1-cli-tasks.md](./v1-cli-tasks.md)

---

## 1. Prerequisites & Current State

### What's already built (as of 2026-04-29)

| Component | Status | Relevant to CLI |
|---|---|---|
| `plumb/core/entities.py` | Complete | `Run`, `Score`, `Example`, `ScorerKind`, `ExampleSource`, `SpanKind` |
| `plumb/core/ports.py` | Complete | `StorageWriter`, `StorageReader`, `JudgeAdapter` Protocol |
| `plumb/core/errors.py` | Complete | `StorageError`, `JudgeError`, `ValidationError` |
| `plumb/adapters/storage_sqlite.py` | Complete | `SQLiteStorageAdapter` — all read + write methods the CLI needs |
| `plumb/adapters/blobstore_fs.py` | Complete | `FilesystemBlobStore` — used by `judge run` for blob content |
| `plumb/api.py` | Complete | Decorator/context manager; CLI does NOT import this |
| `plumb/config.py` | Complete | `get_settings()`, `ensure_data_dir()`, `Settings` |
| `plumb/autocapture/` | In progress (v1-autocapture) | CLI has no dependency on autocapture |
| `plumb/adapters/agentsview_attach.py` | Not yet built | `attach` command stubs the call; adapter built separately |
| `plumb/adapters/judge_anthropic.py` | Not yet built | `judge run` uses `FakeJudgeAdapter` in tests |
| `plumb/http.py` | Not yet built | `serve` stubs `uvicorn.run`; HTTP app built separately |

### `StorageReader` methods available for CLI use

From `SQLiteStorageAdapter`:

```python
get_run(run_id: str) -> Run | None
list_runs(*, since=None, task_id=None, kind=None, limit=100) -> list[Run]
get_spans_for_run(run_id: str) -> list[Span]
get_scores_for_run(run_id: str) -> list[Score]
list_examples(*, task_id=None, active=None) -> list[Example]
```

The `plumb run stats` JOIN query (with `span_count`/`score_count`) cannot be expressed via `list_runs` alone — it requires a raw SQL query on the adapter's connection. The CLI will issue a raw parameterized query on `_conn` directly via a private helper, or the adapter can expose a new `list_runs_with_counts(...)` method. **Pending decision PD-4** — see §3.

### `JudgeAdapter` Protocol (from `plumb/core/ports.py`)

```python
class JudgeAdapter(Protocol):
    name: str
    version: str
    def score(self, *, metric_name, prompt, content, model, timeout_s=60.0) -> JudgeResult: ...
```

`JudgeResult` fields: `metric_name`, `value_numeric`, `value_label`, `rationale`, `tokens_in`, `tokens_out`, `latency_ms`, `scorer_version`.

---

## 2. Key Design Decisions (Resolved)

### DR-1: CLI does not import `plumb.api`

The CLI is a pure consumer of storage and adapters. It never uses the decorator/context manager. This keeps the cold-import path clean and avoids circular imports.

### DR-2: All subcommands in one `cli.py` file

The ≤ 400 LOC target is tight but achievable if each command is kept to 20–30 lines. Helpers (`parse_since`, `format_output`) live in separate modules. If `cli.py` grows beyond 400 LOC, split `judge_run` into `plumb/_cli_judge.py` — it's the most complex command.

### DR-3: `typer.testing.CliRunner` for all CLI tests

`CliRunner` from `typer.testing` (thin wrapper around `click.testing.CliRunner`) captures stdout/stderr and exit code without spawning a subprocess. Integration tests use `tmp_path`-backed `SQLiteStorageAdapter`.

### DR-4: `scorer_version` defaults to `"cli-unversioned"` when omitted

Satisfies FR-SCORE-2 (NOT NULL) while being explicit about provenance. Logged at INFO on the first omission per session.

### DR-5: `sha256(b"no_spans")` sentinel for `example promote` with zero spans

A zero-span run is valid (FR-EDGE-3). The `inputs_hash` column is NOT NULL in the schema, and `Example.__post_init__` enforces a 64-char lowercase hex string via `_require_hex64`. A literal `"no_spans"` string therefore fails entity validation.

The implementation uses `hashlib.sha256(b"no_spans").hexdigest()` — a deterministic, well-known 64-char hex value (`94a3…`) — as the zero-span sentinel. Consumers who need to identify zero-span promotions should compare `inputs_hash` against this value. This value cannot collide with a real span's `input_hash` in practice (a real sha256 would require constructing a blob whose sha256 is exactly this value).

### DR-6: `plumb judge run` exits 0 even when individual judge calls fail

Mirrors `INT-JUDGE-5`: judge errors are recorded as `value_label='error'` score rows and logged at WARNING. The batch command exits 0 if it completes the loop; exits 1 only if the adapter itself is not configured or the storage write fails completely.

---

## 3. Pending Decisions (All Resolved — 2026-04-29)

### PD-1: `rich` as required dep vs. optional — **RESOLVED: Option A**

**Decision:** Make `rich` a required dependency for the CLI.

**Rationale:** The CLI is for humans; rich tables are the core UX. One rendering path simplifies `_output.py` and its tests. `rich` is already in most ML dev environments. The ~2 MB install footprint increase is acceptable for a developer tool.

**Impact on implementation:** `pyproject.toml` moves `rich` from optional to required. `_output.py` can import `rich.table.Table` unconditionally (inside functions to preserve cold-import budget).

---

### PD-2: Content format passed to `judge run` adapter — **RESOLVED: Option C**

**Decision:** Defer content format definition to the judge adapter TRS. CLI passes raw primary-span blob decoded as UTF-8, or `""` if no blob.

**Rationale:** Avoids coupling the CLI to a content-format decision that belongs to the judge adapter design. The interim behaviour (raw blob UTF-8) is easy to change before real adapters land.

**Impact on implementation:** `judge_run` fetches the `input_hash` from the primary span (same selection logic as `example_promote`), reads the blob from `FilesystemBlobStore`, decodes as UTF-8, passes as `content`. `BlobNotFoundError` → use `""` + WARNING log.

---

### PD-3: `plumb run stats` — show all runs or top-level only by default — **RESOLVED: Option A**

**Decision:** Show all runs flat, sorted by `start_ts DESC`. No filtering by `parent_run_id` in v1.

**Rationale:** Simplest implementation; `--task-id` filter gives enough narrowing for v1 use cases. Revisit with `--include-children` / `--top-level-only` flag in v2.

**Context:** The `runs` table has `parent_run_id`. Many sub-agent runs can exist per orchestrator run.

**Options:**
- **A. All runs flat, sorted by `start_ts DESC`** — simple; `--task-id` filter narrows view.
- **B. Top-level only by default; `--include-children` flag** — cleaner default UX; slightly more complex.
- **C. Group-by-parent display** — most informative; most complex.

**Recommendation:** Option A for v1. Revisit in v2 with `--include-children`.

**Decision needed from:** anant **before T1.4**.

---

### PD-4: `run stats` JOIN query — raw SQL on adapter conn vs. new `list_runs_with_counts` method — **RESOLVED: Option A**

**Decision:** Add `list_runs_with_counts(...)` as a first-class method on `SQLiteStorageAdapter`.

**Rationale:** SQL stays inside the adapter layer; CLI stays clean. The counts are a natural part of a "run summary" view. One well-tested method is better than leaking `_conn` out of the adapter boundary.

**Impact on implementation:** `storage_sqlite.py` gains a `list_runs_with_counts(since, task_id, kind, limit) -> list[RunSummary]` method, where `RunSummary` is a small dataclass (or `TypedDict`) with `Run` fields + `span_count: int` + `score_count: int`. This is a `StorageReader`-layer addition; does not touch the schema.

---

## 4. Integration Points

### 4.1 `pyproject.toml` change

```toml
[project.scripts]
plumb = "plumb.cli:app"
```

Changes needed: add `[project.scripts]` entry and move `rich` from optional to required (PD-1 resolved). `typer` is already present.

### 4.2 `config.py` — judge settings needed by `plumb judge run`

`plumb judge run` reads from `Settings`:

```python
class Settings(BaseSettings):
    ...
    judge_provider: str = "anthropic"          # PLUMB_JUDGE_PROVIDER
    judge_anthropic_api_key: str | None = None # PLUMB_JUDGE_ANTHROPIC_API_KEY
    judge_base_url: str | None = None          # PLUMB_JUDGE_BASE_URL
    judge_model: str = "claude-sonnet-4-6"    # PLUMB_JUDGE_MODEL
```

These fields need to be added to `Settings` in `plumb/config.py` as part of this slice (or the judge adapter slice — coordinate to avoid duplication).

### 4.3 `agentsview_attach.backfill` stub

For T3.3, `plumb attach` calls:
```python
from plumb.adapters.agentsview_attach import backfill
result = backfill(path, alias=as_name)
```

If `agentsview_attach.py` does not yet exist, add a minimal stub:
```python
# plumb/adapters/agentsview_attach.py
def backfill(path, alias=None):
    raise NotImplementedError("agentsview_attach not yet implemented")
```

Tests monkeypatch this; the real implementation lands in a separate slice.

### 4.4 `plumb/http.py` stub for `plumb serve`

`plumb serve` calls:
```python
import uvicorn
uvicorn.run("plumb.http:app", host=host, port=port)
```

If `plumb/http.py` doesn't exist yet, add a minimal stub:
```python
# plumb/http.py
from fastapi import FastAPI
app = FastAPI()

@app.get("/health")
def health(): return {"status": "ok"}
```

The full HTTP service is a future slice; the stub satisfies the CLI's import requirement.

---

## 5. Files This Slice Creates or Modifies

| File | Action | Notes |
|---|---|---|
| `plumb/cli.py` | Create | Main CLI module; all 7 commands |
| `plumb/_time_utils.py` | Create | `parse_since` helper |
| `plumb/_output.py` | Create | `format_output` + renderers |
| `plumb/adapters/storage_sqlite.py` | Modify (if PD-4 → A) | Add `list_runs_with_counts` method |
| `plumb/config.py` | Modify | Add judge-related `Settings` fields |
| `plumb/adapters/agentsview_attach.py` | Create stub | `backfill()` raises `NotImplementedError` |
| `plumb/http.py` | Create stub | Minimal FastAPI app with `/health` |
| `pyproject.toml` | Modify | Add `[project.scripts]` entry |
| `tests/cli/` | Create (directory + 7 test files) | One file per command group |
| `tests/helpers/fake_judge.py` | Create | `FakeJudgeAdapter` stub |
| `.github/workflows/ci.yml` | Modify | Add smoke step (T4.2) |

---

## 6. Risks & Mitigations

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| `cli.py` exceeds 400 LOC | Medium | Low | Extract `judge_run` → `plumb/_cli_judge.py` if needed |
| `plumb judge run` content format undefined | High (PD-2 unresolved) | Medium | Use raw blob UTF-8 as interim; easy to change before real adapter lands |
| `StorageAdapter.list_runs_with_counts` scope creep | Low | Low | Single query method; < 20 lines |
| `rich` import adds to cold-import budget | Low | Low | `rich` is only imported inside command functions, not at module level |
| `agentsview_attach` stub breaks if adapter lands with different signature | Medium | Low | Stub uses `*args, **kwargs`; real implementation will have its own TRS |

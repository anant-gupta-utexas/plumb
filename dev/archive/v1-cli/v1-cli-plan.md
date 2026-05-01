# TRS — `plumb/cli.py` (v1 CLI Slice)

**Status:** Draft v1 — derived from [TRD §3.5](../../../docs/2_architecture/TRD.md), follows [v1 Core+API TRS](../../archive/v1-core-and-api/v1-core-and-api-plan.md), [v1 Storage Adapter TRS](../../archive/v1-storage-adapter/v1-storage-adapter-plan.md), concurrent with [v1 Autocapture TRS](../v1-autocapture/v1-autocapture-plan.md)
**Owner:** anant
**Last updated:** 2026-04-29
**Scope:** Fourth component slice of plumb v1 — the `plumb` CLI with all seven subcommands.

> Implementation phases and per-task ACs are in [`v1-cli-tasks.md`](./v1-cli-tasks.md). Design rationale and resolved/pending decisions are in [`v1-cli-context.md`](./v1-cli-context.md).

---

## 1. Overview & Scope

### 1.1 What this slice delivers

A `typer`-driven CLI registered as `plumb` in `pyproject.toml [project.scripts]`:

```
plumb run stats [--since 7d] [--task-id <id>] [--format {table,json,csv}] [--limit N]
plumb score write --run-id <id> --metric <name> --scorer <kind>
                  (--value-numeric <n> | --value-label <v>)
                  [--span-id <id>] [--scorer-version <v>]
plumb example promote --from-run <run-id> [--rubric <path>]
plumb judge run --model <m> --metric <name>
                [--since 7d] [--task-id <id>] [--dry-run]
plumb serve [--host 127.0.0.1] [--port 8765]
plumb attach <path-to-sqlite> [--as <name>]
plumb version
```

**Files produced:**

- `plumb/cli.py` — all commands; ≤ 400 LOC target.
- `plumb/_time_utils.py` — `parse_since(s: str) -> datetime` (shared with HTTP layer later).
- `plumb/_output.py` — `print_table`, `print_json`, `print_csv`, `format_output`.
- `tests/cli/` — one test file per subcommand group (see §10).

### 1.2 What this slice does NOT deliver

- **`plumb/http.py` internals.** `plumb serve` calls `uvicorn.run(...)` but the FastAPI app is a future slice.
- **Judge adapter implementations.** Tested here with `FakeJudgeAdapter`; real adapters are a separate slice.
- **`agentsview_attach` adapter internals.** `plumb attach` calls `backfill()`; adapter body is a separate slice.

### 1.3 Why this slice now

1. **Primary day-to-day touch point.** `plumb run stats` is how engineers verify instrumentation is working.
2. **`plumb score write` unblocks the offline eval loop** — human reviewers can write scores without Python.
3. **`plumb judge run` is the batch-eval entry point** — must exist before judge adapters land.
4. **Typer routing is foundational** — all downstream extensions add subcommands.

### 1.4 Anchor TRD references

| TRD ID | Constraint |
|---|---|
| FR-CLI-1 | Normative subcommand list + argument signatures |
| FR-CLI-2 | Exit 0 on success, non-zero on failure; `plumb serve` starts HTTP service |
| FR-CLI-3 | Human-readable table for TTY; newline-delimited JSON for non-TTY |
| FR-HTTP-1 | `plumb serve` default host `127.0.0.1`; non-loopback → WARNING |
| FR-SCORE-1 | Score write via CLI (second of four paths) |
| FR-SCORE-2 | `scorer_version` NOT NULL on every score row |
| FR-SCORE-3 | XOR: exactly one of `--value-numeric` / `--value-label` |
| NFR-Sec-1 | API keys via env vars only; never CLI args |
| NFR-Use-4 | Public API docstrings ≥ 95% (`interrogate` gate) |

---

## 2. Requirements Summary

### 2.1 Functional requirements

- **FR-CLI-1 (MUST).** Seven subcommands wired exactly as specified above.
- **FR-CLI-2 (MUST).** Non-serve subcommands exit 0 on success, 1 on failure. `plumb serve` Ctrl-C exits 0.
- **FR-CLI-3 (SHOULD).** Default output is formatted table when stdout is a TTY; newline-delimited JSON otherwise.
- **FR-SCORE-2 (MUST).** `scorer_version` defaults to `"cli-unversioned"` if omitted from `score write`.
- **FR-SCORE-3 (MUST).** `--value-numeric` and `--value-label` are mutually exclusive; `typer.BadParameter` if both or neither.
- **FR-HTTP-1 (partial, MUST).** `plumb serve --host 0.0.0.0` emits `logger.warning(...)` before startup.

### 2.2 NFRs in scope

- **NFR-Sec-1 (MUST).** No `--api-key` or similar arg. Pattern-match guard rejects `--model sk-*`.
- **NFR-Sec-3 (MUST).** All queries use parameterized bindings only.
- **NFR-Use-2 (MUST).** `ruff check .` and `ruff format --check .` pass.
- **NFR-Use-4.** All public Typer commands have Google-style docstrings (not gated in CI).
- **NFR-Use-5 (MUST).** `plumb --help` and `plumb version` work on a fresh Python 3.13 install.

---

## 3. Detailed Component Design

### 3.1 Module structure

```
plumb/
├── cli.py            # Typer app; all 7 subcommands (< 400 LOC)
├── _time_utils.py    # parse_since(s) → datetime
└── _output.py        # print_table / print_json / print_csv / format_output
```

`cli.py` imports from `plumb.adapters.storage_sqlite`, `plumb.config`, `plumb.core.entities`, `plumb._time_utils`, `plumb._output`. It does **not** import `plumb.api` (the decorator layer).

### 3.2 Typer app layout

```python
app = typer.Typer(name="plumb", no_args_is_help=True)
run_app     = typer.Typer(no_args_is_help=True)
score_app   = typer.Typer(no_args_is_help=True)
example_app = typer.Typer(no_args_is_help=True)
judge_app   = typer.Typer(no_args_is_help=True)

app.add_typer(run_app,     name="run")
app.add_typer(score_app,   name="score")
app.add_typer(example_app, name="example")
app.add_typer(judge_app,   name="judge")

@run_app.command("stats")        def run_stats(...): ...
@score_app.command("write")      def score_write(...): ...
@example_app.command("promote")  def example_promote(...): ...
@judge_app.command("run")        def judge_run(...): ...
@app.command("serve")            def serve(...): ...
@app.command("attach")           def attach(...): ...
@app.command("version")          def version(): ...
```

### 3.3 Command signatures (normative)

#### `plumb run stats`
```python
def run_stats(
    since:   Annotated[str | None, typer.Option("--since")]   = None,
    task_id: Annotated[str | None, typer.Option("--task-id")] = None,
    format:  Annotated[str,        typer.Option("--format")]  = "table",
    limit:   Annotated[int,        typer.Option("--limit")]   = 100,
) -> None: ...
```
Output columns: `run_id` (first 8 chars), `task_id`, `kind`, `status`, `start_ts` (local), `duration_ms`, `span_count`, `score_count`.

#### `plumb score write`
```python
def score_write(
    run_id:         Annotated[str,         typer.Option("--run-id")],
    metric:         Annotated[str,         typer.Option("--metric")],
    scorer:         Annotated[str,         typer.Option("--scorer")],
    value_numeric:  Annotated[float | None, typer.Option("--value-numeric")] = None,
    value_label:    Annotated[str | None,   typer.Option("--value-label")]   = None,
    span_id:        Annotated[str | None,   typer.Option("--span-id")]       = None,
    scorer_version: Annotated[str | None,   typer.Option("--scorer-version")] = None,
) -> None: ...
```

#### `plumb example promote`
```python
def example_promote(
    from_run: Annotated[str,        typer.Option("--from-run")],
    rubric:   Annotated[Path | None, typer.Option("--rubric", exists=True)] = None,
) -> None: ...
```
Input hash: `input_hash` from LLM span with highest `tokens`; falls back to first span; `"no_spans"` sentinel if zero spans.

#### `plumb judge run`
```python
def judge_run(
    model:   Annotated[str,        typer.Option("--model")],
    metric:  Annotated[str,        typer.Option("--metric")],
    since:   Annotated[str | None, typer.Option("--since")]    = None,
    task_id: Annotated[str | None, typer.Option("--task-id")]  = None,
    dry_run: Annotated[bool,       typer.Option("--dry-run")]  = False,
) -> None: ...
```
Selects runs without an existing score for `metric`. Resolves `JudgeAdapter` from `Settings.judge_provider`.

#### `plumb serve`
```python
def serve(
    host: Annotated[str, typer.Option("--host")] = "127.0.0.1",
    port: Annotated[int, typer.Option("--port")] = 8765,
) -> None: ...
```
Non-loopback guard: if `host not in {"127.0.0.1", "::1", "localhost"}` → `logger.warning(...)` before startup.

#### `plumb attach`
```python
def attach(
    path:    Annotated[Path,       typer.Argument(exists=True)],
    as_name: Annotated[str | None, typer.Option("--as")] = None,
) -> None: ...
```

#### `plumb version`
Prints `plumb {plumb.__version__}` and exits 0.

### 3.4 `_time_utils.py` — `parse_since`

Supported formats: `Nd` (days), `Nw` (weeks), `Nh` (hours), `Nm` (minutes), ISO-8601. Returns UTC-aware `datetime`. Raises `ValueError` on unrecognized input.

```
regex: r"^(\d+)([dwhmDWHM])$"
unit map: d→days, w→weeks, h→hours, m→minutes
fallthrough: datetime.fromisoformat → coerce tzinfo=UTC if naive
```

### 3.5 `_output.py` — output formatting

```python
def is_tty() -> bool: ...
def print_table(rows: list[dict[str, Any]], columns: list[str]) -> None: ...
def print_json(rows: list[dict[str, Any]]) -> None: ...   # newline-delimited
def print_csv(rows: list[dict[str, Any]], columns: list[str]) -> None: ...
def format_output(rows, columns, format) -> None:
    # if format=="table" and not is_tty(): use "json"
```

`rich.Table` is the primary renderer. If `rich` is unavailable (edge case), falls back to plain pipe-separated output.

---

## 4. API Specifications (CLI Argument Contract)

### 4.1 Exit codes

| Scenario | Exit code |
|---|---|
| Success | 0 |
| Invalid argument / parse error | 1 |
| run_id / span_id not found | 1 |
| Storage error | 1 |
| Judge adapter not configured | 1 |
| Ctrl-C on `plumb serve` | 0 |

### 4.2 Argument validation rules

| Command | Rule | Error type |
|---|---|---|
| `score write` | XOR `value_numeric`/`value_label` | `typer.BadParameter` |
| `score write` | `run_id` must exist in DB | `typer.BadParameter` |
| `score write` | `scorer` must be valid `ScorerKind` | `typer.BadParameter` |
| `run stats` | `--format` ∈ {table, json, csv} | `typer.BadParameter` |
| `run stats` | `--since` parseable by `parse_since` | `typer.BadParameter` |
| `judge run` | `--model` non-empty; not `sk-*` pattern | `typer.BadParameter` |
| `example promote` | `--from-run` run must exist | `typer.BadParameter` |

---

## 5. Database Design (CLI Queries)

The CLI does not modify the schema. All writes go through `StorageWriter` methods.

### 5.1 `plumb run stats` — main query
```sql
SELECT
    r.run_id, r.task_id, r.kind, r.status, r.start_ts, r.end_ts,
    COUNT(DISTINCT s.span_id)   AS span_count,
    COUNT(DISTINCT sc.score_id) AS score_count
FROM runs r
LEFT JOIN spans  s  ON s.run_id  = r.run_id
LEFT JOIN scores sc ON sc.run_id = r.run_id
WHERE
    (? IS NULL OR r.start_ts >= ?)
    AND (? IS NULL OR r.task_id  = ?)
GROUP BY r.run_id
ORDER BY r.start_ts DESC
LIMIT ?
```
All values bound via `?` parameters.

### 5.2 `plumb score write` — existence check
```sql
SELECT 1 FROM runs WHERE run_id = ?
```
Then `StorageWriter.write_score(score)`.

### 5.3 `plumb judge run` — unscored runs
```sql
SELECT r.*
FROM runs r
WHERE
    (? IS NULL OR r.start_ts >= ?)
    AND (? IS NULL OR r.task_id = ?)
    AND NOT EXISTS (
        SELECT 1 FROM scores s
        WHERE s.run_id = r.run_id AND s.metric_name = ?
    )
ORDER BY r.start_ts DESC
LIMIT 500
```

### 5.4 Index usage
| Query | Index |
|---|---|
| `run stats` run list | `idx_runs_task_start` |
| span count join | `idx_spans_run` |
| score count join | `idx_scores_run_metric` |
| `judge run` filter | `idx_runs_task_start` + NOT EXISTS subquery |

---

## 6. Algorithm & Logic Design

### 6.1 `parse_since` pseudocode
```
match = regex(r"^(\d+)([dwhmDWHM])$", s)
if match:
    n, unit = int(group(1)), group(2).lower()
    return now_utc() - {"d":timedelta(days=n), "w":timedelta(weeks=n),
                         "h":timedelta(hours=n), "m":timedelta(minutes=n)}[unit]
try:
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
except ValueError:
    raise ValueError(f"Cannot parse since value: {s!r}")
```

### 6.2 `format_output` dispatch
```
if format == "table" and not is_tty():
    format = "json"
dispatch: "table" → print_table | "json" → print_json | "csv" → print_csv
```

### 6.3 `plumb judge run` batch logic
```
adapter = resolve_from_settings()
runs = query_runs_without_score(since, task_id, metric, limit=500)
if dry_run: print(f"Would judge {len(runs)} run(s)"); return
for run in runs:
    content = load_blob_content(run)  # raw bytes decoded UTF-8; "" if missing
    result = adapter.score(metric_name=metric, prompt=load_prompt(metric),
                           content=content, model=model)
    storage.write_score(Score(run_id=run.run_id, metric_name=metric,
                              scorer=JUDGE, scorer_version=result.scorer_version, ...))
```

### 6.4 `example_promote` input hash selection
```
spans = storage.get_spans_for_run(from_run)
llm_spans = [s for s in spans if s.kind == SpanKind.LLM and s.input_hash]
if llm_spans:
    primary = max(llm_spans, key=lambda s: s.tokens_in or 0)
    inputs_hash = primary.input_hash
elif spans and spans[0].input_hash:
    inputs_hash = spans[0].input_hash
else:
    inputs_hash = "no_spans"
```

---

## 7. Error Handling & Edge Cases

| Scenario | Behaviour |
|---|---|
| `StorageError` in any command | Print `"Error: {msg}"` to stderr; exit 1 |
| `plumb run stats` with no rows | Empty table / `[]` JSON; exit 0 |
| `score write` run not found | `typer.BadParameter`; exit 1 |
| `judge run` no runs to score | `"Nothing to judge"`; exit 0 |
| `judge run` adapter not configured | Exit 1 with env var name hint |
| `serve` port in use (`OSError`) | `"Error: port {port} is already in use"`; exit 1 |
| `serve` Ctrl-C | Exit 0 |
| `--since` parse failure | `typer.BadParameter` with format examples |
| `attach` adapter raises | Exit 1; no partial state guarantee (adapter must document rollback) |

---

## 8. Dependencies & Interfaces

### 8.1 Internal imports for `cli.py`
| Module | Usage |
|---|---|
| `plumb.adapters.storage_sqlite.SQLiteStorageAdapter` | All storage reads + writes |
| `plumb.adapters.blobstore_fs.FilesystemBlobStore` | Blob content for `judge run` |
| `plumb.adapters.agentsview_attach.backfill` | `attach` delegation |
| `plumb.config` | `get_settings`, `ensure_data_dir` |
| `plumb.core.entities` | `Run`, `Score`, `Example`, `ScorerKind`, `ExampleSource` |
| `plumb.core.errors` | `StorageError`, `JudgeError`, `ValidationError` |
| `plumb.__version__` | `version` command |
| `plumb._time_utils` | `parse_since` |
| `plumb._output` | `format_output` |

### 8.2 External dependencies
| Package | Purpose |
|---|---|
| `typer ≥ 0.12` | CLI framework |
| `rich ≥ 13` | Table rendering (see PD-1 in context) |
| `uvicorn ≥ 0.30` | `serve` delegation |

### 8.3 `JudgeAdapter` interface (for `judge run`)
```python
class JudgeAdapter(Protocol):
    name: str; version: str
    def score(self, *, metric_name, prompt, content, model, timeout_s=60.0) -> JudgeResult: ...
```
Tests inject `FakeJudgeAdapter`. Real adapters land in a future slice.

---

## 9. Security Considerations

- **No API key args.** `--model` validated against `r"^(sk-|anthropic_)"` pattern; match → `typer.BadParameter`.
- **Parameterized SQL.** All queries use `?` bindings (NFR-Sec-3); `ruff S608` enforced.
- **Path traversal.** `typer.Argument(exists=True)` validates `attach` path; no user-string path construction beyond this.
- **Rubric content.** Stored verbatim as TEXT; no HTML execution surface in CLI.
- **Non-loopback warning.** Advisory `logger.warning`; does not block startup.

---

## 10. Testing Strategy

### 10.1 Test files

| File | Covers |
|---|---|
| `tests/cli/test_time_utils.py` | `parse_since` unit tests |
| `tests/cli/test_output.py` | `format_output` unit tests |
| `tests/cli/test_cli_run_stats.py` | `plumb run stats` unit + integration |
| `tests/cli/test_cli_score_write.py` | `plumb score write` unit + integration |
| `tests/cli/test_cli_example_promote.py` | `plumb example promote` unit + integration |
| `tests/cli/test_cli_judge_run.py` | `plumb judge run` with `FakeJudgeAdapter` |
| `tests/cli/test_cli_misc.py` | `version`, `serve`, `attach` |
| `tests/helpers/fake_judge.py` | `FakeJudgeAdapter` stub |

### 10.2 Key test cases (summary)

**`run stats`:** empty DB, 3 runs present, `--since` filter, `--task-id` filter, `--format json`, `--format csv`, invalid format, invalid `--since`, non-TTY defaults to JSON.

**`score write`:** numeric write, label write, both flags → exit 1, neither → exit 1, unknown run → exit 1, invalid scorer → exit 1, omitted `scorer_version` defaults to `"cli-unversioned"`.

**`example promote`:** success with LLM span, with rubric file, run not found, zero-span run (`inputs_hash="no_spans"`), multi-span selects highest-token LLM span.

**`judge run`:** dry-run, scores written, already-scored runs skipped, adapter not configured, `--since`/`--task-id` filters.

**misc:** `version` output, non-loopback warning, `attach` delegates, `attach` path not found.

### 10.3 Mocking policy

| Dependency | How |
|---|---|
| Judge adapter | `FakeJudgeAdapter` implementing `JudgeAdapter` Protocol |
| `uvicorn.run` | `monkeypatch` to no-op |
| `agentsview_attach.backfill` | `monkeypatch` to returning `{"imported": 5}` |
| TTY detection | `monkeypatch plumb._output.is_tty` |
| Clock | `FakeClock` reused from existing test helpers |

Storage: integration tests use real `SQLiteStorageAdapter` backed by `tmp_path`.

### 10.4 Coverage target

≥ 80% on `plumb/cli.py`, `plumb/_time_utils.py`, `plumb/_output.py`. Project-wide threshold remains ≥ 75%.

---

## 11. Performance Considerations

CLI is not a hot path. Informal targets:

| Command | Expected wall time |
|---|---|
| `plumb version` | < 200 ms (cold import budget, NFR-Perf-6) |
| `plumb run stats` (100 rows) | < 500 ms |
| `plumb score write` | < 200 ms |
| `plumb example promote` | < 300 ms |
| `plumb judge run` | bounded by judge API latency |

`run stats` JOIN is covered by existing indexes; no EXPLAIN QUERY PLAN optimization needed for v1.

---

*See [`v1-cli-tasks.md`](./v1-cli-tasks.md) for the full implementation phase breakdown and per-task acceptance criteria.*
*See [`v1-cli-context.md`](./v1-cli-context.md) for pending decisions and design rationale.*

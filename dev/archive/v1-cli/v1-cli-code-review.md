# v1-cli — Code Review

**Reviewer persona:** Code Reviewer (consult-experts)
**Date:** 2026-05-01
**Scope reviewed:**
- [plumb/cli.py](plumb/cli.py) (514 LOC)
- [plumb/_time_utils.py](plumb/_time_utils.py) (48 LOC)
- [plumb/_output.py](plumb/_output.py) (71 LOC)
- [plumb/adapters/storage_sqlite.py](plumb/adapters/storage_sqlite.py) — `RunSummary` + `list_runs_with_counts` only (lines 32-58, 539-570)
- [plumb/adapters/agentsview_attach.py](plumb/adapters/agentsview_attach.py) (stub)
- [plumb/http.py](plumb/http.py) (stub)
- [plumb/config.py](plumb/config.py) (judge fields)
- [tests/cli/](tests/cli/) (7 files + conftest)

**Anchor docs:** [v1-cli-plan.md](dev/active/v1-cli/v1-cli-plan.md), [v1-cli-context.md](dev/active/v1-cli/v1-cli-context.md), [v1-cli-tasks.md](dev/active/v1-cli/v1-cli-tasks.md), [TRD §3.5](docs/2_architecture/TRD.md), [SYSTEM_DESIGN.md](docs/2_architecture/SYSTEM_DESIGN.md).

---

## Executive Summary

The v1-cli slice is **largely sound and merge-ready in spirit**: all seven subcommands are implemented, every Phase-1–4 acceptance criterion in [v1-cli-tasks.md](dev/active/v1-cli/v1-cli-tasks.md) is checked, the test surface is broad (≈ 50 cases across 7 files, including unit + integration with a real `SQLiteStorageAdapter`), and the security posture (parameterized SQL, no key-shaped CLI args, non-loopback warning, mode-0700 data dir) is solid.

That said, several issues warrant fixing **before merge**, and a few design choices deserve a follow-up conversation. The most material findings:

1. **CRITICAL — `_die()` lies about its return type and breaks static reasoning.** It is annotated `-> None` but always raises; helpers calling it (`_resolve_since`, `_validate_format`) silently return `None` after the raise, while the type-checker has no way to know. Already disguising a real bug in `score_write` (see C-2).
2. **CRITICAL — `score_write` re-raises `_die`'s `typer.Exit(1)` through a broad `except Exception` and immediately re-`_die`s it as a string** (`"Exit"`). The user sees a confusing error.
3. **CRITICAL — `judge run` reaches into `storage._conn` and a private `_row_to_run` from `cli.py`.** Violates the adapter boundary that PD-4 was specifically resolved to defend.
4. **IMPORTANT — `cli.py` is 514 LOC vs the ≤ 400 LOC target** in plan §3.1 / DR-2. The `judge_run` extraction explicitly contemplated by DR-2 has not been done.
5. **IMPORTANT — DR-5 violated.** The plan/context committed to the literal sentinel string `"no_spans"` for zero-span runs (so consumers can distinguish it from a real sha256). The implementation instead writes `sha256(b"no_spans")` — a perfectly valid 64-char hex digest indistinguishable from a real input hash. This silently changes a documented contract.
6. **IMPORTANT — `serve --host`'s `OSError` handler will misclassify real port-bind failures** because the substring check (`"address" in msg or "in use" in msg`) overlaps and misfires on unrelated `OSError`s.

None of these are show-stoppers; all are either ~5–30-line fixes or documentation reconciliations. Details and severity tags below.

---

## Critical Issues (must fix before merge)

### C-1. `_die()` typed `-> None` while it always raises — hides a bug in `_resolve_since`

[plumb/cli.py:70-73](plumb/cli.py:70)

```python
def _die(msg: str) -> None:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)
```

This should be `-> NoReturn`. Two concrete consequences:

1. **`_resolve_since` reads as "returns `datetime | None`" but actually has an unreachable fall-through:**
   [plumb/cli.py:76-82](plumb/cli.py:76)
   ```python
   def _resolve_since(since_str: str | None) -> datetime | None:
       if since_str is None:
           return None
       try:
           return parse_since(since_str)
       except ValueError as exc:
           _die(f"Invalid --since value: {exc}")  # raises, but mypy thinks fall-through returns None
   ```
   If `_die` is later refactored or wrapped in a way that swallows the exception, callers will get a silent `None` and behave as if `--since` was absent. Annotating `_die -> NoReturn` gives the type checker (and humans) the contract.

2. **Same for `_validate_format`:** `[plumb/cli.py:85-88](plumb/cli.py:85)` reads as if `_die` could return; the explicit `return fmt` after it is the only thing keeping that path correct.

**Fix:**
```python
from typing import NoReturn
def _die(msg: str) -> NoReturn:
    typer.echo(f"Error: {msg}", err=True)
    raise typer.Exit(1)
```

**Severity rationale:** Critical because it interacts with C-2 below.

---

### C-2. `score_write`'s broad `except Exception` swallows `_die`'s `typer.Exit` and re-`_die`s it as `"Exit"`

[plumb/cli.py:195-215](plumb/cli.py:195)

```python
try:
    with _get_storage() as storage:
        run = storage.get_run(run_id)
        if run is None:
            _die(f"Run {run_id!r} not found.")          # raises typer.Exit(1)
        ...
        storage.write_score(score)
except Exception as exc:
    _die(str(exc))                                       # catches the Exit, prints "Error: Exit"
```

`typer.Exit` is a subclass of `click.exceptions.Exit`, which is a `RuntimeError`-derived exception. The broad `except Exception` catches it, re-derives a message via `str(exc)` (which yields `"Exit"`), and re-raises a fresh `typer.Exit(1)` — losing the original message.

The test suite happens to pass because `test_score_write_unknown_run_exit_1` only asserts `"not found" in combined`, but the **first** error the user sees in real life when they hit this path will be:

```
Error: not found.
Error: Exit
```

The same pattern exists at:
- `judge_run` `[plumb/cli.py:397-400](plumb/cli.py:397)` — partially mitigated by the explicit `except typer.Exit: raise` guard, which is itself a code smell that proves the author already knew about this bug elsewhere
- `attach` is fine because it scopes to `except StorageError` only
- `example_promote` `[plumb/cli.py:281-282](plumb/cli.py:281)` has the same bug but isn't currently observable

**Fix (apply consistently):**
```python
except typer.Exit:
    raise
except Exception as exc:
    _die(str(exc))
```
…or, better, replace the broad `except Exception` with the specific exceptions that `storage.*` actually raises (`StorageError`, `ValidationError`, `sqlite3.Error`).

**Severity rationale:** User-visible incorrect error message; hides downstream failures during debugging.

---

### C-3. `judge_run` reaches into `storage._conn` and imports `_row_to_run` from `cli.py` — violates adapter boundary

[plumb/cli.py:332-354](plumb/cli.py:332)

```python
db_rows = storage._conn.execute(   # noqa: SLF001
    """SELECT r.* FROM runs r WHERE ...""",
    (since_iso, since_iso, task_id, task_id, metric),
).fetchall()
from plumb.adapters.storage_sqlite import _row_to_run
runs = [_row_to_run(r) for r in db_rows]
```

This is exactly the pattern that PD-4 was resolved to **avoid** (see [v1-cli-context.md §3 PD-4](dev/active/v1-cli/v1-cli-context.md)):

> **Decision:** Add `list_runs_with_counts(...)` as a first-class method on `SQLiteStorageAdapter`. **Rationale:** SQL stays inside the adapter layer; CLI stays clean. … One well-tested method is better than leaking `_conn` out of the adapter boundary.

The `noqa: SLF001` suppression and `from plumb.adapters.storage_sqlite import _row_to_run` (importing a private helper across a layer boundary) make this a textbook leakage of internal state outside the adapter.

It also makes the SQL query un-tested at the adapter layer — the only test that exercises this path is `test_judge_run_skips_already_scored`, which is a CLI-level integration test. If the column names ever change in the schema, the breakage will surface as an opaque CLI failure, not an adapter unit-test failure.

**Fix:** Add `list_runs_unscored_for_metric(*, metric: str, since: datetime | None, task_id: str | None, limit: int = 500) -> list[Run]` (or similar) on `SQLiteStorageAdapter`, mirroring how `list_runs_with_counts` was added. Move the SQL there, drop the `_conn` reach-in and the cross-package private import. ~25 LOC net change; reduces `cli.py` size too.

**Severity rationale:** Architectural violation in the very same slice that introduced the ports-and-adapters method to fix. Caught early it's a 25-line refactor; caught later it sets a precedent.

---

## Important Improvements (should fix)

### I-1. DR-5 contract drift: `"no_spans"` sentinel silently became `sha256(b"no_spans")`

Plan [v1-cli-plan.md §3.3](dev/active/v1-cli/v1-cli-plan.md) and context [DR-5](dev/active/v1-cli/v1-cli-context.md) commit to:

> `"no_spans"` is a human-readable sentinel that is **not a valid sha256 hex digest, so consumers can distinguish it**.

The implementation at [plumb/cli.py:264-265](plumb/cli.py:264) writes:
```python
inputs_hash_final = hashlib.sha256(b"no_spans").hexdigest()
```
which is `94a3...` — a perfectly valid 64-char hex digest. **Consumers cannot distinguish a zero-span promotion from a real input hash that happens to coincide.** The whole point of DR-5 (per its own §3 rationale block) is gone.

The test at `test_example_promote_zero_span_run` asserts the hashed form, so the test was edited to match the (changed) implementation rather than the documented contract — this is exactly the anti-pattern called out in [CLAUDE.md "Agent Working Rules" §1](CLAUDE.md).

**Two valid resolutions, pick one and document it:**
- **A.** Restore the literal `"no_spans"` sentinel as the plan/context specify. Requires checking the schema's CHECK constraint on `inputs_hash` length (if any). If schema requires 64-char hex, document the deviation.
- **B.** Update the plan + context to record that `inputs_hash` must be a valid 64-char hex (presumably for schema/CHECK reasons), and pick a clearly-documented well-known sentinel value (e.g. `"0" * 64` or the hash chosen here) and note in the example row's metadata that it represents zero-span. Update DR-5 to reflect the new contract.

Either way, the docs and code must agree.

---

### I-2. `cli.py` is 514 LOC vs ≤ 400 LOC plan target — `judge_run` extraction not done

Plan §3.1 and DR-2 explicitly call out:

> If `cli.py` grows beyond 400 LOC, split `judge_run` into `plumb/_cli_judge.py` — it's the most complex command.

`cli.py` is 514 LOC. `judge_run` plus its two helpers is ~135 LOC (lines 287–435). Extracting them into `plumb/_cli_judge.py` brings `cli.py` to ~380 LOC and aligns with the documented threshold. The CLAUDE.md style guide (`files < 400 lines`) reinforces this.

This is a 30-minute mechanical refactor; doing it now also addresses C-3 cleanly (the new `list_runs_unscored_for_metric` method makes `_cli_judge.py` smaller).

---

### I-3. `serve` `OSError` substring matcher will mis-classify unrelated errors

[plumb/cli.py:467-470](plumb/cli.py:467)
```python
except OSError as exc:
    if "address" in str(exc).lower() or "in use" in str(exc).lower():
        _die(f"port {port} is already in use.")
    _die(str(exc))
```

`"address" in msg.lower()` will match almost any networking-related `OSError` whose message mentions "address" (e.g. `[Errno 99] Cannot assign requested address` from a non-existent host, `getaddrinfo failed`). The user then sees `"port 8765 is already in use"` for an entirely different problem.

**Fix:** Use `errno` instead of substring matching:
```python
import errno
except OSError as exc:
    if exc.errno == errno.EADDRINUSE:
        _die(f"port {port} is already in use.")
    _die(str(exc))
```

The existing `test_serve_port_in_use_exits_1` mocks `OSError("address already in use")` without setting `errno`, so it will need updating to `OSError(errno.EADDRINUSE, "address already in use")`.

---

### I-4. `judge_run` adapter loader unconditionally raises `NotImplementedError` and is monkey-patched in tests — the dry-run / nothing-to-judge paths can never load it, but the real `--metric` path always crashes

[plumb/cli.py:403-406](plumb/cli.py:403)
```python
def _load_judge_adapter(provider: str, model: str):
    raise NotImplementedError(f"Judge provider {provider!r} not yet implemented.")
```

Currently this is fine because:
- `--dry-run` and "no runs" paths return before calling it.
- Tests `monkeypatch("plumb.cli._load_judge_adapter", return_value=fake)`.

But once a real `SQLiteStorageAdapter` is in production with no judge adapter implemented yet, the **first non-dry-run invocation** will crash with `NotImplementedError`, get caught by the broad `except Exception`, get re-raised by `_die("Judge provider …")`, and exit 1 — **but not before potentially writing zero scores partially mid-loop** (it raises before the `for run in runs` loop, so we're actually safe here, but the architecture is fragile).

More importantly, `provider="fake"` is not a real provider — a future implementer must remember to dispatch on `provider` here. Recommend either:
- Adding a registry pattern: `_PROVIDER_REGISTRY: dict[str, Callable[[str], JudgeAdapter]] = {}` so adapters self-register, or
- Documenting at the function-level that this is a deliberate stub and listing the integration contract for the future adapter slice.

A `# TODO(adapter-slice): wire real adapters per PD-2` comment at minimum would help the next reader.

---

### I-5. `_get_storage()` re-instantiates a `_RealClock` class on every call — and the same class exists in `tests/cli/conftest.py::_Clock`

[plumb/cli.py:55-67](plumb/cli.py:55)
```python
def _get_storage():
    ...
    class _RealClock:
        def now(self) -> datetime:
            return datetime.now(UTC)
    ...
    return SQLiteStorageAdapter(db_path, clock=_RealClock())
```

Defining `_RealClock` inside the function body means:
- A fresh class is created on every `_get_storage()` call. Negligible cost, but smells.
- It's not unit-testable in isolation.
- It duplicates the `_Clock` already in `tests/cli/conftest.py`.

There's almost certainly already a real-clock implementation in `plumb.adapters` (the v1-storage-adapter slice), or it should live in a shared module. Promoting this to a module-level `_RealClock` (or, better, importing the canonical one) tightens the seam.

---

### I-6. `_load_run_content` instantiates `FilesystemBlobStore(ensure_data_dir(get_settings()))` on every run in the loop

[plumb/cli.py:409-435](plumb/cli.py:409)

Inside the `for run in runs` loop, `_load_run_content` is called per-run, and each call **re-runs `get_settings()` (lru-cached, OK), `ensure_data_dir()` (idempotent but does a path resolve + stat), and constructs a fresh `FilesystemBlobStore`.** For 500 runs that's 500 redundant constructions. Hoist the blob store creation out of the loop and pass it in:

```python
blob_store = FilesystemBlobStore(ensure_data_dir(get_settings()))
for run in runs:
    content = _load_run_content(storage, blob_store, run.run_id)
    ...
```

Also: the broad `except Exception: return ""` at lines 418-419 swallows every error including `KeyboardInterrupt` (no — Python's `Exception` excludes `BaseException`, OK). But it also swallows `PermissionError` from `ensure_data_dir`, `pydantic.ValidationError` from `get_settings()`, etc. Recommend narrowing to `(BlobNotFoundError, OSError)` and letting genuine config errors bubble to `_die`.

---

### I-7. `judge_run` writes a score row from a `Score` object whose constructor may have raised inside the `try` — but the `storage.write_score(score)` is *outside* the `try`

[plumb/cli.py:366-396](plumb/cli.py:366)

```python
for run in runs:
    try:
        ...
        score = Score(...)            # constructed in try
    except Exception as exc:
        ...
        score = Score(score_id=...,   # constructed in except
                      ...,
                      value_label="error")
    storage.write_score(score)        # outside try — UnboundLocalError if both fail
```

If the `except` block itself raises (e.g. `Score(...)` validation error because `value_label="error"` violates some constraint, or `ScorerKind.JUDGE` ever rotates), the loop body crashes with `UnboundLocalError: local variable 'score' referenced before assignment`. Move `storage.write_score(score)` inside the `try`/`except` (place it in a `finally`-like position via `else`) or wrap the whole iteration in a try that always logs-and-continues:

```python
for run in runs:
    try:
        ...
        score = Score(...)
    except Exception as exc:
        logger.warning(...)
        score = Score(..., value_label="error")
    try:
        storage.write_score(score)
    except Exception as exc:
        logger.warning("Failed to write error-score for run %s: %s", run.run_id[:8], exc)
```

Plan §6.3 anticipates this with the `INT-JUDGE-5` reference; the implementation matches the spirit but has the unbound-local pothole.

---

### I-8. `attach`'s `Path` argument: `typer.Argument(exists=True)` was specified in the plan but is missing in the implementation

Plan §3.3:
```python
def attach(
    path: Annotated[Path, typer.Argument(exists=True)],
    ...
```

Implementation [plumb/cli.py:481-485](plumb/cli.py:481):
```python
def attach(
    path: Annotated[Path, typer.Argument(help=_PATH_HELP)],
    ...
```

`exists=True` is dropped; instead there's a manual `if not path.exists(): _die(...)` at line 494. This works but:
- Loses the typer auto-completion / shell-tab niceness.
- The plan task T3.3 AC says "Non-existent path → Typer rejects before delegating; `backfill` never called" — implied to be Typer-native, since the test `test_attach_nonexistent_path_exits_1` only checks `exit_code != 0`.

Restoring `exists=True, file_okay=True, dir_okay=False, readable=True` matches the plan and gives a sharper error. Cost: 0 LOC.

---

### I-9. Score-write XOR check only validates `value_numeric is not None` vs `value_label is not None` — `--value-label ""` (empty string) is treated as set

[plumb/cli.py:181-184](plumb/cli.py:181)
```python
numeric_set = value_numeric is not None
label_set = value_label is not None
if numeric_set == label_set:
    _die("Exactly one of --value-numeric or --value-label must be provided.")
```

Passing `--value-label ""` makes `label_set = True`, the XOR check passes, and a score row is written with an empty-string label. The schema may or may not reject this (depending on a `CHECK(length(value_label) > 0)` constraint, if any).

If the entity validator (`Score`) doesn't already enforce non-empty `value_label`, add `if value_label is not None and not value_label: _die(...)` before the XOR check. Verify by reading `plumb/core/entities.py`'s `Score` validator.

---

## Minor Suggestions (nice to have)

### M-1. `re.match(r"^(sk-|anthropic_)", model)` only catches two key shapes

[plumb/cli.py:315](plumb/cli.py:315)

Real-world API key prefixes also include OpenRouter (`sk-or-`), Together (`together_`), Mistral (`...`), and the bare `sk_test_`/`sk_live_` Stripe-style. Consider broadening the regex slightly or, better, refactoring to a strict allow-list of valid model name shapes (e.g. `^[a-z0-9._:/-]+$` and length bounds) — keys tend to have high entropy and shape recognizers are easier to maintain than denylists.

Plan §9 only requires `^(sk-|anthropic_)`, so this is non-blocking.

### M-2. `format_output` falls back to JSON in non-TTY but `_output.format_output`'s docstring doesn't mention this

[plumb/_output.py:51-71](plumb/_output.py:51)

The docstring lists the three formats and the `ValueError`, but the silent table→json fallback is a non-obvious side effect that callers must know about. Add a single line:

> When `fmt="table"` and stdout is not a TTY, output is silently downgraded to newline-delimited JSON for pipeability (FR-CLI-3).

### M-3. `print_json(rows)` uses bare `print(...)` — won't honour the same stdout buffer that other code paths target, and bypasses `typer.echo` semantics

[plumb/_output.py:18-19](plumb/_output.py:18)

Mostly fine because `print` writes to `sys.stdout` which `format_output`'s test monkeypatches anyway, but for consistency with `typer.echo(...)` use elsewhere in `cli.py`, prefer `typer.echo(json.dumps(row, default=str))`. This also yields color-stripping and CRLF handling on Windows for free.

(Minor because v1 is Linux/macOS-first per TRD.)

### M-4. `print_table` swallows `ImportError` only — does not handle other rich startup failures

[plumb/_output.py:31-48](plumb/_output.py:31)

`from rich.console import Console` could raise `ModuleNotFoundError` (subclass of `ImportError`, OK) but `Console().print(table)` could conceivably raise a `rich.errors.MarkupError` for ill-formed strings in a row value. Since v1 only renders plain values from `_RUN_STATS_COLUMNS` (all simple scalars), this is theoretical — but a wrapping `try/except Exception → fallback` would harden the path. Extremely low priority.

### M-5. `parse_since("0d")` raises but `parse_since("01d")` is `1 day` and accepted

Probably fine, but worth noting for documentation: leading zeros in the relative form work (`"01d" = "1d"`). The regex `^(\d+)([dwhmDWHM])$` accepts them. If you want to reject `"00d"` and `"01d"` you'd need a tighter regex.

### M-6. Task T3.3 has one unchecked AC: `StorageError from backfill → exit 1 + error message to stderr`

Tasks file shows this as `[ ]`, and indeed there is no test for it in `test_cli_misc.py`. The implementation [plumb/cli.py:497-501](plumb/cli.py:497) does handle this case:

```python
try:
    result = backfill(path, alias=as_name)
    typer.echo(str(result))
except StorageError as exc:
    _die(str(exc))
```

Add a 5-line test:
```python
def test_attach_storage_error_exits_1(tmp_path) -> None:
    fake_db = tmp_path / "agents.db"; fake_db.touch()
    with patch("plumb.adapters.agentsview_attach.backfill",
               side_effect=StorageError("corrupt schema")):
        result = runner.invoke(app, ["attach", str(fake_db)])
    assert result.exit_code == 1
    assert "corrupt schema" in result.output
```

---

## Architecture Considerations

### A-1. Inline `import` statements inside command bodies — consistent and probably the right choice for cold-import budget, but worth a comment

[plumb/cli.py](plumb/cli.py) imports `plumb.adapters.storage_sqlite`, `plumb.config`, `plumb.core.entities`, `hashlib`, `uvicorn`, `plumb.adapters.agentsview_attach`, etc. inside command function bodies. This is intentional per [v1-cli-context.md §6 risk row](dev/active/v1-cli/v1-cli-context.md):

> `rich` is only imported inside command functions, not at module level

…and it's good practice for a CLI that has to honour NFR-Perf-6's cold-import budget (`plumb version` < 200 ms). But the convention is not documented anywhere in `cli.py`. Consider a one-line comment near the top of the module:

```python
# NOTE: heavyweight imports (pydantic, sqlite3, uvicorn, rich, hashlib) are deferred
# to command bodies to keep `plumb --help` and `plumb version` cold-start under
# the NFR-Perf-6 200ms budget. Do not move them to the module top.
```

### A-2. `plumb.cli` does not import `plumb.api` (DR-1) — confirmed and good

Verified: no `from plumb import api` or `from plumb.api import ...`. Maintains the clean-import invariant.

### A-3. `plumb/__init__.py` re-exports an extensive public surface (autocapture, run, errors) but **not** the CLI app object

[plumb/__init__.py:31-55](plumb/__init__.py:31)

This is correct — the CLI is exposed via `[project.scripts]` in `pyproject.toml`, not via the Python import surface. Importing `plumb` in user code should not pull in `typer`/`rich`/`uvicorn`. Good separation. Worth documenting in `core_concepts.md` if not already.

### A-4. `RunSummary` in `storage_sqlite.py` uses `__slots__` and a `sqlite3.Row` constructor — slight smell

[plumb/adapters/storage_sqlite.py:36-58](plumb/adapters/storage_sqlite.py:36)

The class is a thin row-projection. Since `Run` itself is a `frozen dataclass`, consider making `RunSummary` a `frozen dataclass(slots=True)` for consistency with the rest of the entity layer. The `sqlite3.Row` → `RunSummary` conversion would then be a free function (`_row_to_run_summary`) mirroring the existing `_row_to_run`. This also simplifies test fixtures (you can construct `RunSummary` directly without faking a `sqlite3.Row`).

Non-blocking; cosmetic.

### A-5. The judge run loop is the only place `cli.py` does multi-step business logic — supports DR-2's "extract if it grows" decision

A future `_cli_judge.py` extraction would also let the dry-run / nothing-to-judge / batch-loop logic be unit-tested with a fake storage at a finer granularity than the current `CliRunner` integration tests.

---

## Test Coverage Notes

- ✅ ≈50 tests across 7 files; pass per T4.1's `--cov-fail-under=75`.
- ✅ `FakeJudgeAdapter` in `tests/helpers/fake_judge.py` (referenced; not read in this review — assumed to honour the `JudgeAdapter` Protocol).
- ✅ TTY/non-TTY behaviour, format dispatch, time parsing edge cases — well covered.
- ⚠️ **No test for the documented `_die` -> `_resolve_since` fall-through path** (will become visible if C-1 is fixed by adding `NoReturn`).
- ⚠️ **No test for the `OSError` non-EADDRINUSE branch in `serve`** — addressing I-3 should add one.
- ⚠️ **No test for `--value-label ""`** (I-9).
- ⚠️ **No test for `attach` with `StorageError`** (M-6).
- ⚠️ The `test_run_stats_format_csv` test [tests/cli/test_cli_run_stats.py:138-145](tests/cli/test_cli_run_stats.py:138) only asserts the header line starts with `"run_id"` — would not catch a regression that emits e.g. tab-separated output. Consider parsing through `csv.DictReader` and asserting one full row.

---

## Documentation Reconciliation

Before merge, the following plan/context items need a one-line update:

| Item | Current state in plan/context | Reality in code | Recommended action |
|---|---|---|---|
| DR-5 sentinel | `"no_spans"` literal | `sha256(b"no_spans")` hex | **Fix code** to match plan, or **update DR-5** to record the new contract (with rationale) |
| DR-2 LOC threshold | "If `cli.py` grows beyond 400 LOC, split `judge_run`" | `cli.py` is 514 LOC, no split | Apply the split (preferred) or update DR-2 with the new ≤ 600 LOC ceiling |
| PD-4 boundary | "One well-tested method is better than leaking `_conn`" | `judge_run` reaches into `_conn` and imports private `_row_to_run` | Apply the boundary fix (C-3) |
| `attach` `Path(exists=True)` | Spec uses `typer.Argument(exists=True)` | Manual `path.exists()` check | Restore typer-native validation |

The **CLAUDE.md "Agent Working Rules" §1** explicitly warns against editing tests to match changed implementation — DR-5 vs the zero-span test is exactly that pattern. Surfaces in the review because honesty about the deviation is a gate for merge.

---

## Next Steps

Suggested order of operations (each item is a self-contained ~5–30 LOC change):

1. **C-1, C-2** — `_die -> NoReturn` + tighten `except Exception` clauses. ~10 LOC. High-leverage; unblocks reasoning about C-3 and I-7.
2. **C-3** — Add `list_runs_unscored_for_metric` to `SQLiteStorageAdapter`; rip `_conn`/`_row_to_run` out of `cli.py`. ~25 LOC + 1 unit test.
3. **I-1** — Resolve `"no_spans"` sentinel: pick (A) or (B), update plan/code/test together. ~5 LOC.
4. **I-2** — Extract `judge_run` to `plumb/_cli_judge.py`. ~135 LOC moved (no logic change). After (C-3) so the extraction is small.
5. **I-3** — Switch `serve` `OSError` handler to `errno.EADDRINUSE`. ~5 LOC + test patch.
6. **I-7** — Reorder `storage.write_score(score)` inside the per-run try. ~5 LOC.
7. **I-8** — Restore `typer.Argument(exists=True)` for `attach`. ~1 LOC.
8. **I-4, I-5, I-6, I-9** — small hardening passes; can be batched into a single PR labeled "cli: hardening".
9. **M-1 to M-6** — defer to a follow-up "polish" PR.

After fixes:
- Re-run `pytest --cov` and confirm `cli.py` coverage stays at ≥ 90%.
- `ruff check . && ruff format --check . && mypy --strict plumb/core/`.
- Manually run `plumb run stats`, `plumb judge run --dry-run`, `plumb serve --host 127.0.0.1 --port 8765` against a real `~/.plumb/plumb.db` to sanity-check.
- Move `dev/active/v1-cli/` → `dev/archive/v1-cli/` after PR merge (already noted as `[ ]` in the tasks file).

---

**Code review saved to:** `dev/active/v1-cli/v1-cli-code-review.md`

**Please review the findings and approve which changes to implement before I proceed with any fixes.** I have not modified any source code. The review above is advisory; I'll wait for your direction on which items (Critical / Important / Minor / Architecture) to address and in what order.

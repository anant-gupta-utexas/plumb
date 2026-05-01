---
project: plumb
status: building
phase: v1 (Phase 9 complete, Week 5)
last_updated: 2026-05-01
next_gate: v1-http / v1-judge-adapters
blocked_on: null
---

# plumb — status

## Current

v1-cli slice shipped and archived. `plumb/cli.py` (384 LOC) + `plumb/_cli_judge.py` (168 LOC)
implement all seven subcommands: `run stats`, `score write`, `example promote`, `judge run`,
`serve`, `attach`, `version`. Supports filtering (since, task-id), output formats (table/json/csv),
and dry-run mode. All 569 tests pass; ruff-clean. Code review findings fully addressed.

## Recent (last 7 days)

- v1-autocapture Phases 1–8 complete and archived.
- v1-cli code review (2026-04-30) findings fixed and merged:
  - **C-1**: `_die()` annotated `-> NoReturn` (was `-> None`); fixes silent fall-through
    in `_resolve_since` caught by type checker.
  - **C-2**: Added `except typer.Exit: raise` guards in `run_stats`, `score_write`,
    `example_promote` to prevent re-catching and double-printing error messages.
  - **C-3**: Added `list_runs_unscored_for_metric()` to `SQLiteStorageAdapter`;
    removed `_conn` reach-in and private `_row_to_run` import from cli.py (PD-4).
  - **I-1/DR-5**: Updated context: inputs_hash enforced as 64-char hex by entity layer;
    zero-span runs use `sha256(b"no_spans")` as deterministic sentinel.
  - **I-2**: Extracted `judge_run` to `plumb/_cli_judge.py` (~135 LOC); brought cli.py
    from 514 to 384 LOC (below 400-LOC target per DR-2).
  - **I-3**: Fixed serve `OSError` handler to use `errno.EADDRINUSE` instead of substring.
  - **I-4/5/6/8/9**: Stub comment for judge adapters, _RealClock module-level,
    blob_store hoist, typer-native path validation, empty label guard.
  - **M-6**: Added `test_attach_storage_error_exits_1`.
  - Moved `dev/active/v1-cli/ → dev/archive/v1-cli/`.
- All 569 tests pass; source ruff-clean.

## Next

- Implement v1-http: FastAPI read-only service (port 8765).
- Implement v1-judge-adapters: Anthropic native + OpenAI-compat (OpenRouter / Ollama /
  vLLM / LM Studio / LiteLLM).
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- None. Autocapture is stable; storage + core layers are load-bearing.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/SYSTEM_DESIGN.md`
- CLI archive: `dev/archive/v1-cli/`
- Autocapture archive: `dev/archive/v1-autocapture/`
- Prior archive: `dev/archive/v1-storage-adapter/`
- Deferred features: `docs/2_architecture/deferred-features.md`

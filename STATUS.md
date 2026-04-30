---
project: plumb
status: building
phase: v1 (Phase 7, Week 4)
last_updated: 2026-04-29
next_gate: v1-autocapture slice (monkey-patch entry points)
blocked_on: null
---

# plumb — status

## Current

v1 core + API + storage adapter complete. `plumb/core/`, `plumb/api.py`,
`plumb/adapters/` (SQLiteStorageAdapter, FilesystemBlobStore) shipped with
full test coverage (94% adapters, ≥90% core). Storage layer verified under
durability (SIGKILL), concurrency (WAL), and performance (p95 ~6 ms run-close)
gates. Code review findings (12 items) addressed and merged. Ready for
autocapture, CLI, HTTP, judge slices.

## Recent (last 7 days)

- v1-storage-adapter Phase 7–8 complete: SIGKILL durability verified, run-close
  p95 ~6 ms (target ≤50 ms), all docs updated, slice archived.
- Code review (2026-04-27) applied: 5 Important + 7 Minor findings.
  - I-1: Span tokens asymmetry documented (v2 deferred schema split).
  - I-2: Example entity field drift fixed (added origin_run_id + rubric).
  - I-3: Threading.Lock around all StorageWriter methods.
  - I-4: FR-EDGE-2 sweep tightened (surface invariant violations).
  - I-5: verify_pragmas wired post apply_pragmas.
  - M-1..M-7, A-2: Minor cleanups + BlobStore Protocol update.
- All 340 tests pass; source ruff-clean; 2 deferred-features entries added.
- Commit: 5e4b72d `fix(storage): Code review findings from v1-storage-adapter review`

## Next

- Implement v1-autocapture: monkey-patch hooks for `anthropic`, `openai`,
  `httpx` SDKs to auto-capture spans.
- Implement v1-cli: typer commands for `stats`, `serve`, `judge run`.
- Implement v1-http: FastAPI read-only service (port 8765).
- Implement v1-judge-adapters: Anthropic + OpenAI/OpenRouter compat.
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- None. Storage layer is stable and load-bearing for autocapture/CLI/HTTP.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/system_design.md`
- Code review archive: `dev/archive/v1-storage-adapter/v1-storage-adapter-code-review.md`
- Deferred features: `docs/2_architecture/deferred-features.md`

---
project: plumb
status: building
phase: v1 (Phase 8 complete, Week 5)
last_updated: 2026-04-30
next_gate: v1-cli / v1-http / v1-judge-adapters
blocked_on: null
---

# plumb — status

## Current

v1 autocapture slice shipped and archived. `plumb/autocapture/` monkey-patches
`anthropic` (sync + async Messages API) and `openai` (Chat Completions + Responses
API, sync + async) to auto-emit `kind='llm'` spans into the active `RunHandle`.
Blob-store content addressing (sha256 hash per request + response payload) and
secret redaction are in place. All 500 tests pass; ruff-clean.

## Recent (last 7 days)

- v1-autocapture Phases 1–8 complete and archived.
- Code review (2026-04-30) applied: 2 Critical + 4 Important/Minor findings.
  - **C-1**: Request canonicalization safety boundary — moved before-try canonicalize
    call into `safe_canonicalize_request()` so a plumb bug can never block the user's
    SDK call (FR-CAP-3 / NFR-Rel-1). Added `CANONICALIZATION_FAILED` sentinel.
  - **C-2** (response serialization): on `canonicalize_*_response` failure, record
    `output_hash=None` + `error_type='response_serialization_failed'` with a structured
    WARNING instead of silently hashing `b"{}"`.
  - **I-1**: `_register`/`_unregister`/`_is_registered` now self-lock via `RLock`;
    provider installers use `_register` rather than direct `_INSTALLED[...] = ...`.
  - **I-2**: Real `FilesystemBlobStore` perf gate added (`test_autocapture_overhead.py`);
    NFR-Perf-1 bifurcated — strict 1 ms for wrapper-only path, moderate 5 ms (8 ms CI)
    for full path including 2× `os.fsync`. Plan + TRS budget table updated accordingly.
  - **M-1**: Streaming edge-case row in plan corrected to `output_hash=None`.
  - **M-2**: Unused `resp_canon` parameter removed from `_wrap_sync`/`_wrap_async`.
  - 15 new safety-boundary regression tests added.
- All 500 tests pass; source ruff-clean.

## Next

- Implement v1-cli: typer commands for `run stats`, `score write`, `example promote`,
  `judge run`, `serve`, `attach`.
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
- Autocapture archive: `dev/archive/v1-autocapture/`
- Prior archive: `dev/archive/v1-storage-adapter/`
- Deferred features: `docs/2_architecture/deferred-features.md`

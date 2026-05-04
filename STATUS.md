---
project: plumb
status: building
phase: v1 (Phase 10 complete, Week 5)
last_updated: 2026-05-04
next_gate: v1-http / v1-judge-adapters merge-ready
blocked_on: null
---

# plumb — status

## Current

v1-judge-adapters Phase 6 (code-review remediation) complete. All P1 and P2 findings from the
code review addressed: CLI now judges model responses (P1 #1), error scores are retryable (P1 #2),
factory honors supplied `Settings.data_dir` (P2 #1), and retry uses `tenacity.wait_exponential_jitter`
per plan (P2 #2). Two previously-failing CLI tests fixed via hardcoded baseline date → `datetime.now(UTC)`
in `make_run()`. All 711 tests pass; ruff-clean. Test files split to approach 400-LOC target.

## Recent (last 7 days)

- v1-judge-adapters code review (2026-05-04) findings fully remediated:
  - **P1 #1**: `_load_run_content()` now prefers successful LLM spans with `output_hash` (model response),
    falls back to any LLM span with `output_hash`, returns `""` if none — never judges the request blob.
  - **P1 #2**: SQL `NOT EXISTS` now checks `s.scorer_version NOT LIKE '%:error'` so error rows don't
    block re-judging; CLI outer-except writes `{provider}:{model}:unknown:error` (consistent suffix).
  - **P2 #1**: `get_judge_adapter()` reordered: provider validation → credential validation → prompt loading.
    Passes `prompts_dir=ensure_data_dir(settings) / "judge_prompts"` to honor supplied `Settings`.
  - **P2 #2**: Replaced hand-rolled `with_judge_retry` with `tenacity.retry(stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=1, max=8), retry=retry_if_exception_type(JudgeTransientError),
    reraise=True)` per INT-JUDGE-5.
  - **Test gaps**: Added output-blob selection test (real blobstore), error-score retry test, non-mocked
    factory tests (real `data_dir`), and factory validation-order tests.
  - **Build fix**: `make_run()` now uses `datetime.now(UTC) - timedelta(days=...)` so since-filter tests
    stay correct over time. Fixed two failing CLI tests.
  - **Test file splits**: Split oversize test files into `_construction` (validation/metadata) and
    `_scoring` (happy path/retry/fail-open/security).

## Next

- Finalize v1-judge-adapters: code cleanup, merge to main.
- Implement v1-http: FastAPI read-only service (port 8765).
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/SYSTEM_DESIGN.md`
- CLI archive: `dev/archive/v1-cli/`
- Autocapture archive: `dev/archive/v1-autocapture/`
- Judge adapters (active): `dev/active/v1-judge-adapters/`
- Deferred features: `docs/2_architecture/deferred-features.md`

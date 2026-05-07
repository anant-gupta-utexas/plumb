---
project: plumb
status: v1-shipped
phase: v1 (Phase 11 complete, Week 5)
last_updated: 2026-05-07
next_gate: tag v1.0.0; move dev/active/v1-http → dev/archive/v1-http
blocked_on: null
---

# plumb — status

## Current

v1.0.0 complete (2026-05-07). v1-http slice finalized: FastAPI read-only service (127.0.0.1:8765)
with five endpoints (`/health`, `/runs`, `/runs/{id}`, `/examples`, `/stats/task/{id}`), connection
pool (size 4), error handling (404/422/503/500 envelopes), OpenAPI docs. Schema bootstrap idempotent,
stalled-run sweep optimized, percentile aggregations tested. E2E + perf tests passing (6 CI runs
after macOS jitter budget fix). getting_started.md expanded with curl examples, loopback security
note (TRD §5.3), blob-resolution path. All Phase 1–4 tasks complete. 630+ unit/integration/E2E tests.

## Recent (last 7 days)

- v1-http Phase 1–2 implementation (2026-05-07): schemas, pool, health, /runs endpoints.
- v1-http Phase 3–4 implementation (2026-05-07): stats aggregation, error handlers, OpenAPI, E2E, perf.
- Documentation finalization (2026-05-07): curl examples + security note + blob-resolution path.
- CI perf budget raised 3→6 ms (2026-05-07) to account for macOS scheduler jitter on loaded runners.

## Next

- Merge PR #21 (README + v1-judge-adapters archive + version bump + v1-http).
- Tag `v1.0.0` once PR #21 passes full CI.
- Move `dev/active/v1-http/` to `dev/archive/v1-http/` on main after merge.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/SYSTEM_DESIGN.md`
- Atlas recommendations assessment: `docs/2_architecture/deferred-features.md` (v2+ entries, 2026-05-06)
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

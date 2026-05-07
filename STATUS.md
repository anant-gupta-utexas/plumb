---
project: plumb
status: v1-ready
phase: v1 (Phase 10 complete, Week 5)
last_updated: 2026-05-06
next_gate: v1-http finalization + tag v1.0.0
blocked_on: null
---

# plumb — status

## Current

v1.0.0 release candidate (2026-05-06). README refreshed with value proposition, badges, schema detail, and
documentation table. v1-judge-adapters feature plan archived (complete per PR #19, #20). Version bumped to
1.0.0 in pyproject.toml. Atlas-integration Phase A shipped: (1) orchestrator handoff guide + 
(2) RunHandle.add_score(rationale=...) wired through CLI judge + (3) pyproject.toml split into 
[core]/[cli]/[http]/[judge]/[all] extras with lazy imports. Four deferred items documented in 
deferred-features.md for v2. 568 unit/CLI tests pass.

## Recent (last 7 days)

- v1-judge-adapters code review (2026-05-04) findings fully remediated, feature archived.
- Atlas recommendations (2026-05-06) Phase A complete, Phase B/C queued for v2.
- README refreshed (2026-05-06) with value proposition, badges, schema annotations.
- Version bumped to 1.0.0 (2026-05-06).

## Next

- Finalize v1-http: FastAPI read-only service (port 8765), run integration tests.
- Merge PR #21 (README + v1-judge-adapters archive + version bump).
- Tag `v1.0.0` once PR #21 + v1-http integration tests pass.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/SYSTEM_DESIGN.md`
- Atlas recommendations assessment: `docs/2_architecture/deferred-features.md` (v2+ entries, 2026-05-06)
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

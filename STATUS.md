---
project: plumb
status: building
phase: v1 (Phase 10 complete, Week 5)
last_updated: 2026-05-06
next_gate: v1-http / v1-judge-adapters merge-ready
blocked_on: null
---

# plumb — status

## Current

v1 atlas-integration recommendations (2026-05-06). Assessed all six recommendations against Tier-1 gating
constraints (FR-API-1: two callables, FR-API-4: four RunHandle methods, DATA-MIG-1: zero schema migrations
after Week 4). Phase A shipped: (1) orchestrator handoff guide + (2) RunHandle.add_score(rationale=...) 
parameter wired through CLI judge + (3) pyproject.toml split into [core]/[cli]/[http]/[judge]/[all] extras
with lazy imports and friendly ImportError messages. Four deferred items documented in deferred-features.md
for v2 (rationale DDL column, idempotent score ingestion, resume_run API, add_example method — all require
Tier-1 gate renegotiation or schema bump). 568 unit/CLI tests pass.

## Recent (last 7 days)

- v1-judge-adapters code review (2026-05-04) findings fully remediated.
- Atlas recommendations (2026-05-06) Phase A complete, Phase B/C queued for v2.

## Next

- Finalize v1-http: FastAPI read-only service (port 8765).
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/SYSTEM_DESIGN.md`
- Atlas recommendations assessment: `docs/2_architecture/deferred-features.md` (v2+ entries, 2026-05-06)
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

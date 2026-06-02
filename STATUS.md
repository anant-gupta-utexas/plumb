---
project: plumb
status: v1.0.1 shipped; v1.1/v1.2/v2.0 roadmap defined (2026-06-01)
phase: roadmap-planning (PRD §10 release plan + deferred backlog prioritized)
last_updated: 2026-06-01
next_gate: v1.1 TRD & phase breakdown (atlas unblock + schema v2 migration)
blocked_on: null
---

# plumb — status

## Current

v1.0.1 shipped and stable (2026-05-07 → 2026-06-01). Four-table SQLite schema,
decorator + context-manager entry points, CLI (`run stats`, `score write`, `example promote`,
`judge run`), read-only HTTP service (127.0.0.1:8765), ATTACH-based backfill adapter,
two judge adapters (Anthropic native + OpenAI-compatible), ten v1 metrics.
630+ unit/integration/E2E tests, full test/lint passing. Ready for PyPI.

**PRD roadmap complete (2026-06-01):** Three future releases prioritized from the
deferred-options backlog ([docs/2_architecture/deferred-features.md](docs/2_architecture/deferred-features.md)):
- **v1.1** — Atlas unblock: schema v2 migration (`user_version` 1→2) bundles
  `scores.rationale` column, idempotent scoring, `tokens_in`/`tokens_out` split,
  plus three new surface items (`resume_run`, `add_example`; renegotiates
  FR-API-1/FR-API-4 gates).
- **v1.2** — Metric depth: plan-vs-execution attribution, MAST 14-mode tagging,
  judge calibration, concurrent judge calls, per-metric model overrides.
- **v2.0** — Analysis & scale: frontier reports, SLM judges, ensembling,
  streaming, tool-use judges, long-running agents.

## Recent (last 7 days)

- v1-http finalization (2026-05-31): E2E + perf tests fixed, archived slice.
- PRD §10 Release Plan written (2026-06-01): v1.1/v1.2/v2.0 mapped with
  traceability to deferred-features backlog.
- Deferred-features backlog annotated (2026-06-01): 10 scheduled entries
  marked `→ scheduled PRD §10 vX.Y` per backlog's supersede-don't-delete convention.

## Next

- **v1.1 planning.** Tech Lead / TRD task: detail Phase 1 (schema v2 migration
  + three new surface items). Unblocks atlas dogfooding.
- PyPI publication (v1.0.1, when release readiness confirmed).

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- **Roadmap authority:** `docs/1_product_and_research/PRD.md` §10 Release Plan
- **Backlog authority:** `docs/2_architecture/deferred-features.md` (per-option
  rationale; 10 items now scheduled, rest deferred or won't-do)
- TRD (v1.0 authority): `docs/2_architecture/TRD.md`
- SDD (v1.0 authority): `docs/2_architecture/SYSTEM_DESIGN.md`
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

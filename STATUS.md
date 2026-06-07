---
project: plumb
status: v1.0.1 shipped; v1.1/v1.2/v2.0 TRD detailed (2026-06-02)
phase: roadmap-specification (TRD §§14–19 normative for v1.1/v1.2; scope-level for v2.0)
last_updated: 2026-06-02
next_gate: v1.1 phase breakdown TRS (task list for schema v2 migration + three API additions)
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
- **TRD extended to v1.1/v1.2/v2.0 (2026-06-02):** §§14–19 added; v1.0 baseline (§§1–13)
  preserved with inline renegotiation notes. v1.1 & v1.2 have full normative FR/NFR/Data/AC;
  v2.0 is scope-level per design (feature AC deferred to TDS). Migration contract detailed
  (DATA-MIG-2…6): additive-only, duplicate-abort safety, atomic, idempotency guard.

## Next

- **Decide the `spans.attributes` proposal (do this before the v1.1 migration is cut).**
  New net-new item surfaced 2026-06-07: a nullable `attributes TEXT` JSON column
  on `spans` for structured per-span data (ingestion counters, orchestrator
  worker metadata, per-stage workflow context). Proposed to ride the v1.1
  `user_version` 1→2 migration that is already scheduled — bundling is near-free,
  deferring costs a second `SCHEMA_VERSION` bump. Tension: a free-form bag pushes
  on the minimal-surface thesis, so pressure-test before accepting. See
  [`docs/1_product_and_research/phase-2-prioritization.md`](docs/1_product_and_research/phase-2-prioritization.md)
  and the dated backlog entry in
  [`docs/2_architecture/deferred-features.md`](docs/2_architecture/deferred-features.md).
- **v1.1 phase breakdown.** Run `/dev-docs-be` TRS command to produce flat task list
  under `dev/active/v1.1-schema-migration/` (or similar). Maps §15 FR/NFR/AC to
  tasks (fold in `spans.attributes` if accepted above). Unblocks atlas dogfooding.
- **PyPI publication (v1.0.1).** Smoke test, then `uv publish`. Independent of the
  v1.1 work — can ship anytime.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- **Roadmap authority:** `docs/1_product_and_research/PRD.md` §10 Release Plan
- **Backlog authority:** `docs/2_architecture/deferred-features.md` (per-option
  rationale; 10 items scheduled, rest deferred or won't-do)
- **TRD (comprehensive):** `docs/2_architecture/TRD.md` (v1.0 baseline §§1–13 +
  v1.1/v1.2/v2.0 roadmap §§14–19; 2026-06-02)
- SDD (v1.0 authority): `docs/2_architecture/SYSTEM_DESIGN.md`
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

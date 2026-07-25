---
project: plumb
status: v1.1.0 shipped (2026-07-24); v1.2/v2.0 TRD detailed
phase: v1.2-specification (TRD §§16–19 normative for v1.2; scope-level for v2.0)
last_updated: 2026-07-25
next_gate: v1.2 phase breakdown TRS (task list for metric-depth features; see docs/1_product_and_research/PRD.md §10 and docs/2_architecture/TRD.md)
blocked_on: null
---

# plumb — status

## Current

**v1.1.0 "Atlas unblock + schema v2" shipped (2026-07-24).** Schema migration
`user_version` 1→2 is live — additive only, applied automatically on first open
of a v1.0 database. Seven new surface features landed:
- `plumb.resume_run(run_id)` — third entry point (context-manager-only, for
  cross-process hand-off), alongside the decorator + context-manager forms.
- `RunHandle.add_example(...)` — fifth handle method, writes an `examples` row
  from inside an active run.
- `RunHandle.set_usage(*, tokens_in, tokens_out, dollar_cost)` — run-level
  usage/cost writer; last call wins per-field, `dollar_cost` never auto-fills.
- `scores.rationale` — durable column, now actually persisted (previously
  accepted but silently dropped at the storage boundary).
- `spans.tokens_in` / `spans.tokens_out` — split from the collapsed legacy
  `spans.tokens` column.
- `spans.attributes` — optional JSON-serializable dict, ~8KB soft cap,
  fail-closed validation on write.
- Idempotent score writes (`INSERT ... ON CONFLICT ... DO NOTHING` against a
  new unique index) + `dollar_cost_run_count` on the task-aggregate query, so
  callers can distinguish partial cost coverage from zero cost.

906 unit/integration/E2E tests passing, ruff-clean, mypy strict on core. See
[CHANGELOG.md](CHANGELOG.md) for the full v1.1.0 entry and
[dev/archive/v1.1-schema-migration-phase-2/](dev/archive/v1.1-schema-migration-phase-2/)
for the completed-work record (TDS, task checklist, code review).

**PRD roadmap** ([docs/1_product_and_research/PRD.md §10](docs/1_product_and_research/PRD.md)):
- **v1.0** — shipped (baseline): four tables, two entry points, ten metrics.
- **v1.1** — shipped (above).
- **v1.2** — Metric depth: plan-vs-execution attribution, MAST 14-mode tagging,
  judge calibration, concurrent judge calls, per-metric model overrides. No
  further schema migration.
- **v2.0** — Analysis & scale: frontier reports, SLM judges, ensembling,
  streaming, tool-use judges, long-running agents.

## Recent (last 7 days)

- **v1.1.0 released (2026-07-24):** all 14 tasks in
  [dev/archive/v1.1-schema-migration-phase-2/v1.1-schema-migration-phase-2-tasks.md](dev/archive/v1.1-schema-migration-phase-2/v1.1-schema-migration-phase-2-tasks.md)
  shipped and merged. `user_version` 1→2 migration, seven new surface
  features (see Current), CHANGELOG.md v1.1.0 entry written, `pyproject.toml`
  version bumped to `1.1.0`.
- CI gate failures + `Literal[False]` exit-type fixes landed same-day
  (`d40890f`) ahead of the version bump.
- `spans.attributes` proposal decided (accepted, 2026-06-07 → shipped 2026-07-24):
  rode the same `user_version` 1→2 migration as the other six features rather
  than deferring to a second `SCHEMA_VERSION` bump.

## Next

- **v1.2 phase breakdown.** Run `/dev-docs-be` TRS command to produce a flat
  task list under `dev/active/v1.2-metric-depth/` (or similar), mapping
  TRD §16 FR/NFR/AC to tasks: plan-vs-execution attribution, MAST 14-mode
  tagging, judge calibration vs. human α, concurrent judge calls
  (`--concurrency N`), per-metric model env overrides. No further schema
  migration needed — every new score fits the existing `scores` table via
  `metric_name`.
- **PyPI publication.** Now publishes **v1.1.0** (not v1.0.1 — the package
  version moved on since that note was written). Smoke test, then
  `uv publish`. Independent of the v1.2 work — can ship anytime.
- **`plumb run stats` cost column** — explicitly deferred as a v1.2
  CLI-parity question (TRD-v2.md correction, 2026-07-24): `dollar_cost` is
  populated end-to-end as of v1.1 but the CLI's `run stats` command still
  doesn't render it; only the HTTP `/stats` endpoint surfaces cost today.

## Blocked / waiting

- None. Core + CLI + autocapture + adapters stable.

## Pointers

- **Roadmap authority:** `docs/1_product_and_research/PRD.md` §10 Release Plan
- **Backlog authority:** `docs/2_architecture/deferred-features.md` (per-option
  rationale; 10 items scheduled, rest deferred or won't-do)
- **TRD (comprehensive):** `docs/2_architecture/TRD.md` (v1.0 baseline §§1–13 +
  v1.1/v1.2/v2.0 roadmap §§14–19)
- **v1.1 completed-work record:** `dev/archive/v1.1-schema-migration-phase-2/`
  (plan, context, tasks, code review)
- SDD (v1.0 authority): `docs/2_architecture/SYSTEM_DESIGN.md`
- Orchestrator handoff guide: `docs/3_guides/orchestrator_handoff.md`
- Optional extras: `pyproject.toml`

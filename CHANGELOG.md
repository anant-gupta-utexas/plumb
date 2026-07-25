# Changelog

All notable changes to plumb are documented in this file.

## v1.1 — "Atlas unblock + schema v2" (unreleased)

### Schema migration

- `user_version` 1 → 2. **Additive and non-breaking** — this is a minor
  version bump, not a major one, despite the TRD's general "schema changes
  bump the major version" guidance: every change in this migration is a new
  nullable column or a new index, applied in a single transaction with a
  duplicate-row pre-check that aborts (leaving the DB at `user_version=1`,
  zero rows touched) if any `(run_id, metric_name, scorer_version, span_id)`
  tuple would collide under the new unique index. A v1.0 database opens
  transparently under v1.1 and migrates automatically on first open; a
  second open of an already-migrated database is a no-op.
- New columns: `scores.rationale`, `spans.tokens_in`, `spans.tokens_out`,
  `spans.attributes`.
- New index: `idx_scores_idem` — unique on
  `(run_id, metric_name, scorer_version, IFNULL(span_id, ''))`, backing
  idempotent score writes.
- Pre-migration rows remain readable unchanged: `scores.rationale` reads as
  `None`, `spans.tokens_in` falls back to the legacy summed `spans.tokens`
  column with `tokens_out=None`, `spans.attributes` reads as `None`.

### Added

- `plumb.NotFoundError` — new member of the core exception hierarchy,
  raised by `resume_run` for an unknown `run_id`.
- `plumb.resume_run(run_id)` — third entry point (after `run`'s decorator
  and context-manager forms), context-manager-only, for re-opening a
  `pending` run from a different process. Raises `NotFoundError` if the run
  doesn't exist, `ValidationError` if it's already terminal
  (`success`/`failure`/`aborted`/`stalled`).
- `RunHandle.add_example(...)` — fifth handle method, writes an `examples`
  row from inside an active run (same write path as `plumb example
  promote`, no CLI round-trip required).
- `RunHandle.set_usage(*, tokens_in=None, tokens_out=None, dollar_cost=None)`
  — run-level usage/cost writer. Last call wins per-field. If never called,
  `tokens_in`/`tokens_out` auto-fill at close time from the buffered spans'
  split token totals; `dollar_cost` is **never** auto-filled — it is `NULL`
  unless set explicitly, in every release, permanently.
- `RunHandle.add_score(..., rationale=...)` now persists `rationale`
  (previously accepted but silently dropped at the storage boundary).
- `RunHandle.add_span(..., attributes=...)` — optional JSON-serializable
  `dict`, ~8KB soft cap, validated fail-closed at the API boundary before
  the span is buffered. Malformed/legacy values on read surface as `None`
  rather than raising.
- Idempotent score ingestion: `write_score` now uses
  `INSERT ... ON CONFLICT ... DO NOTHING` against `idx_scores_idem` and
  returns whether the row was actually inserted. `RunHandle.add_score` and
  `plumb score write` gain an advisory `idempotency_key` (not persisted as
  a column — the index is the authoritative dedup guarantee).
- `dollar_cost_run_count` on the task-aggregate query
  (`aggregate_runs_for_task` / `GET /stats/task/{task_id}`) — the count of
  runs in the window with a non-NULL `dollar_cost`, so callers can tell
  partial cost coverage apart from a task with zero cost.

### Unchanged / explicitly out of scope

- `plumb run stats` (CLI) does not render cost — that stays a v1.2
  CLI-parity question.
- `StatsOut`'s `extra="forbid"` behavior is unchanged.

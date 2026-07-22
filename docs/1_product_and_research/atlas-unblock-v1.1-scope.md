---
title: plumb v1.1 "Atlas unblock" — v3-driven scope deltas + TRS brief
status: planning — feeds a v1.1 TRD amendment, then a per-phase TRS
created: 2026-07-21
last_reviewed: 2026-07-21
tags: [v1.1, schema-v2, atlas, loop-mode, cost, tokens, attributes, migration]
---

# plumb v1.1 "Atlas unblock" — scope deltas for the atlas loop (v3)

## Why this doc exists

An external consumer (the **atlas loop**, atlas v3 — an autonomous,
minimal-input development loop) is being built. Its measurement needs were
diffed against plumb's already-specified **TRD §15 "v1.1 — Atlas unblock +
schema v2"**. §15 covers most of what the loop needs, but the diff surfaced
**two features that are NOT yet in the TRD** and one **factual correction** to
an assumption the loop's own planning made about plumb.

**This doc is the bridge:** it records exactly what to add to plumb's TRD §15
before cutting the v1.1 TRS, so the next session can (1) amend the TRD, then
(2) run `/dev-docs-be` on §15 to produce the flat task list. It does **not**
restate §15's five already-specified features except to reference them.

> Consumer-agnostic framing: plumb is a standalone measurement library. "The
> loop" below is simply *a consumer that records runs*. Nothing here couples
> plumb to that consumer — every item is a general capability (run-level cost,
> structured span attributes) that any recorder would want. The migration
> discipline (four tables, minimal surface, additive-only) is plumb's, and is
> preserved.

## What v1.1 already specifies (TRD §15 — no change needed)

Referenced so the TRS author does not re-derive them. All are in
`docs/2_architecture/TRD.md` §15 and `deferred-features.md`:

| TRD ref | Feature | Loop use (v3 phase) |
|---|---|---|
| §15.1 | `plumb.resume_run(run_id)` — 3rd entry point | Not required by the loop (it is sequential + uses child runs). Nice-to-have; leave as specified. |
| §15.2 | `RunHandle.add_example(...)` — 5th handle method | **Self-healing** writes rejection/failure examples cleanly, retiring atlas's current private-API reach into `plumb.api._storage_writer.write_example` (atlas L3). |
| §15.4 | `scores.rationale` durable column | **Durable PR-review + judge rationale** — the `add_score(rationale=...)` value currently drops at the storage boundary (atlas L3 judge gate). |
| §15.5 | `spans.tokens_in` / `tokens_out` split | Per-span in/out token fidelity for loop runs (atlas L0+). |
| §15.6 | Idempotent score ingestion (UNIQUE index + `idempotency_key`) | The loop's **PR-outcome sync re-writing a `user_signal` score on re-tick cannot double-count** (atlas L2). |

## Factual correction the loop's planning depends on (verified against source)

The atlas loop's plan assumed *"`runs` already has `tokens_in`/`tokens_out`/
`dollar_cost`, so cost is captured."* **Half true, and the false half is the
one that matters.** Verified in plumb v1.0.1 source:

- The **columns exist** (`_schema.py` runs DDL: `tokens_in INTEGER`,
  `tokens_out INTEGER`, `dollar_cost REAL`).
- **The online `with run()` path never writes them.** `finalize_run`
  (`storage_sqlite.py:431`) and its `_FINALIZE_RUN` UPDATE (`:291`) set only
  `status, end_ts, error_type, orchestrator_model, sub_agent_model,
  prompt_version, tool_schema_version, git_sha`. **Not** cost, **not** run-level
  tokens.
- `RunHandle` exposes **no setter** for cost/usage (`set_models` exists;
  there is no `set_usage`). `add_span(tokens=(in,out))` records *span* tokens
  (collapsed to a single summed `spans.tokens` column in v1.0; the split is
  §15.5's job).
- Therefore `plumb run stats` → `SUM(dollar_cost)` (`storage_sqlite.py:743`)
  **sums a column the online path leaves NULL**. Any "cost-per-landed-PR"
  headline reads **$0 today.**

This is the gap §15 does **not** close (§15.5 splits *span* tokens; it says
nothing about *run-level* cost/tokens). → **New feature P1-a below.**

---

## Delta 1 (P1-a) — Run-level cost / usage writer  [NOT in TRD yet — ADD]

**Problem.** No supported path writes `runs.dollar_cost` / `runs.tokens_in` /
`runs.tokens_out` on the online `with run()` / `resume_run()` path. Aggregations
that sum these columns are structurally correct but always read zero.

**Proposed shape (no schema change — the columns already exist):**

```python
# New RunHandle method, buffered onto _RunBuilder like set_models():
def set_usage(
    self,
    *,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    dollar_cost: float | None = None,
) -> None:
    """Late-bind run-level usage totals; last non-None value per field wins.
    No-op after abort()."""
```

**Storage change.** Thread the three fields through `finalize_run(...)` and add
them to the `_FINALIZE_RUN` UPDATE `SET` list. `write_run` (the offline path,
`storage_sqlite.py:471`) already reads them off the `Run` entity via
`_run_to_row` — only the **online finalize path** is missing them.

**Relationship to §15.5.** Orthogonal. §15.5 is *span* granularity
(`spans.tokens_in/out`); P1-a is *run* granularity (`runs.*`). A consumer sets
per-span tokens via `add_span` **and** rolls up run totals via `set_usage`.
Whether plumb should *auto-derive* `runs.tokens_*` by summing spans at finalize
(instead of an explicit setter) is a **design decision for the TRD amendment**
— see "Open decisions" below.

**Design decisions to resolve in the TRD (not the TRS):**
- **D-a1: explicit `set_usage` vs. auto-sum-from-spans at finalize.** Explicit
  setter = caller owns the number (matches how backends report a single
  authoritative `total_cost_usd`); auto-sum = zero caller burden but can only
  derive tokens (not dollars — plumb has no per-span cost), and double-counts if
  a caller also sets it. **Recommendation: explicit `set_usage`** (dollars have
  no other source; keeps plumb a recorder, not a calculator). Optionally *also*
  auto-fill `runs.tokens_*` from spans **only when** `set_usage` did not supply
  them.
- **D-a2: interaction with `resume_run` (§15.1).** `set_usage` on a resumed run
  should **accumulate or overwrite?** Recommend **overwrite with last-wins**
  (same semantics as `set_models`), documented; accumulation invites
  double-count across processes.

**Acceptance sketch (for the TRD, refined in TRS):**
- *Given* an open run, *When* `r.set_usage(tokens_in=100, tokens_out=250,
  dollar_cost=0.0123)` then the block exits, *Then* the `runs` row has exactly
  those three values and `plumb run stats` `dollar_cost_total` includes 0.0123.
- *Given* a run where `set_usage` is never called, *Then* the three columns are
  `NULL` (or the auto-sum value per D-a1) — never a fabricated number.

---

## Delta 2 (P1-b) — `spans.attributes` JSON column  [proposal in backlog; NOT in TRD §15 migration — ADD to the migration]

**Status.** Recorded in `deferred-features.md` (2026-06-07, line 438) as a
**proposal needing sign-off**, explicitly flagged to **ride the v1.1
`user_version` 1→2 migration or wait a whole release**. It is currently **not**
one of §15's five features and **not** in §15.3's migration contract. The
decision to include it is **time-sensitive**: once §15 ships and `user_version`
re-freezes at 2, adding it becomes a *second* migration in v1.2+.

**Decision (per the v3 planning session, 2026-07-21): INCLUDE it in the v1.1
migration.** Rationale below; the standing tension is recorded honestly.

**Proposed shape (one additive nullable column):**

```sql
ALTER TABLE spans ADD COLUMN attributes TEXT;   -- JSON object, nullable
```
```python
# Span entity gains: attributes: dict | None = None
# add_span(..., attributes: dict | None = None)  — json.dumps on write,
#   validate JSON-serializable at the API boundary (fail-closed on write,
#   never on read); json.loads → dict on read.
```

**Loop use (why it earns the column now).** Loop runs want a durable, queryable
home for per-run/per-span metadata that today has nowhere to live except
smuggled into `task_id` prefixes:

```python
add_span(kind="llm", name="code_gen",
         attributes={"lane": "planned", "engine": "codex",
                     "issue": 142, "attempt_n": 2, "failure_mode": "flaky"})
# → queryable via SQLite json_extract(attributes,'$.failure_mode'),
#   json_extract(attributes,'$.engine'), etc. No task_id-prefix parsing.
```

This is exactly the routing + self-healing analytics surface (atlas L2/L3):
"which engine/lane/failure-mode correlates with merged PRs."

**The standing tension (do not bury it).** A free-form JSON bag pushes on
plumb's **minimal-surface thesis** — the discipline that makes plumb a
publishable framework rests on four tables + two entry points + no dumping
grounds. Mitigations already in the backlog entry:
- It is a **column, not a fifth table** — the four-*table* thesis is intact.
- plumb **does not interpret the keys** — it stores/returns opaque JSON;
  no metric logic reads it, so it cannot corrupt the scoring layer.
- Three independent consumers (ingestion counters, orchestrator worker
  metadata, per-stage workflow context) want the *same* thing → the right
  abstraction is one generic field, not N named columns (which would be *worse*
  surface creep).
- It rides an **already-scheduled** migration → near-zero incremental cost;
  deferring costs a whole release cycle for one nullable column.

**If you want the falsifier checked before locking it into a one-way-door
migration:** run the `pressure-test` skill on this proposal (the backlog entry
itself says it needs sign-off). The v3 session chose "include" on the
migration-timing logic; this is the one item where a deliberate second look is
cheap insurance before the schema re-freezes.

**Design decisions to resolve in the TRD:**
- **D-b1: validation strictness.** Fail-closed on non-JSON-serializable value at
  `add_span` (recommended) vs. best-effort `str()`. Recommend **fail-closed on
  write** (a silently-stringified dict is a debugging trap), **never raise on
  read** (NFR-Rel-1 — a malformed legacy value must not break a query).
- **D-b2: size guard.** Cap serialized `attributes` length (e.g. ≤ 8 KB) to keep
  it metadata, not a blob smuggle? Recommend a documented soft cap enforced at
  the API boundary.
- **D-b3: is it on `spans` only, or also `runs`?** The loop's needs are
  span-level. Recommend **`spans` only** for v1.1 (a `runs.attributes` is a
  separate future call; do not widen scope now).

---

## What this means for plumb's TRD (§15) — the concrete amendment

Before cutting the TRS, amend `docs/2_architecture/TRD.md` §15 as follows. All
edits keep §15's "one additive migration" contract intact — P1-a adds **no**
schema change, P1-b adds **one** `ALTER` to the migration already defined.

1. **§14 roadmap table + §15 intro "Five features" → "Seven features".** Add two
   rows:
   - `P1-a — Run-level cost/usage writer (set_usage) — API + storage (no schema)`
   - `P1-b — spans.attributes JSON column — Schema (additive) — folded onto the v1.1 migration`
   Update the §15 header count and the §14 §15-row "Surface impact" to note
   `+1 handle method (set_usage)` alongside the existing `resume_run` /
   `add_example` surface deltas.

2. **New §15.9 — `set_usage` run-level usage writer.** FR-USAGE-1..n:
   the `set_usage` signature (above), last-wins buffering on `_RunBuilder`,
   threading through `finalize_run` + `_FINALIZE_RUN`, the D-a1/D-a2 decisions
   resolved, and the reliability delta (no-op after abort; storage failure
   fail-degraded per NFR-Rel-1). **No** entry in §15.3 (no schema change).

3. **New §15.10 — `spans.attributes` structured column.** FR-ATTR-1..n:
   the `ALTER TABLE spans ADD COLUMN attributes TEXT`, `Span.attributes`
   round-trip through `_span_to_row`/`_row_to_span`/`_INSERT_SPAN`, JSON
   validation policy (D-b1), soft size cap (D-b2), `spans`-only scope (D-b3),
   and the legacy-row semantics (pre-migration rows have `attributes = NULL`,
   never backfilled).

4. **§15.3 migration contract — add one line to DATA-MIG-2:**
   `ALTER TABLE spans ADD COLUMN attributes TEXT;`
   The migration stays additive-only, single-transaction (DATA-MIG-4),
   duplicate-safe (DATA-MIG-6 unchanged — attributes has no index). Re-run
   idempotence (DATA-MIG-3) and the `1→2` version arm (DATA-MIG-5) already
   cover it.

5. **§15.8 acceptance criteria — add:**
   - `AC-USAGE-1/2` (P1-a): explicit `set_usage` round-trips to `runs.*` and
     into `dollar_cost_total`; un-set → NULL (or auto-sum per D-a1).
   - `AC-ATTR-1` (P1-b): `add_span(attributes={...})` round-trips via
     `json_extract`; `AC-ATTR-2`: legacy span row (`attributes NULL`) reads back
     as `None`; `AC-ATTR-3`: non-serializable value raises at write, no row.

6. **§15.7 NFR deltas — extend NFR-MIG-1** note: the added `attributes` column
   does not change the ≤500 ms migration budget (a bare `ALTER ADD COLUMN` is
   O(1) metadata in SQLite; no table rewrite).

No other §15 subsection changes. §16/§17 are untouched.

---

## Brief for the TRS (`/dev-docs-be` on §15, next session)

Run `/dev-docs-be` against the **amended** §15 to produce the flat task list
(suggested `dev/active/v1.1-schema-migration/`). Points to convey to that TRS:

- **Scope = §15's seven features on ONE `user_version` 1→2 migration.** The five
  already-specified (§15.1/15.2/15.4/15.5/15.6) plus the two added by this doc
  (P1-a `set_usage`, P1-b `spans.attributes`). Do not split the migration.
- **Migration is the spine; sequence tasks so the `_bootstrap_schema` 1→2 arm
  and the duplicate pre-check (DATA-MIG-6) land first**, then the additive
  columns/index, then the API surface (`resume_run`, `add_example`, `set_usage`,
  `idempotency_key`, `attributes` kwarg), then the adapter round-trip updates
  (`_run_to_row`/`_span_to_row`/`_score_to_row` and their readers), then the
  aggregation-query updates (FR-TOKENS-4 style COALESCE fallbacks; include
  `dollar_cost` now that it is populated).
- **Files the TRS will touch** (from source): `plumb/api.py` (`RunHandle`:
  `add_example`, `set_usage`, `add_score(idempotency_key=...)`,
  `add_span(attributes=...)`; new `resume_run` factory), `plumb/core/entities.py`
  (`Span.attributes`, token/rationale fields already present),
  `plumb/adapters/_schema.py` (DDL + `SCHEMA_VERSION`→2 + migration arm),
  `plumb/adapters/storage_sqlite.py` (`_FINALIZE_RUN` SET-list, `_INSERT_SPAN`,
  `_INSERT_SCORE`, `_span_to_row`/`_row_to_span`, `_score_to_row`/`_row_to_score`,
  `_run_to_row` already has the run cols, `open_or_resume` path, the migration
  runner, aggregation SQL at ~line 739+), `plumb/cli.py` (`score write
  --idempotency-key`; any `run stats` cost column now non-zero).
- **Priority within the release (for task ordering / partial-ship):**
  P0 = migration mechanics + P1-a `set_usage` + P1-b `attributes` (these are the
  two v3-blocking + migration-timing-locked items). P1 = §15.4 rationale,
  §15.6 idempotency, §15.2 `add_example` (v3 L2/L3 wants them; same migration so
  include). P2 = §15.1 `resume_run` (not v3-blocking; keep if cheap, cut first
  if the migration work overruns).
- **Guardrails to restate in the TRS:** additive-only (DATA-MIG-3); never
  auto-dedup user data (DATA-MIG-6); fail-degraded-not-raise on plumb-internal
  error (NFR-Rel-1); parameterized SQL (NFR-Sec-3); the migration runs once in
  `_bootstrap_schema` before any user query (NFR-MIG-2). `attributes` validation
  is the one new fail-closed-on-write path.
- **Independent of this work:** PyPI publication of v1.0.1 (`uv publish`) — can
  ship anytime, not part of the migration.
- **One decision to lock before the TRS if not already:** whether to
  `pressure-test` P1-b (`spans.attributes`) before the migration re-freezes the
  schema. If yes, do it *before* `/dev-docs-be`, since a "no" answer changes the
  migration's `ALTER` list.

## v3 dependency edges (how this gates the atlas loop)

- atlas **L0/L1** need **nothing** from plumb (record per-span tokens via the
  existing `add_span(tokens=...)`; report tokens, not dollars).
- atlas **L2** (the daemon + cost-per-landed-PR headline) needs **P1-a**
  (real `dollar_cost`) and **§15.6** (idempotent sync). → plumb v1.1 should land
  **before atlas L2 ships**, in parallel with L0/L1.
- atlas **L3** (self-healing) wants **§15.2** (`add_example`) and **§15.4**
  (rationale) to retire the private-API workaround. **P1-b** (`attributes`)
  sharpens L2/L3 routing analytics but is not strictly blocking.

## Cross-references

- plumb TRD (§14 roadmap, §15 v1.1 contract): [`../2_architecture/TRD.md`](../2_architecture/TRD.md)
- Deferred-features backlog (per-decision rationale; P1-b entry at 2026-06-07): [`../2_architecture/deferred-features.md`](../2_architecture/deferred-features.md)
- Phase-2 prioritization (the `spans.attributes` proposal's home): [`phase-2-prioritization.md`](phase-2-prioritization.md)
- Schema/metrics v1: [`schema-and-metrics-v1.md`](schema-and-metrics-v1.md)
- Source anchors: `plumb/api.py` (RunHandle), `plumb/adapters/storage_sqlite.py` (`_FINALIZE_RUN`:291, `finalize_run`:431, aggregation:739+), `plumb/adapters/_schema.py` (runs/spans DDL, `SCHEMA_VERSION`)

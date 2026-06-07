---
title: "plumb Phase 2 — prioritization"
status: prioritization (decision sheet)
created: 2026-06-07
related:
  - deferred-features.md (backlog — authority for "why each option was picked")
  - PRD.md §10 Release Plan (authority for "what ships when")
---

# plumb Phase 2 — prioritization

> Captured 2026-06-07. plumb's Phase 2 is *already specified* (PRD §10:
> v1.1 → v1.2 → v2.0). This note records one **net-new** proposal surfaced by a
> consumer integration that was *not* previously in the backlog, and sequences
> the existing roadmap so the proposal can ride the v1.1 migration if accepted.

---

## 1. The net-new item — `spans.attributes` JSON column

A consumer integration noted that a span's durable payload is lean
(`kind`, `name`, `latency_ms`, `status` + the content hashes). Structured
per-span data computed at instrumentation time — e.g. an ingestion span that
knows `items_fetched`, `items_new`, `items_skipped`, or an orchestrator worker
span that knows `ticket_id`, `attempt_n`, `failure_mode`, `blocked_by` — has
**no durable home**. The only escape hatch is serializing it into
`input_hash`/`output_hash` blob content (abusing a content-address field for
structured metadata) or smuggling it into the `task_id` prefix. Both are
workarounds.

**This is not in the existing backlog.** The closest entries are near-misses:
the `tokens_in`/`tokens_out` split (v1.1, two *named* columns) and the v2
`subgoals` metadata column (scoped to loop detection, not arbitrary data).

**The proposal:** one nullable `attributes TEXT` JSON column on `spans`, folded
onto the v1.1 migration that is **already** bumping `user_version` 1→2.
Recorded as a proposed v1.1 entry in
[`../2_architecture/deferred-features.md`](../2_architecture/deferred-features.md),
dated 2026-06-07.

### Why bundle it onto v1.1 now (cost-of-being-wrong)

- **Asymmetric cost.** v1.1 is already performing exactly one additive
  migration. Adding one more nullable column to that same migration is
  near-free. Deferring it to its own v2 migration pays a *second*
  `SCHEMA_VERSION` bump for one column — a whole release cycle of cost.
- **Multiple consumers want the same field.** Ingestion-pipeline counters,
  orchestrator worker metadata (`ticket_id`, `attempt_n`, `failure_mode`,
  `blocked_by`), and per-stage workflow context (`workflow`, `stage`, `gate`).
  Several independent asks for the same shape is the signal the right
  abstraction is *one generic field*, not N named columns.
- **It subsumes two open provenance questions.** A YAML-driven gated-workflow
  consumer flagged both a metric-namespacing gap and a possible `runs.workflow`
  provenance column. A `spans.attributes` field gives per-workflow context a
  durable home without either. **Prefer the attributes column over a
  `runs.workflow` add.**

### The real tension (pressure-test before committing)

plumb's thesis is "four tables / minimal surface." A free-form attributes bag is
exactly the kind of surface that thesis exists to resist — it can become a
dumping ground, and its values are opaque to plumb's own ten metrics. The
four-*table* constraint is preserved (it's a column), but the
minimal-*surface* spirit is genuinely in tension. This is why the backlog entry
is a **proposal needing sign-off**, not a done deal. Worth an adversarial
pressure-test before it goes onto the v1.1 migration.

---

## 2. Does the near-term consumer work need a plumb upgrade?

**No — and this matters as a scope fence.** A current consumer integration
verified (2026-06-07) that what it needs is native in plumb v1.0:

| Consumer need | plumb status |
|---|---|
| `parent_run_id` child runs (self-healing retry lineage) | **v1.0 — shipped** |
| `dollar_cost`, `tokens_in/out`, cost dashboard | **v1.0 entity — shipped** (the in/out *split* is v1.1; the sum works today) |
| `Example.origin_run_id` + `production_promotion` (failure capture) | **v1.0 — shipped** |
| `RunHandle.add_example(...)` from inside a run | **v1.1** — consumer routes around via the adapter-direct `storage.write_example` path for now |
| `scores.rationale` durable column (gate auditability) | **v1.1** — in-memory works for a short-lived demo; durability is a polish item |

So a plumb refactor must **not** become a blocking dependency for the consumer.
The `spans.attributes` work is a *parallel* track — valuable for the ingestion
consumer and as a durability upgrade for orchestrator worker metadata — but the
consumer ships without it if it has to.

---

## 3. Decision sheet

| Track | Priority | Action |
|---|---|---|
| `spans.attributes` JSON column | **Decide before v1.1 migration is cut** | Pressure-test the thesis tension; if accepted, fold onto the v1.1 `user_version` 1→2 migration. Backlog entry filed. |
| v1.1 (rationale, idempotent scoring, tokens split, `resume_run`, `add_example`) | **Keep as-is** | Already specified (TRD §§14–19 normative). Next gate = v1.1 phase-breakdown TRS. |
| v1.2 (plan-vs-execution, MAST, calibration, concurrency, per-metric model) | **Defer** | For the flagship write-up, *not* the near-term consumer work. Do not pull forward. |
| v2.0 (frontier reports, SLM judges, ensembling, streaming, tool-use judges) | **Defer** | Largest release, experiment-driven. Unchanged. |

---

## 4. Net Phase-2 ordering for plumb

1. **Decide the `spans.attributes` proposal** (pressure-test → accept/reject).
   This is the only thing that *must* happen before v1.1's migration freezes.
2. **Cut the v1.1 phase-breakdown TRS** as already planned (schema v2 migration
   + the three API additions), folding `attributes` in if accepted at step 1.
3. **PyPI publication of v1.0.1** is independent and can ship anytime.
4. v1.2 / v2.0 stay where the PRD put them — after the near-term work and the
   flagship post, respectively.

---

## 5. Open decisions

- [ ] Accept `spans.attributes` onto the v1.1 migration, or defer to v2 / reject?
      (Pressure-test the minimal-surface thesis tension first.)
- [ ] If accepted: confirm the field is opaque to plumb (no metric reads it) and
      validated JSON-serializable at the API boundary (fail-closed on write).
- [ ] Confirm `runs.workflow` provenance is *dropped* in favor of
      `spans.attributes` carrying workflow context.

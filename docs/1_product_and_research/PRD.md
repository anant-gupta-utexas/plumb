# plumb — Product Requirements Document

**Status:** v1.0 shipped; v1.1 / v1.2 / v2.0 roadmap added (2026-06-01)
**Owner:** anant

---

**Plumb measures what current agent-telemetry tools don't: whether a human
actually accepted the agent's output, where the orchestrator routed, how
sub-agents handed off, and what it cost to get the answer.** A small Python
package + SQLite schema + two entry points. Designed for solo developers
and small DevEx / AI-ML / agentic-systems teams instrumenting their own
multi-agent workflow.

---

## 1. Problem

Every major observability vendor (Arize, Braintrust, LangSmith, Humanloop,
Galileo, Patronus) now offers agent telemetry — but three gaps stay open for
anyone instrumenting their *own* multi-agent dev workflow:

1. **Acceptance is invisible.** Current tools log that the agent ran, not
   whether a human accepted the code, merged the PR, or re-prompted in
   frustration. The *intervention rate* is the metric DevEx teams actually
   want; none of the agent tools emit it.
2. **Orchestrator-specific failures are uncategorized.** Cemri et al.'s MAST
   taxonomy (arXiv:2503.13657) shows ~79% of multi-agent failures are
   specification or inter-agent misalignment — invisible to single-agent
   metrics. Routing quality, handoff round-trip, and duplicate sub-agent
   calls need a schema that models spans and hand-offs, not just LLM calls.
3. **Offline and online live in different tools.** Eval frameworks grade
   golden sets; observability tools grade traces. The industry has already
   converged on unifying them in one schema (Braintrust, LangSmith) — but
   there is no minimal, public, four-table reference implementation that a
   small team or a single developer can adopt in an afternoon.

## 2. Goal

Ship a minimal, opinionated measurement spine that:

- fits a single-developer workflow *and* generalizes to a small DevEx /
  AI-ML / agentic-systems team;
- captures the ten v1 metrics defined in [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md)
  across **one** unified `runs` table (offline + online);
- instruments multi-component agent systems (orchestrator, content pipeline,
  recommender, any sub-agent) from day one;
- produces publishable data inside 8 weeks of instrumentation, supporting a
  long-form write-up: *"I built a measurement framework, instrumented a
  multi-agent system with it, ran it for 8 weeks — here's what the data
  says."*

## 3. Audiences & framings

One artifact, three framings:

| Audience            | What they see in plumb                                                   | Lead-in line                                                             |
| ------------------- | ------------------------------------------------------------------------ | ------------------------------------------------------------------------ |
| **DevEx**           | Intervention rate, acceptance, routing quality on real dev work          | "A framework for measuring dev productivity that teams aren't measuring" |
| **AI/ML eng**       | Four-table schema, statistical rigor, paired McNemar ship decisions      | "Eval methodology with real error bars on a real system"                 |
| **Agentic systems** | Orchestrator routing, handoff round-trip, pass^k, MAST-aligned span tree | "Multi-agent orchestrator instrumented end-to-end for 8 weeks"           |

## 4. What plumb measures (v1 metric cut)

Ten metrics, all computable from the four-table schema, each covers a distinct
failure mode. Derived in [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md); listed here for the PRD:

1. Task completion (binary)
2. End-to-end latency
3. Dollar cost
4. Tokens-per-resolved-task
5. Tool-call validity
6. Tool-argument hallucination
7. Routing top-1 accuracy
8. Handoff round-trip accuracy
9. Intervention rate
10. pass^3 on a reliability subset

The metric set is extended in later releases: **v1.2** adds plan-vs-execution
attribution, MAST-style 14-mode failure tagging, and judge calibration against a
human α baseline. Everything else is **v2.0** or out-of-scope (see §7). The full
sequencing lives in §10 Release Plan; the deferred-options backlog with
per-decision rationale is in [`../2_architecture/deferred-features.md`](../2_architecture/deferred-features.md).

## 5. Schema

Four tables, three foreign keys, one bidirectional lineage link. The shape is
the thesis: if it can't be expressed in these four tables, it isn't v1.

```
runs       (run_id PK, kind ∈ {offline, online}, task_id, parent_run_id?,
            orchestrator_model, sub_agent_model, prompt_version,
            tool_schema_version, git_sha, start_ts, end_ts,
            tokens_in, tokens_out, dollar_cost, status)

spans      (span_id PK, run_id FK, parent_span_id?,
            kind ∈ {llm, tool, subagent, handoff, plan, verify},
            name, input_hash, output_hash,
            tokens, latency_ms, status, error_type)

scores     (score_id PK, run_id FK, span_id? FK,
            metric_name, scorer ∈ {deterministic, judge, human, user_signal},
            scorer_version, value_numeric, value_label, scored_at)

examples   (example_id PK, task_id, inputs_hash, expected_output_hash,
            rubric, source ∈ {synthetic, production_promotion, human_authored},
            origin_run_id? FK → runs, active, created_at)
```

Key design moves (expanded in [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md)):

- **`runs.kind`** unifies offline evals and production traces in one table.
- **`spans.input_hash` / `output_hash`** keep PII out of the main row; full
  content lives in a content-addressed blob store.
- **`scores.scorer` + `scorer_version`** make judge, human, deterministic, and
  user-signal scores structurally identical — and detect judge drift later
  without corrupting history.
- **`examples.origin_run_id`** is the single foreign key that closes the
  offline ↔ online loop: a production failure promoted to a test case
  remembers the trace it came from.

## 6. API surface

Two entry points. Everything else is queries over the schema.

**Decorator** — wraps a function as a `runs` row with auto-captured spans for
any LLM/tool calls inside:

```python
from plumb import run

@run(task_id="content-pipeline.ingest", kind="online")
def ingest(url: str) -> Doc: ...
```

**Context manager** — block-scoped equivalent, for inline use or
orchestrator-level instrumentation:

```python
from plumb import run

with run(task_id="atlas.stage5.codegen", kind="online") as r:
    r.add_score("verify_pass", scorer="deterministic", value_label="pass")
    ...
```

**CLI** — `plumb` is a registered entry point:

```
plumb run stats [--since 7d] [--format json]
plumb score write --run-id <id> --metric <name> --scorer <kind> --value-label <v>
plumb example promote --from-run <id> --rubric <path>
plumb judge run --model claude-sonnet-4-6 --metric routing_top1
```

**Adapters** — `ATTACH`-based backfill from existing agent-telemetry SQLite
files (e.g. `~/.agentsview/db.sqlite`): ~200 LOC adapter, no ETL, no nightly
job. Gives 14 coding agents of historical data for free.

**Post-v1.0 surface additions (v1.1).** v1.0 deliberately capped the surface at
two entry points and four `RunHandle` methods. Real atlas dogfooding surfaced
two gaps that the existing surface can't cover without ugly workarounds, so v1.1
renegotiates the surface gate (see §7 and §10):

```python
# v1.1 — continue an existing run from a second process (atlas code_gen stage)
with plumb.resume_run(run_id="...") as r:   # third entry point
    r.add_span(...)

# v1.1 — record a rejection example from inside an active run
r.add_example(inputs_hash="...", source="production_promotion", rubric="...")  # fifth handle method
```

## 7. Non-goals

Explicit, because drift here is the single biggest failure mode for this
project. If you find yourself doing any of these in v1, stop and route the
work to v2 or ignore.

- **No fifth table.** Surveys, ESM prompts, cost ledgers all fold into
  existing tables (`runs.kind='survey'`, `scores.scorer='user_signal'`) or
  wait for v2. Four tables is the constraint. *(Still holds through v2.0. The
  v1.1 schema migration is additive — new columns/indexes on the four existing
  tables, no fifth table.)*
- ~~**No third entry point.**~~ → **Renegotiated in v1.1.** v1.0 capped the
  surface at decorator + context manager. v1.1 adds `plumb.resume_run(run_id)`
  as a third entry point because atlas's cross-process `code_gen` continuation
  cannot be expressed with the child-run workaround without losing same-run
  span lineage. Still no class hierarchy, no plugin system, no middleware
  pattern — the addition is one named callable with a documented contract.
  Rationale: atlas dogfooding is now the load-bearing user, and surface
  minimalism is no longer worth blocking a real integration need. See §10 v1.1.
- ~~**Exactly four `RunHandle` methods.**~~ → **Renegotiated in v1.1.** v1.0
  capped the handle at `add_score` / `add_span` / `set_models` / `abort`. v1.1
  adds `add_example(...)` as a fifth method so callers can record rejection
  examples programmatically from inside an active run, instead of reaching into
  the adapter layer. See §10 v1.1.
- **No custom dashboard.** Queries return JSON/DataFrame; visualization is
  out-of-scope. (If a post needs a chart, it ships as a one-off notebook.)
- **No SaaS.** Not a product. Not multi-tenant. Single-user SQLite file.
- **No real-time streaming.** Batch writes on run close. Backfill via
  ATTACH. No Kafka, no WebSocket, no live tail.
- **Not every failure mode.** Skipping: memory quality, context-window
  utilization, failure propagation, cascade depth, communication overhead
  (v2), long-running-agent subgoal annotation (v2), checkpointing metrics (v2).
- **No runtime blocking / guardrails.** After-the-fact eval only. (Galileo /
  Patronus philosophy split — we pick after-the-fact.)

## 8. Success metrics

Tiered, covering both technical correctness and external reach.

### Tier 1 — technical (does it work?)

| Metric                        | v1 target (end of Phase 1, Week 6)                        | v2 target (end of Phase 2, Week 9)              |
| ----------------------------- | --------------------------------------------------------- | ----------------------------------------------- |
| Instrumented atlas components | 4 of 4                                                    | 4 of 4 + external repo                          |
| Runs captured                 | ≥ 30 real instrumented runs                               | ≥ 100 real instrumented runs                    |
| Backfill coverage             | ≥ 2 weeks Claude Code sessions via ATTACH                 | ≥ 8 weeks                                       |
| Schema stability              | Zero schema migrations after Week 4                       | Zero migrations through Week 9                  |
| Entry-point surface           | Decorator + context manager only                          | Unchanged — a third entry point is a regression |

> **Gate update (2026-06-01, post-v1.0).** Two v1.0 Tier-1 gates are
> deliberately renegotiated for the v1.1 roadmap, not regressed:
> - **Schema stability** held through v1.0 (`SCHEMA_VERSION = 1`, zero
>   migrations). v1.1 performs *one* documented, additive migration
>   (`user_version` 1→2) and re-freezes the schema after it. The "zero
>   migrations within a release" discipline is preserved per-release.
> - **Entry-point surface** is intentionally widened in v1.1 (third entry
>   point `resume_run` + fifth handle method `add_example`) to unblock atlas.
>   This is a tracked decision (§7, §10), not an un-noticed regression.
| Judge drift guard             | `scorer_version` on every judge row                       | Judge re-calibration run completed              |
| Offline → online link         | `examples.origin_run_id` populated on ≥ 1 promoted case   | ≥ 10 promoted cases                             |
| CI regression gate            | Regression run passes on 200-task set with paired McNemar | Same, under a cost budget                       |

### Tier 2 — reach (does it earn attention?)

| Metric                       | v1 target (Week 6)               | Flagship (Week 11)                                               |
| ---------------------------- | -------------------------------- | ---------------------------------------------------------------- |
| Public GitHub repo           | README + install + quickstart    | Released, tagged v0.1                                            |
| GitHub stars                 | ≥ 10                             | ≥ 50                                                             |
| Public posts citing plumb    | ≥ 2                              | ≥ 6 (incl. flagship long-form)                                   |
| Long-form post engagement    | 1 post breaking 1k impressions   | Flagship post above 5k impressions                               |
| Inbound signal               | ≥ 1 DM referencing the framework | ≥ 5 DMs from interested practitioners                            |
| Reuse signal                 | ≥ 1 external fork or install     | ≥ 1 external team or person instrumenting their own work with it |

The Tier-2 numbers are aspirational, not gating. The Tier-1 numbers are gating:
if v1 ships without the schema stability and instrumented-components targets,
the flagship post has no data to stand on.

## 9. Risks & open questions

- **Judge quality.** Sonnet as default with Opus for routing + handoff is the
  chosen configuration; still need to verify Sonnet 4.6 holds on
  routing-top-1 before quoting the number publicly.
- **200-task regression set MDE.** At N=200, we accept ~5–7pp minimum
  detectable effect. Must state this explicitly in any model-swap post.
- **`agentsview` schema drift.** ATTACH is cheap today, but if the upstream
  schema changes we need a 1-hour migration path, not a re-design.
- **Scope creep from the research doc.** [`./measurement-framework-research.md`](./measurement-framework-research.md)
  is the 66KB literature synthesis; the canonical schema in
  [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md) supersedes it for v1 shape. The PRD
  points at the schema-and-metrics-v1 doc, not the raw literature synthesis, for v1 decisions.

## 10. Release Plan

v1.0 shipped (package version 1.0.x): four-table schema, decorator +
context-manager entry points, CLI, read-only HTTP service, ATTACH backfill, two
judge adapters, and the ten v1 metrics. The releases below sequence the deferred
backlog. Each entry maps back to a dated decision in
[`../2_architecture/deferred-features.md`](../2_architecture/deferred-features.md)
(the "From backlog" column), which holds the full per-option rationale.

Sequencing principle: **dependency before label.** The backlog labels some
metric work "v1.1", but that work sits *behind* the schema/atlas migration in
dependency order, so it is renumbered to **v1.2** here. The PRD Release Plan is
the authority; the backlog labels are traceability pointers, not commitments.

### v1.0 — shipped (baseline)

- Theme: minimal measurement spine — four tables, two entry points, ten metrics.
- Status: released, `SCHEMA_VERSION = 1`, zero migrations.

### v1.1 — Atlas unblock + schema v2 (next release)

- **Theme / Goal:** Close the silent-data-loss gaps and unblock the atlas
  integration. One additive schema migration (`user_version` 1→2) carries the
  whole data cluster; the surface gate is renegotiated for the two API items.
- **Target timeframe:** MVP+1 (next release).
- **Features included:**

  | Feature | From backlog | Notes |
  | --- | --- | --- |
  | `scores.rationale` durable column | "v2 — `scores.rationale` durable column" (2026-05-06) | DDL + `_score_to_row`/`_row_to_score` round-trip; entity field already exists. |
  | Idempotent score ingestion | "v2 — Idempotent score ingestion" (2026-05-06) | UNIQUE index on `(run_id, metric_name, scorer_version, span_id)`; `idempotency_key` on `add_score` + `plumb score write`. |
  | `spans.tokens_in` / `tokens_out` split | "v2 — Span `tokens_in` / `tokens_out` column split" (2026-04-29) | Splits the collapsed `spans.tokens` column; fixes the round-trip in/out asymmetry. |
  | `plumb.resume_run(run_id)` | "v2 — `plumb.resume_run(run_id)`" (2026-05-06) | **Third entry point.** Renegotiates FR-API-1 (see §7). Atlas `code_gen` cross-process continuation. |
  | `RunHandle.add_example(...)` | "v2 — `RunHandle.add_example(...)`" (2026-05-06) | **Fifth handle method.** Renegotiates FR-API-4 (see §7). |

- **Schema discipline:** exactly one migration, additive only (no fifth table,
  no destructive rewrites). `SCHEMA_VERSION` bumps to 2 and the schema re-freezes
  for the rest of the release.
- **Gate impact:** widens the entry-point surface (§7, §8 gate update). This is
  the deliberate philosophy shift — atlas dogfooding now outweighs strict
  surface minimalism.

### v1.2 — Metric depth (the flagship post needs this)

- **Theme / Goal:** Richer failure analysis for the long-form write-up. No
  further schema migration — every new score fits the existing `scores` table
  via `metric_name`.
- **Target timeframe:** MVP+2.
- **Features included:**

  | Feature | From backlog | Notes |
  | --- | --- | --- |
  | Plan-vs-execution attribution | "v1.1 — Plan-vs-execution attribution" | `scores.metric_name='plan_failure'`/`'execution_failure'`; re-run failed trajectories with a stronger executor. |
  | MAST 14-mode failure tagging | "v1.1 — MAST 14-mode failure tagging" | `scores.metric_name='mast_mode'`, `value_label=<mode_id>`; needs ≥30 failed runs to validate. |
  | Judge calibration vs human α | "v1.1 — Judge calibration against human-human α baseline" | Krippendorff's α on a labeled held-out set; the scaffold (`scorer_version`) already shipped in v1.0. |
  | Concurrent judge calls (`--concurrency N`) | "v1.1 — Concurrent judge calls" | Thread-pool behind a flag; makes the above tractable at backlog scale. |
  | Per-metric model env overrides | "v1.1 — Per-metric model env overrides" | Plan-vs-exec wants Opus, cheap binary metrics want Haiku. |

- **Renumber note:** the backlog labels these "v1.1"; they are scheduled here as
  v1.2 because they depend on v1.1's judge-throughput and migration work landing
  first.

### v2.0 — Analysis, scale & alternative judges

- **Theme / Goal:** Reporting frontiers, alternative judge backends, and judge
  throughput at scale. Experiment- and content-driven; the largest release.
- **Target timeframe:** MVP+3 / next major version.
- **Features included (each maps to a backlog entry):**
  - Variance decomposition / regression-eval (`plumb regression-eval`).
  - Efficiency-frontier report (`plumb report efficiency-frontier`).
  - Router Pareto-frontier report (`plumb report router-frontier`).
  - Long-running-agent extension (subgoal annotation, loop/stagnation detection).
  - Luna-2-style SLM judges at 100% coverage (third judge adapter).
  - Multi-judge consensus / ensembling.
  - Streaming verdicts.
  - Tool-use judges (CLI-style) — depends on the Protocol/ABC extension seam.
  - File-backed prompt edit UX (`plumb judge prompt create/list/show`).
  - `plumb run stats` top-level-only display (`--include-children` flag).

### Deferred Features (no commitment, revisit on trigger)

These are recorded in the backlog but **not scheduled** into any release above.

- **Judge-adapter Protocol/ABC extension seam** — gates SLM and tool-use
  judges; ship only when a concrete third-party adapter (Bedrock/Vertex) is
  requested. *Low ROI until a real external adapter need exists.*
- **Agentic-CLI-backed judge adapter (ClaudeCodeJudge / CodexCLIJudge)** —
  breaks `scorer_version` determinism; blocked on both a stable CLI judging mode
  *and* the Protocol seam above. *Won't do until both conditions hold.*
- **WAL/SHM file permissions hardening** — single-user local posture makes this
  low-priority; revisit if plumb runs in shared/multi-user CI. *Low ROI vs.
  FileVault/LUKS already covering the threat.*
- **Runtime blocking / guardrails** — permanent non-goal (§7 philosophy split).
  *Won't do; a different product.*
- **Fifth SQL table** — permanent non-goal; the four-table constraint is the
  thesis. *Won't do.*

## 11. Links

- Canonical schema + metric derivation: [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md)
- Deferred-options backlog (per-decision rationale): [`../2_architecture/deferred-features.md`](../2_architecture/deferred-features.md)
- Research backlog (literature synthesis): [`./measurement-framework-research.md`](./measurement-framework-research.md)
- Project README: [`../../README.md`](../../README.md)

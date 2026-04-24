# plumb — Product Requirements Document

**Status:** Draft (Phase 0 → Phase 1 hand-off)
**Owner:** anant

---

**Plumb measures what current agent-telemetry tools don't: whether a human
actually accepted the agent's output, where the orchestrator routed, how
sub-agents handed off, and what it cost to get the answer.** A small Python
package + SQLite schema + two entry points. The keystone artifact for a
multi-agent Personal OS; designed to generalize to any small DevEx / AI-ML /
agentic-systems team.

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
  flagship write-up: *"I built a measurement framework, instrumented my
  Personal OS with it, ran it for 8 weeks — here's what the data says."*

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

v1.1 adds plan-vs-execution attribution and MAST-style 14-mode failure
tagging. Everything else is explicitly v2 or out-of-scope (see §7).

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

## 7. Non-goals

Explicit, because drift here is the single biggest failure mode for this
project. If you find yourself doing any of these in v1, stop and route the
work to v2 or ignore.

- **No fifth table.** Surveys, ESM prompts, cost ledgers all fold into
  existing tables (`runs.kind='survey'`, `scores.scorer='user_signal'`) or
  wait for v2. Four tables is the constraint.
- **No third entry point.** Decorator + context manager is the full surface.
  No class hierarchy, no plugin system, no middleware pattern.
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

Tiered, covering both technical and portfolio outcomes.

### Tier 1 — technical (does it work?)

| Metric                        | v1 target (end of Phase 1, Week 6)                        | v2 target (end of Phase 2, Week 9)              |
| ----------------------------- | --------------------------------------------------------- | ----------------------------------------------- |
| Instrumented atlas components | 4 of 4                                                    | 4 of 4 + external repo                          |
| Runs captured                 | ≥ 30 real instrumented runs                               | ≥ 100 real instrumented runs                    |
| Backfill coverage             | ≥ 2 weeks Claude Code sessions via ATTACH                 | ≥ 8 weeks                                       |
| Schema stability              | Zero schema migrations after Week 4                       | Zero migrations through Week 9                  |
| Entry-point surface           | Decorator + context manager only                          | Unchanged — a third entry point is a regression |
| Judge drift guard             | `scorer_version` on every judge row                       | Judge re-calibration run completed              |
| Offline → online link         | `examples.origin_run_id` populated on ≥ 1 promoted case   | ≥ 10 promoted cases                             |
| CI regression gate            | Regression run passes on 200-task set with paired McNemar | Same, under a cost budget                       |

### Tier 2 — portfolio (does it earn attention?)

| Metric                           | v1 target (Week 6)               | Flagship (Week 11)                                               |
| -------------------------------- | -------------------------------- | ---------------------------------------------------------------- |
| Public GitHub repo               | README + install + quickstart    | Released, tagged v0.1                                            |
| GitHub stars                     | ≥ 10                             | ≥ 50                                                             |
| Build-journal posts citing plumb | ≥ 2                              | ≥ 6 (incl. flagship long-form)                                   |
| LinkedIn/Substack engagement     | 1 post breaking 1k impressions   | Flagship post above 5k impressions                               |
| Inbound signal                   | ≥ 1 DM referencing the framework | ≥ 5 DMs / recruiter messages                                     |
| Reuse signal                     | ≥ 1 external fork or install     | ≥ 1 external team or person instrumenting their own work with it |

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

## 10. Links

- Canonical schema + metric derivation: [`./schema-and-metrics-v1.md`](./schema-and-metrics-v1.md)
- Research backlog (literature synthesis): [`./measurement-framework-research.md`](./measurement-framework-research.md)
- Project README: [`../../README.md`](../../README.md)

# Measurement framework research — working document

A research brief for designing a personal measurement framework (Python + SQLite, tables: `runs`, `tasks`, `interventions`, `costs`; decorator + context manager entry points). Weighted toward schema design. Sources span SPACE, DORA, DX Core 4, McKinsey, Fowler/Cochran, Tacho, Majors (observability), Meyer/Fritz ESM lineage, Anthropic Economic Index, METR, MSR 2026 academic work, and practitioner commentary (Orosz, Beck, Larson). Where sources disagree, the disagreement is called out explicitly — papering over would destroy the positioning.

> **Terminology note (added after the schema refactor).** This doc was written against the earlier four-table schema (`runs`, `tasks`, `interventions`, `costs`). The canonical schema is now `runs`, `spans`, `scores`, `examples` — see `[./schema-and-metrics-v1.md](./schema-and-metrics-v1.md)`. Translate as you read: "tasks table" → "`spans` table"; "interventions table" → "`scores` rows with `scorer='user_signal'`" (each HITL event is a score observation on a run or span, not its own table); "costs table" → costs fold into `runs.dollar_cost` plus per-span `tokens` (LiteLLM-style pricing-version snapshot still applies); the longitudinal-survey gap at the bottom of §2 closes via `scores` rows with `scorer='human'` rather than a fifth table or a `kind='survey'` run. The substantive content — the three-method model (§2), the 12 positioning metrics (§4: Vibe Calibration, Micro-Intervention Density, MCP Friction Tax, Token-Cost-to-Value, Autonomous Rework Rate, Model Routing Leakage, Attention Cost, Structure-vs-Behavior, Sustained-Focus, Cache-Hit by Route, Time-to-First-Intervention, Cost per Hour of Attention Saved), and the disagreement flags in §3 — are all unchanged: they're about the cybernetic human-plus-agent workflow being measured, not which table holds the rows. For v1 metric alignment: "intervention rate" is already listed as one of the ten in the eval spine, and the run-level cost/latency/token fields collapse into `runs.dollar_cost` / `runs.end_ts − start_ts` / `runs.tokens_in+tokens_out`. The SQLite DDL at the bottom of this doc is retained as a column-level reference (post-hoc E fields, UUIDv7 keys, pricing-version snapshot, OpenTelemetry GenAI alignment) but the table partitioning is superseded by the four-table spine in `[./schema-and-metrics-v1.md](./schema-and-metrics-v1.md)`.

---

## Section 1 — The canon: what's already been figured out

The industry has decisively moved past Taylorist line-counting and keystroke-tracking. A canon of rigorous, empirically validated frameworks has emerged to define how engineering effectiveness should be measured. Five frameworks dominate. They agree on less than the vendors imply: convergence is real at the dimension level but breaks down at the metric level and collapses entirely on individual measurement.

### SPACE (Forsgren, Storey, Maddila, Zimmermann, Houck, Butler — ACM Queue 2021, id=3454124)

Five dimensions: **Satisfaction & well-being, Performance, Activity, Communication & collaboration, Efficiency & flow**. Explicitly multi-level (individual / team / system) and explicitly multi-method (telemetry + surveys). The governing rule: **pick ≥2 dimensions in tension**, never a single metric.

> "Developer productivity is about more than an individual's activity levels or the efficiency of the engineering systems… it cannot be measured by a single metric or dimension."

SPACE introduced the insight that **perceptual measures — capturing the "voice of the developer" through surveys — are as valid as objective system telemetry**. System data might show that a code review was completed in ten minutes, but only a perceptual survey can reveal if that rapid review disrupted the reviewer's flow state or compromised psychological safety. This dual reliance on workflow and perceptual measures cemented developer sentiment as a leading indicator of organizational health.

*Note on ACM Queue ID collisions:* the paper at `queue.acm.org/detail.cfm?id=3595878` is the **DevEx paper** (Noda/Forsgren/Storey/Greiler, 2023), not SPACE. Original SPACE is id=3454124. The two are often conflated.

### DORA (Google Cloud, State of DevOps 2024 and 2025)

Originally four keys (deployment frequency, lead time for changes, change failure rate, mean time to restore/MTTR). These metrics successfully categorized organizations into low/medium/high/elite performers and proved that speed and stability are mutually reinforcing, not opposed, in high-performing teams.

**DORA 2024 restructured** into two clusters — *throughput* (deployment frequency, lead time, **rework rate** — new) and *instability* (change failure rate, failed deployment recovery time). **DORA 2025 replaced the four performance clusters with seven team archetypes** (e.g., "Harmonious high achievers," "Legacy Bottleneck") blending delivery metrics with burnout, friction, and "valuable work" percentage. Data comes from over 5,000 technology professionals.

The 2025 DORA report's framing is: **AI acts as an organizational amplifier, not a panacea** — 90% of technology professionals report daily AI use, but AI accelerates well-structured teams while magnifying dysfunctions and technical debt in struggling ones. The **rework rate** (ratio of unplanned deployments caused by production issues vs. total deployments) was formally added in 2024 and reinforced in 2025 as a secondary stability metric, specifically because AI-assisted workflows boost raw throughput at the direct expense of code stability.

DORA's AI findings are the single most important empirical input for positioning this framework. See Section 3.

### DX Core 4 (Noda, Tacho, Storey, Greiler — 2024)

Collapses SPACE + DORA + DevEx into four counterbalanced dimensions, each with one "key" metric: **Speed** (diffs per engineer), **Effectiveness** (Developer Experience Index — DXI — 14 Likert items), **Quality** (Change Failure Rate), **Impact** (% time on new capabilities). Marketed as the consolidation move.

Metrics such as "diffs per engineer" are utilized only under strict preconditions: they must be counterbalanced by an oppositional metric, strictly divorced from individual performance rewards, and communicated transparently to prevent behavioral gamification.

The keystone is the **Developer Experience Index (DXI)**. Research spanning over 4 million benchmark samples demonstrates DXI as the first validated measure of developer productivity tied to financial value. A one-point DXI gain translates to ~~13 minutes/week/developer saved (~~10 hours annually). Top-quartile DXI performers exhibit engineering speed and quality four to five times higher than bottom-quartile peers, alongside 43% higher employee engagement.

**Tension worth naming:** SPACE's co-authors are on the Core 4 byline, yet Core 4 ships "one key metric per dimension" after SPACE's paper warned productivity "cannot be reduced to a single metric." DX's defense is that Core 4 only works when the four oppositional metrics are read together. Critics note DXI's 14 items are proprietary (vendor lock-in).

### McKinsey ("Yes, you can measure software developer productivity" — Gupta & Gnanasambandam, 2023)

Three levels × three types. Levels: system, team, **individual**. Types: Outcomes, Optimization, Opportunities. Imports DORA + SPACE, adds:

- **Inner-loop vs outer-loop time** — argues developers should spend 70% of their time on value-generating inner-loop activities (coding, building, unit testing) rather than outer-loop chores (integration, deployment, manual testing).
- **Developer Velocity Index (DVI)** — benchmark score.
- **Contribution Analysis** — proprietary algorithms analyzing individual contributions to team backlogs in tools like Jira, surfacing trends that inhibit capacity or highlight upskilling needs.
- **Talent Capability Score**.

This is the framework that broke the consensus — it openly endorses individual measurement.

> "it's essential to understand the three types of metrics that need to be tracked: those at the system level, the team level, **and the individual level**."

The algorithmic individual tracking triggered massive industry backlash. Kent Beck (with Gergely Orosz) called it "absurdly naive… certain to backfire." The practitioner consensus: applying system-level delivery metrics to individuals demonstrates a fundamental misunderstanding of software as collaborative knowledge work, treating engineers like factory line workers rather than creative contributors.

### Fowler / Cochran / Noda — developer effectiveness + DevEx

Two complementary pieces.

**Cochran's "Maximizing Developer Effectiveness"** defines effectiveness not by raw output but by removal of friction and cognitive overhead. Categorizes metrics into lagging indicators (DORA) and leading indicators (specific developer feedback loops). The flagship insight is the measurement of **micro-feedback loops** — the tasks developers perform 100 to 200 times a day (like validating a local code change). In a highly effective environment, local validation takes 5–15 seconds; in a low-effectiveness environment, 2 minutes. A 2-minute compile seems trivial to management, but the delays compound into 100+ minutes/day of lost time. More detrimentally, delays longer than 15 seconds invite distractions that shatter flow state — and psychological research cited by Cochran indicates it takes up to **23 minutes to return to peak cognitive productivity** after a flow break.

**Noda/Forsgren/Storey/Greiler's DevEx paper** (ACM Queue 2023, id=3595878) distills three dimensions: **feedback loops, cognitive load, flow state**, each measured via both workflow telemetry and perceptual surveys.

**Fowler's companion piece** ("Measuring Developer Productivity via Humans") draws the methodological line: qualitative metrics are *data provided by humans*, split into **attitudinal** (how devs feel) and **behavioral** (what devs report doing). Rejects the word "productivity" in favor of "developer experience." Argues system telemetry alone cannot measure intangibles like technical debt, ease of codebase navigation, or the cognitive tax of a fragmented internal toolchain.

### Laura Tacho's two posts

**First post** (individual performance): team/system metrics (PRs, commits, story points, LOC, deployment frequency) are **inappropriate for individual performance**. The exception: "manager-of-managers whose job is to improve a system." Her argument is anchored in Goodhart's Law — when a measure becomes a target, it ceases to be a good measure. If management targets commit counts, developers produce "dirty git histories" to inflate numbers; if code coverage is targeted, developers write superficial tests that fail to improve change failure rate. For senior engineers, this means measuring project on-time delivery, partner satisfaction, and architectural impact, using activity data only to "debug" why an outcome was missed.

**Second post** (survey design): anonymous, 8–12 week cadence to avoid fatigue, 1–10 Likert, segmented by cohort, always paired with an intervention loop. Mandates equal weighting of categories to prevent bias and **negative framing** (e.g., balancing "Our processes are efficient" with "I feel like my time gets wasted") as a check against positive reporting bias.

### Charity Majors — observability as the substrate

Majors' Observability 2.0 position is that traditional observability built on "three pillars" (metrics, logs, traces) is outdated — it silos data and strips away the context engineers actually need. Instead: **wide, high-cardinality, arbitrarily structured events**. Rows, not aggregates. Dashboards are "a poor view into software"; SLOs are the real API between engineering and the business.

This matters directly for schema design: every `runs` row should append wide contextual metadata (active git branch, specific model weights, local file state, MCP servers connected) so post-hoc analysis isn't aggregated into useless averages but remains fully queryable for "unknown-unknowns."

### Will Larson — process vs impact

Larson's position in "Measures of engineering impact": DORA metrics are *process measures, not impact measures*. Synthetic metrics derived from event traces beat pre-aggregated dashboards. Reinforces the "store events, derive views" design decision below.

### Comparison table


| Framework               | Primary dimensions                                               | Individual measurement stance                         | Preferred methods                  | Single-number metric?                      |
| ----------------------- | ---------------------------------------------------------------- | ----------------------------------------------------- | ---------------------------------- | ------------------------------------------ |
| SPACE (2021)            | Satisfaction, Performance, Activity, Collaboration, Efficiency   | Allowed only in tension with others; warns against it | Telemetry + surveys                | **No** — explicit prohibition              |
| DORA (2024/25)          | Throughput + Instability; 7 team archetypes (2025)               | Team-level only                                       | Survey-driven benchmarks           | No                                         |
| DX Core 4 (2024)        | Speed, Effectiveness, Quality, Impact                            | Diffs/eng NOT at individual level                     | Telemetry + surveys + ESM          | **Yes** — DXI marketed as "the one number" |
| McKinsey (2023)         | Outcomes, Optimization, Opportunities × (system/team/individual) | **Endorses individual measurement**                   | Surveys + backlog data             | No, but DVI benchmark is close             |
| Fowler / DevEx          | Feedback loops, Cognitive load, Flow                             | Rejects for performance grading                       | Workflow + perceptual              | No                                         |
| Tacho                   | Uses DX Core 4                                                   | **Against** for ICs; allows for manager-of-managers   | Surveys + retros + interviews      | No                                         |
| Cochran (Effectiveness) | Friction reduction via micro-feedback loops                      | Environmental, not individual                         | Workflow telemetry + human reports | No                                         |


### What's converged, what isn't

**Converged enough to treat as settled:**

1. **Productivity is multidimensional.** No serious framework uses a single metric in isolation.
2. **Multi-method beats any single method.** Telemetry alone misses context; surveys alone drift.
3. **Balanced metrics beat single-number metrics at the team level.** Speed must always be counterbalanced by stability and quality.
4. **Feedback loop speed (inner loop) is a first-class metric.** Cochran, DevEx, DX Core 4, McKinsey all converge here.
5. **Qualitative data is first-class data**, not a softer supplement.
6. **Flow state preservation is central to value creation.**

**Live disagreements:**

- **SPACE vs McKinsey on individual measurement.** SPACE: "deployment frequency is not a useful way to track individual performance." McKinsey: individual metrics are essential. Beck + Orosz: McKinsey's framework is "absurdly naive." This is the live political fault line.
- **DX Core 4 vs SPACE on single-number metrics.** DX ships "the one number"; SPACE explicitly rejects single-number framing. Reconciled only by rhetorical sleight (DXI is "one number within a four-metric system").
- **Tacho vs McKinsey on Contribution Analysis.** Tacho: "An individual cannot fully control their performance within a system where they are just one contributor." McKinsey: Contribution Analysis solves exactly this.
- **DORA 2024 vs DX on AI.** DORA 2024: 25% more AI adoption → throughput −1.5%, stability −7.2%. DX publishes customer gains of 16–41%. DORA 2025 partially reconciles (throughput flipped positive in mature orgs; stability remains negative).
- **Larson and Majors vs the rest.** Both argue SPACE/DORA measure *process*, not *impact*. Majors: SLOs as the real API; dashboards are "a poor view." Larson: DORA metrics are "process measures, not impact measures."
- **Operations-centric vs human-centric.** The deepest philosophical split: McKinsey-style frameworks seek to algorithmicize individual backlog contributions; Tacho/Fowler/DX rely on qualitative surveys and team-level outcome measurement to preserve psychological safety and prevent gamification.

---

## Section 2 — The three-method model applied to the user's schema

DX's three-method model — **tool-based telemetry + periodic surveys + experience sampling (ESM)** — is the most defensible scaffolding for schema design because it maps cleanly onto what a decorator/context manager can and cannot naturally capture.

Experience Sampling Methodology (ESM), also known as Ecological Momentary Assessment (EMA), is a research technique designed to capture thoughts, feelings, and behaviors as they occur in their natural environment. By prompting users in the flow of work, ESM eliminates the retrospective recall bias that plagues end-of-quarter surveys.

Reverse-engineered:


| Method                        | What it captures                                                  | Natural entry point                                                       | What's missing in the 4-table design                                                  |
| ----------------------------- | ----------------------------------------------------------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------- |
| **Telemetry**                 | Run/task/cost rows auto-emitted at boundaries                     | Context manager (block enter/exit) + decorator (function enter/exit)      | Nothing — this is what the framework is built for                                     |
| **Periodic surveys**          | Long-term self-report (weekly/quarterly Likert)                   | Neither — needs a CLI `pos survey` or scheduled prompt                    | A 5th table: `surveys` — OR fold into `runs` with `kind='survey'`                     |
| **Experience sampling (ESM)** | In-flow prompts at task/run end ("how productive did that feel?") | Context manager `__exit__` is the natural trigger; decorator can wrap too | Belongs in `runs` (run-level Likert) + `interventions` (triggered reflective prompts) |


### The context manager → telemetry (runs, costs)

The context manager is the engine for objective system telemetry. Its `__enter__` and `__exit__` dunder methods programmatically log millisecond-precision timestamps, exact duration, exit codes, process IDs, and success/exception status — **no developer friction, fully deterministic**. Concurrently, it captures `costs` by hooking the I/O streams within the block: prompt tokens, completion tokens, inference costs, and compute overhead, all keyed to the run.

The design pulls directly from Majors' Observability 2.0 framing: every row should carry wide contextual metadata (git branch, model weights, MCP servers, file state) so post-hoc analysis isn't reduced to aggregated averages.

**Telemetry's blind spot** (Fowler, Noda): it cannot capture subjective friction. The context manager records that a run took 45 seconds and cost $0.02 but cannot determine whether those 45 seconds were an acceptable compile or a flow-shattering disruption.

### The decorator → experience sampling (tasks, interventions)

The decorator bridges that gap. By wrapping functional logic, it can pause execution, intercept exceptions, and prompt the user at the point of action. When an AI agent enters an infinite loop, hallucinates a file path, or the developer forcibly terminates via Ctrl+C, the decorator catches the event and triggers a micro-survey: *"Why did you override the agent?"* / *"What context was the tool missing?"* — written immediately to `interventions`. It also captures `tasks` pre/post-execution with subjective difficulty, goal alignment, and cognitive load.

This maps directly to Fowler's "transactional surveys" concept — short, high-frequency prompts triggered by specific system interactions, without broad survey fatigue.

**Decorator's limitation**: it demands user compliance. Frequent halts for input introduce the very friction the framework is measuring — a direct violation of Cochran's micro-feedback-loop imperative. Event-based ESM triggers can also produce fragmented data if the developer habitually skips prompts during high-stress incidents.

### Mapping table


| Schema table    | Primary entry point | DX pillar                 | Data captured                                                        | Strengths / limitations                                                                    |
| --------------- | ------------------- | ------------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| `runs`          | Context manager     | Telemetry / observability | Timestamps, latency, exit codes, git branches, loaded MCP servers    | Objective, high-cardinality, zero friction / cannot measure cognitive load                 |
| `costs`         | Context manager     | Telemetry / observability | Token counts, API inference pricing, compute overhead                | Millisecond-precision economic tracking / does not measure output value                    |
| `interventions` | Decorator           | Experience sampling (ESM) | Human-in-the-loop overrides, exception categorization, abort reasons | Eliminates recall bias, captures context of failure / high frequency risks disrupting flow |
| `tasks`         | Decorator           | Experience sampling (ESM) | Subjective task difficulty, goal alignment, effort estimation        | Aligns system execution with human intent / relies on developer compliance                 |


### The missing method: the longitudinal survey gap

The schema naturally misses the third pillar: the **longitudinal survey**. The Personal OS operates at the microscopic "inner loop" — it excels at measuring friction of a specific run or cost of a single task, but SPACE/DevEx rely on periodic, macro-level assessments (satisfaction, psychological safety, DXI) that a Python decorator cannot effectively capture. You won't get good signal asking a developer to rate overall codebase health or quarterly collaboration quality from a `__exit__` hook.

**Options to close the gap:**

1. Add a 5th table `surveys`.
2. Keep 4 tables; schedule periodic surveys as a CLI-triggered path writing into `runs` rows with `kind='survey'`, one `tasks` row per item, response in `score_value`.
3. Supplement with an external weekly macro-prompt or integrated markdown journaling system.

**Recommendation:** option 2 — preserves the "4 tables, 2 entry points" contract while still implementing the DX tripartite approach faithfully.

### Recommended fields per table

Legend: **C** = cheap (auto-captured), **E** = expensive (user input / post-hoc).

#### `runs` — one row per decorated function call or context manager scope

Core identity and lineage: `run_id` (UUIDv7, C), `parent_run_id` (C), `session_id` (C), `kind` (enum: `agent_orchestrator` / `content_pipeline` / `ml_training` / `eval` / `survey` / `manual_task`, C), `name` (C), `entry_point` (`decorator` | `context_manager`, C), `project` (C), `git_sha` (C), `code_version` (C), `env` (C), `config_json` (C), `tags_json` (C).

Lifecycle and status: `status` (`running` / `success` / `error` / `aborted` / `timeout`, C), `error_type` (C), `error_message` (C, truncated), `started_at` / `ended_at` / `duration_ms` (C).

Content refs: `input_summary` / `output_summary` (C, truncated previews only — full content in blob refs).

Denormalized rollups (critical for dashboard speed in SQLite): `total_tokens` (C), `total_cost_usd` (C), `num_llm_calls` (C), `num_tool_calls` (C), `num_interventions` (C).

Self-report / ESM fields (filled post-run): `goal_achieved` (0/1/NULL, **E**), `goal_quality_score` (1–5, **E**), `satisfaction_score` (1–7 Likert per Meyer, **E**), `flow_state` (1–7, **E**), `perceived_productivity` (1–7 Likert, **E**), `ai_time_saved_min` (DX's direct metric, **E**), `pre_task_estimated_min` (**E** — enables the Vibe Calibration Score; see §4), `notes` (**E**).

Indexes: `(started_at)`, `(project, started_at)`, `(kind, status)`, `(session_id)`.

#### `tasks` — one row per subunit inside a run (LLM call, tool call, agent step, pipeline stage, training epoch, eval sample, human review)

Identity: `task_id` (C), `run_id` FK (C), `parent_task_id` (C), `type` (enum, C), `name` (C), `status` (C), `error_type` (C).

Timing (aligned with OpenTelemetry GenAI SemConv attribute names, so the table is future-interop with Datadog/Traceloop/Braintrust exporters): `started_at` / `ended_at` / `duration_ms` (C), `ttft_ms` (time-to-first-token for streaming, C).

LLM-specific: `model` (`gen_ai.request.model`, C), `provider` (C), `operation` (C), `input_tokens` (C), `output_tokens` (C), `reasoning_tokens` (C — critical for o-series and Claude extended thinking), `cached_tokens` (C — prompt caching prices 10–90% less), `temperature` (C), `max_tokens_req` (C), `finish_reason` (C — distinguishes `length` truncation from clean `stop`).

Tool-specific: `tool_name` (C), `tool_call_id` (C).

Retry/self-correction: `retry_count` (C), `was_retry_of` (FK to task_id, C).

Content refs: `input_ref` / `output_ref` (C — content-addressable hash or path), `input_preview` / `output_preview` (C), `metadata_json` (C).

Context-loading instrumentation (enables the MCP Friction Tax metric; see §4): `context_load_ms` (C) and `generation_ms` (C) as a decomposition of `duration_ms` when measurable.

Evaluation (**E** fields): `score_value` (Langfuse analog), `score_label`, `scorer_name`, `accepted` (0/1 — was output accepted downstream).

Meyer-lineage ESM fields (for manual task rows): `task_type_self_report` (coding / review / planning / email / meeting, **E**), `perceived_difficulty` (1–7, **E**).

Indexes: `(run_id, started_at)`, `(type)`, `(model)`, `(parent_task_id)`, `(status)`.

#### `interventions` — one row per human-in-the-loop event OR self-triggered ESM prompt

This is where the framework stakes its positioning. No existing observability tool has a first-class interventions table; they all fold HITL into generic "scores" or "feedback."

Identity: `intervention_id` (C), `run_id` FK (C), `task_id` FK (C, nullable).

Type/trigger: `kind` (enum: `approval` / `rejection` / `edit` / `abort` / `retry_triggered` / `clarification` / `manual_override` / `feedback` / `tool_denied` / `rollback` / `esm_prompt` / `stream_interrupt` / `immediate_post_edit`, C), `trigger` (`policy` — agent asked / `user_initiated` / `confidence_gate` / `error_recovery` / `schedule` / `timeout`, C). The `trigger` field distinguishes "agent asked for help" (Inspect AI's tool approval model; HiL-Bench's ask-F1) from "user barged in" (Anthropic's interventions-per-session).

The additional `stream_interrupt` and `immediate_post_edit` kinds capture **micro-interventions** — Ctrl+C on a running stream, or a manual edit of a file within N seconds of the agent touching it — which are essential for the Micro-Intervention Density metric (see §4).

Timing: `detected_at` (C), `responded_at` (C), `wait_ms` (time-to-review, C), `response_ms` (time spent composing, C).

Outcome: `outcome` (`approved` / `approved_with_edits` / `rejected` / `ignored` / `timed_out`, C), `actor` (C).

Edit quantification: `edit_distance` (C — Levenshtein or token-diff), `edit_ref` (C), `tokens_before` / `tokens_after` (C).

Reflection: `severity` (low/medium/high — for autonomy weighting, **E**), `reason` (free-text categorized post-hoc, **E**), `rework_flag` (0/1 — this intervention reverses previously accepted work; DORA rework-rate feed, **E**), `confidence_at_trigger` (C — model/policy confidence if available).

Beck's structure-vs-behavior dimension: `change_class` (`behavior` / `structure` / `mixed` / `n/a`, **E**) — lets you separate feature work from refactor/cleanup interventions.

Silent-loop instrumentation: `is_autonomous` (0/1, C — was this recovery done by the agent itself without surfacing to the human?). Enables the Autonomous Rework Rate (see §4).

Metadata: `metadata_json` (C).

Indexes: `(run_id, detected_at)`, `(task_id)`, `(kind)`, `(trigger)`, `(is_autonomous)`.

#### `costs` — one row per billable unit

Every non-LLM framework ignores this table; that's a gap. Anthropic, Cursor, Sourcegraph only expose aggregate token counts. A personal framework with `costs` as a top-level table is a differentiator.

Identity: `cost_id` (C), `run_id` FK (C — tag at creation time, never backfill), `task_id` FK (C, nullable for run-level costs), `ts` (C).

Classification: `category` (enum: `llm_tokens` / `tool_api` / `compute_gpu` / `compute_cpu` / `storage` / `human_minutes` / `egress` / `third_party`, C), `subcategory` (`prompt` / `completion` / `reasoning` / `cached_read` / `cached_write` / `batch`; for tools: `search` / `browser` / `code_exec`, C), `provider` (C), `model` (C).

Quantity and price: `quantity` (C), `unit` (`tokens` / `seconds` / `calls` / `minutes` / `bytes`, C), `unit_price_usd` (C — pricing snapshot at time of call, not retrieved at query time), `cost_usd` (C), `pricing_version` (C).

Attribution (denormalized for fast group-by): `attribution_user` (C), `attribution_project` (C), `attribution_route` (C — tag like "inbox-triage" / "research" / "refactor"), `cache_hit` (0/1, C).

`metadata_json` (C).

Indexes: `(run_id)`, `(task_id)`, `(ts)`, `(category, model)`, `(attribution_user, ts)`.

### How each method maps to entry points

**Decorator**: naturally emits one `runs` row (enter/exit), N `tasks` rows (nested spans via explicit helpers or OTel auto-instrumentation), and M `costs` rows (auto-emitted from the LLM client wrapper). ESM prompt on `__exit`__ writes one `interventions` row with `kind='esm_prompt'` and pipes the response into the run's `perceived_productivity` / `satisfaction_score` fields. **Cheap everywhere except the ESM response.**

**Context manager**: same, but explicit `with` scope makes it easier to tag arbitrary human work (code review sessions, reading docs) where no function boundary exists. This is the path for the "my own coding time" slice that decorators can't cover.

**Periodic surveys** (quarterly): write as `runs` with `kind='survey'`, one `tasks` row per item, response in `score_value`. Keeps the 4-table contract.

### What the three-method model misses for this user

1. **No first-class agent-intervention taxonomy.** DX's framework assumes the developer is a human. When the "developer" is a multi-agent orchestrator, ESM prompts are nonsensical and surveys are meaningless — you can't ask GPT-5 how it felt about the sprint. The `interventions` table replaces surveys in this regime (see Section 3).
2. **No cost-per-task notion.** DX tracks "AI tooling spend" as an aggregate. Solo operators with their own API keys need per-task attribution.
3. **Persistence / rework is under-specified.** Ziegler 2022 had persistence@30s/2min/10min/30min; DX's framework dropped it for simplicity. The `interventions.rework_flag` + `tasks.accepted` enables this natively.
4. **No silent-failure channel.** Agents that recover from their own errors invisibly are a measurement blind spot. `interventions.is_autonomous` closes this.

---

## Section 3 — Agent-driven and solo-developer measurement: the gap

The canon was designed for human teams operating in traditional CI/CD pipelines. When the "developer" is no longer a single human at a keyboard but a hybrid node — a human orchestrator plus a suite of semi-autonomous agents (Cursor, Claude Code, Devin) — the foundational assumptions break in specific, documented ways. The industry is calling this "Software Engineering 3.0."

### What the canon measures well and what it misses

**Handled well by existing frameworks** (adapt and reuse): throughput (PR count, deploy frequency), change failure rate, lead time, survey-based satisfaction, DevEx dimensions (feedback loops, cognitive load, flow) — though the latter need redefinition for agent work.

**Breaks down entirely**:

- **Raw output volume loses diagnostic power.** An autonomous agent in a sandbox can generate hundreds of commits and simulate thousands of deployments in minutes. "Diffs per engineer" becomes meaningless when an AI code assistant can scaffold a 5,000-line React application instantaneously — tracking raw output merely measures the LLM's API rate limit.
- **DORA's lead time and deployment frequency lose meaning** at the individual-plus-agent level for the same reason.
- **Trust paradox.** 2025 DORA: 90% of devs use AI, >80% report productivity gains, yet 30% still have little to no trust in AI-generated code. The gap between usage and trust is itself a missing metric.

**Missed entirely or handled poorly**:

- **Intervention rate / human-takeover events.** Anthropic's Claude Code instrumentation counts interventions-per-session but hasn't published a full schema. HiL-Bench proposes "ask-F1" (harmonic mean of ask-precision and ask-recall) but isn't in industry use.
- **Cost-per-task.** LLM observability tools (Langfuse, AgentOps, Braintrust) track cost per trace; none track cost per *completed* task with a rework/acceptance filter. A task that cost $4 and got reverted isn't $4 of value.
- **Agent autonomy score.** Multiple groups have proposed variants (Factory Signals, Anthropic's severity-weighted interventions); no standard. Anthropic's Feb 2026 Economic Index reports **AI Autonomy on Claude.ai at 44.6%**.
- **Rework rate on agent-produced code.** DORA 2024 added rework rate as a generic metric but didn't separate AI-authored from human-authored work. GitClear measures churn across a repo but can't attribute.
- **Time-to-review for AI PRs.** Faros' analysis of 10,000+ developers: AI-assisted engineers created **98% more PRs**, but **Time-to-Review for AI PRs rose 91%**, leaving overall delivery velocity flat. No framework captures this natively.
- **Model routing effectiveness.** Whether cheap-model tasks stay on the cheap model without cascading retries. Every multi-model setup needs this; no tool exposes it.
- **Agent self-correction metrics.** Retries per successful task, loop detection, "sample until finished" step counts (Anthropic's SWE-bench scaffolding pattern).
- **Sustained-focus duration.** Anthropic reports Sonnet 4.5 sustaining 30+ hours; Rakuten ran Opus 4 for 7 hours. No schema exposes this as a column.
- **Context-loading latency.** How long the agent spends on codebase search, MCP reads, and prompt assembly before producing the first token. A massive hidden infrastructure tax.
- **Autonomous (silent) rework.** When an agent writes code, runs tests, fails, and rewrites three times before presenting a single "success" to the user, traditional systems record this as one flawless action.

### How the three-method model breaks for agents and what replaces each method


| DX method                     | Team / human-developer regime           | Agent / solo regime                                                                                                                                                                                 | What replaces it                                                                                                                                                                                                                 |
| ----------------------------- | --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Telemetry** (tool-based)    | IDE plugins, PR data, vendor admin APIs | **Still works** — but the instrumentation burden shifts to the user, because no vendor owns the orchestrator they built. This is why a Python decorator + context manager is the right abstraction. | `runs` / `tasks` / `costs` auto-populated by decorator wrap                                                                                                                                                                      |
| **Periodic surveys** (Likert) | Quarterly SPACE items from devs         | **Breaks.** Can't ask an agent how satisfied it is. Surveys of the solo operator about their agent fleet still work but measure the operator's experience, not the agents'.                         | Replaced by **eval scores** (`tasks.score_value` from LLM-as-judge) and **post-hoc run review** (`runs.goal_achieved`, `runs.goal_quality_score`)                                                                                |
| **ESM** (in-flow prompts)     | Prompt the dev at PR submit             | **Breaks.** Can't prompt an agent mid-run. The "flow" is watching agents, not coding.                                                                                                               | Replaced by **intervention events** — each human takeover is itself an ESM-equivalent signal because it carries wait-time, edit distance, and reason. Every intervention row is a data point about the operator's attention cost |


**The core reframe**: for agent work, the `interventions` table IS the experience sampling channel. Every HITL event is a spontaneous self-report of dissatisfaction with autonomous operation. You don't need scheduled prompts — the agent triggers them by failing.

### The illusion of velocity — the strongest empirical input

The single most important empirical finding for positioning this framework is the **METR (Measuring Early-2025 AI on Experienced OSS Devs)** RCT on 16 experienced open-source developers:

- Developers using AI took **19% longer** to complete tasks than the control group.
- The same developers **perceived themselves to be 20% faster**.
- Gap: ~39 points between "vibe" and wall-clock reality.
- METR has announced a revised experiment design for 2026, but the 2025 result stands.

This is the strongest evidence that self-reported AI productivity is broken and that any framework relying on perceptual velocity alone will mislead its user. The bottleneck has shifted from typing code (historically 25–35% of SDLC per Orosz et al.) to **reviewing and verifying** it. AI-generated code also shows documented quality issues:

- CodeRabbit's analysis of GitHub PRs: **AI-authored code contains 1.7× more logic/correctness errors** than human-written code; **security flaws appear at 1.5–2× normal rate**.
- MSR 2026 study on Cursor: short-term velocity increases, but **code complexity and static-analysis warnings increase substantially and persistently**, driving long-term velocity slowdowns.
- DORA 2024/2025 formally added **rework rate** to acknowledge this instability.

### Specific agent metrics with formulas (tied to tables)


| Metric                             | Formula                                                                                                                              | Tables               | Cost                    |
| ---------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------ | -------------------- | ----------------------- |
| Autonomy score (run)               | `1 − (COUNT(interventions WHERE is_autonomous=0) / COUNT(tasks WHERE type IN ('agent_step','tool_call')))`                           | interventions, tasks | C                       |
| Autonomy score (severity-weighted) | `1 − Σ(severity_weight) / COUNT(tasks)`, weights 0.2/0.5/1.0                                                                         | interventions, tasks | E (severity labeling)   |
| Intervention rate per hour         | `COUNT(interventions) / (SUM(runs.duration_ms)/3.6e6)`                                                                               | interventions, runs  | C                       |
| Cost per completed task            | `SUM(costs.cost_usd) / COUNT(tasks WHERE status='success' AND accepted=1)`                                                           | costs, tasks         | C (auto) + E (accepted) |
| Fully-loaded cost per task         | Include `human_minutes × $hourly/60` rows                                                                                            | costs, tasks         | C                       |
| Tokens per completed task          | `SUM(costs.quantity WHERE category='llm_tokens') / COUNT(tasks WHERE accepted=1)`                                                    | costs, tasks         | C                       |
| Rework rate (DORA-style, agent)    | `COUNT(interventions WHERE rework_flag=1) / COUNT(tasks WHERE accepted=1)`                                                           | interventions, tasks | E                       |
| Self-correction rate               | `SUM(tasks.retry_count) / COUNT(tasks)`                                                                                              | tasks                | C                       |
| Successful retry rate              | `COUNT(tasks WHERE was_retry_of IS NOT NULL AND status='success') / COUNT(tasks WHERE retry_count>0)`                                | tasks                | C                       |
| Time-to-review p50/p95             | `percentile(interventions.wait_ms WHERE kind='approval')`                                                                            | interventions        | C                       |
| Edit magnitude                     | `AVG(interventions.edit_distance)`                                                                                                   | interventions        | C                       |
| Model routing effectiveness        | `SUM(cost_usd) / COUNT(tasks WHERE accepted=1) GROUP BY model`                                                                       | costs, tasks         | C                       |
| Cache hit ratio                    | `SUM(quantity WHERE cache_hit=1) / SUM(quantity WHERE category='llm_tokens')`                                                        | costs                | C                       |
| Sustained-focus duration           | `MAX(runs.duration_ms WHERE status='success' AND kind='agent_orchestrator')`                                                         | runs                 | C                       |
| Ask-F1 (HiL-Bench analog)          | Harmonic mean of ask-precision (`interventions(trigger='policy',outcome='approved')/interventions(trigger='policy')`) and ask-recall | interventions        | E                       |
| Context-loading ratio              | `AVG(tasks.context_load_ms / tasks.duration_ms)`                                                                                     | tasks                | C                       |
| Autonomous rework rate             | `COUNT(interventions WHERE is_autonomous=1) / COUNT(tasks)`                                                                          | interventions, tasks | C                       |


### Where sources disagree on the agent regime (key for positioning)

- **DX vs DORA 2024 on AI's sign.** DX: customer gains 16–41%. DORA 2024: −1.5% throughput, −7.2% stability per 25% AI adoption. DORA 2025 flipped throughput positive in mature orgs; stability stayed negative. METR: −19% for experienced devs. **Resolution:** sign depends on platform maturity and whether you measure local task time or end-to-end delivery. Your framework, by separating `tasks.duration_ms` (local) from `runs.duration_ms` and rework via `interventions.rework_flag`, can show both at once.
- **Acceptance rate: Ziegler 2022 vs DX 2024.** Ziegler found acceptance rate "drives developers' perception of productivity." DX now writes "acceptance rate is unreliable" because accepted code gets rewritten. **Action:** don't store bare acceptance rate; store accept-then-persist by pairing `tasks.accepted` with `interventions.rework_flag` over a rolling window.
- **Juniors vs seniors benefit.** Peng 2022 and Cui 2024: juniors gain more from autocomplete. Cursor 2025 (Sarkar): seniors gain more from agents (+6% acceptance per SD of experience). Anthropic Economic Index Feb 2026: seasoned users (6+ months) show **~10% higher success rate** and auto-approve actions **>40% of the time** vs new users. **Action:** `config_json` on `runs` should capture task complexity and user tenure; slice accordingly.
- **METR's 19% slowdown vs perceived 20% speedup.** The 39-point perception gap is the strongest single evidence that self-reported AI productivity is broken. **Action:** always pair `runs.perceived_productivity` (ESM Likert) with `runs.duration_ms` minus a baseline. A `runs.baseline_duration_ms_estimate` field (optional E) or `pre_task_estimated_min` lets you compute the gap per run.
- **Benchmark saturation vs SWE-ABS.** Anthropic Opus 4.7 reports 87.6% on SWE-bench Verified; SWE-ABS (Mar 2026) shows ~20% of "solved" patches are semantically wrong (top agent drops 78.8% → 62.2%). **Action:** for `eval` runs, store both raw and hardened scores as separate `tasks.score_value` rows with different `scorer_name`.
- **Are we shipping faster or just coding faster?** Orosz and others: AI optimizes coding (~25–35% of SDLC); verification overhead has grown to compensate. Faros data supports this (98% more PRs, +91% review time, flat delivery). **Action:** never publish task-time metrics without pairing them with review-time and rework metrics.

### Replacement table — traditional metric → agentic equivalent


| Traditional (DORA/SPACE)   | Agent-driven equivalent   | Primary diagnostic value                                             |
| -------------------------- | ------------------------- | -------------------------------------------------------------------- |
| Build time / CI-CD latency | Intervention Rate         | Human friction and agent capability failure in real time             |
| Deployment frequency       | Agent Autonomy Score      | % of workflow safely delegated without human oversight               |
| Change Failure Rate        | Agent-Induced Rework Rate | Hidden tax of correcting AI hallucinations and bugs                  |
| Diffs per Engineer / LOC   | Cost-Per-Task Efficiency  | Economic utility of model routing and token spend                    |
| Lead Time for Changes      | Time-to-Review (AI Code)  | Verification bottleneck and cognitive load of reading generated code |


---

## Section 4 — Positioning: what's under-measured

The market is saturated with enterprise tools (LinearB, Swarmia, Waydev) optimizing human teams in rigid corporate hierarchies — Jira velocity, PR comments, DORA deployment markers for exec anxiety dashboards. **There is a vacuum for measuring the symbiotic, cybernetic workflow of a solo developer orchestrating a localized swarm of AI agents.**

The framework must stake its claim in that vacuum. To command a flagship launch narrative ("here's what the industry isn't measuring"), the shortlist below is the positioning core. None of these appear in SPACE, DORA, DX Core 4, McKinsey, Fowler's DevEx, or any vendor dashboard surveyed.

### 1. Vibe Calibration Score — perceived vs actual velocity (`runs`)

**Why it matters.** METR's 39-point gap between perceived and actual speedup is the single strongest empirical result in 2025 on AI productivity. No framework tracks it at the task level. A personal framework that records *both* self-reported and measured speedup per run, per run-class, is uniquely positioned to publish the real curve — and to proactively surface when the user should drop the agent and write the code manually.

**How.** Delta between `runs.pre_task_estimated_min` (decorator ESM, captured at start) and `runs.duration_ms` (context manager telemetry). Plus `runs.perceived_productivity` (1–7 Likert at run end) normalized against a z-score within the same `kind`+`project` cohort.

**Fields.** `runs.pre_task_estimated_min` (E), `runs.perceived_productivity` (E), `runs.duration_ms` (C), optional `runs.baseline_duration_ms_estimate` (E).

### 2. Micro-Intervention Density — the true cost of autonomy (`interventions`)

**Why it matters.** Traditional tools measure macroscopic failures (broken build, reverted PR). They miss microscopic friction — every time the developer interrupts an agent's terminal stream, manually edits a file immediately after the agent modifies it, or hits Ctrl+C. A workflow that "completed successfully" but required 14 manual prompt corrections and 3 stream interruptions is not an autonomous success — it's a high-friction cognitive burden. Anthropic discusses interventions-per-session but nobody weights by severity or distinguishes a cosmetic edit from a full rewrite.

**How.** Two layers:

- **Density**: `COUNT(interventions WHERE kind IN ('stream_interrupt','immediate_post_edit','clarification','manual_override')) / runs.duration_ms` per run.
- **Severity-weighted autonomy**: `1 − Σ(severity_weight × intervention_count) / COUNT(tasks)` with weights 0.2 / 0.5 / 1.0 for low/medium/high.

**Fields.** `interventions.kind` (C), `interventions.severity` (E), `tasks.type` (C).

### 3. Context-Loading Latency — the MCP Friction Tax (`tasks`)

**Why it matters.** The industry obsesses over tokens-per-second (TPS). But the true bottleneck in sophisticated agentic engineering is **context accumulation**: how long does the agent spend searching the codebase, reading external docs via MCP servers, and formatting the prompt before producing the first output token? If you spend $0.50 on tokens just for the agent to read repo state before a 2-line change, the architecture is failing. No legacy dashboard exposes this.

**How.** Ratio of `tasks.context_load_ms` to `tasks.generation_ms` (or to `tasks.ttft_ms` when instrumenting streaming). Aggregate by `attribution_route` to identify the routes with the worst indexing or system-prompt bloat.

**Fields.** `tasks.context_load_ms` (C), `tasks.generation_ms` (C), `tasks.ttft_ms` (C), `costs.attribution_route` (C).

### 4. Token-Cost-to-Value Yield — combating tokenmaxxing (`costs`, `tasks`, `interventions`)

**Why it matters.** As AI usage becomes linked to enterprise performance reviews, developers are gaming the system by maximizing token consumption — the "tokenmaxxing" trend sweeping Silicon Valley. Langfuse gives cost per trace; nobody divides by tasks that actually shipped and weren't reverted. The economic question the solo operator needs answered: *"Did I spend $2.00 on Opus for a task that Haiku could have resolved for $0.02 with the same intervention rate?"*

**How.** Rework-adjusted cost per accepted task, sliced by model:

```
SUM(costs.cost_usd) /
COUNT(tasks WHERE accepted=1 AND task_id NOT IN
  (SELECT task_id FROM interventions WHERE rework_flag=1
   AND detected_at < accepted_at + 14 days))
GROUP BY tasks.model
```

Compare same task types across models for matched intervention rates. This is GitClear's churn concept applied at task granularity, extended across a model routing matrix. Pairs with metric #6 (model routing leakage) for diagnostic completeness.

**Fields.** `tasks.accepted` (E), `interventions.rework_flag` (E), `costs.cost_usd` (C), `tasks.model` (C).

### 5. Autonomous Rework Rate — the silent loop (`interventions`, `tasks`)

**Why it matters.** When a background agent writes code, runs tests, fails, and rewrites three times before presenting a "success," traditional systems record one flawless action. Even if the visible human intervention rate looks low, high autonomous rework signals agent brittleness with the codebase — wasted compute, subtle logic flaws likely to escape into production. This is one of the cleanest positioning metrics because **no current tool surfaces it**.

**How.** `COUNT(interventions WHERE is_autonomous=1) / COUNT(tasks)`. Instrument by hooking the agent's internal retry loop and writing `interventions` rows with `is_autonomous=1` for each silent recovery.

**Fields.** `interventions.is_autonomous` (C), `tasks` counts (C).

### 6. Model Routing Leakage (`tasks`, `costs`)

**Why it matters.** Multi-model setups (cheap first, escalate on failure) are ubiquitous in 2025; nobody measures how often the cheap model fails silently and the user shrugs instead of re-running on the expensive model. Complements metric #4 — #4 answers "am I overspending?"; this answers "am I underspending and absorbing the cost as my own attention?"

**How.** For tasks with `retry_count > 0` where the retry used a different model: compare `tasks.accepted` rate on cheap vs expensive for matched task types. Leakage = tasks that should have escalated but didn't (low acceptance on cheap, never retried).

**Fields.** `tasks.model` (C), `tasks.retry_count` (C), `tasks.was_retry_of` (C), `tasks.accepted` (E).

### 7. Attention Cost per Run (`interventions` × `runs`)

**Why it matters.** Vendors report cost in dollars and tokens. For a solo operator, the scarce resource is **attention**, not dollars. A run that cost $0.40 but demanded 22 minutes of interruption is more expensive than a $4 run that completed autonomously.

**How.** `SUM(interventions.response_ms + interventions.wait_ms) / COUNT(runs)`. Pair with `runs.duration_ms` for attention-load ratio: what fraction of wall time required you.

**Fields.** `interventions.response_ms`, `interventions.wait_ms`, `runs.duration_ms`.

### 8. Structure-vs-Behavior Change Ratio (`interventions`)

**Why it matters.** Beck's distinction between tidying and feature work is almost never instrumented. For a solo operator, knowing what fraction of your interventions with agents are structural (refactors the agent didn't do right) vs behavioral (feature bugs) tells you where agent scaffolding is weakest.

**How.** `COUNT(interventions WHERE change_class='structure') / COUNT(interventions WHERE change_class IN ('structure','behavior'))`.

**Fields.** `interventions.change_class` (E, tagged post-hoc — cheap enough if done the same day).

### 9. Agent Sustained-Focus Curve (`runs`)

**Why it matters.** Anthropic markets "30h sustained focus" as a capability; no framework shows the *decay curve* — success rate as a function of run duration. This is the inverse of the marketing claim and the truthful version.

**How.** Bucket runs by `duration_ms` deciles, plot `goal_achieved` rate per bucket.

**Fields.** `runs.duration_ms` (C), `runs.goal_achieved` (E).

### 10. Cache-Hit Attribution by Route (`costs`)

**Why it matters.** Anthropic prompt caching and OpenAI cached reads price 10–90% less. Nobody surfaces which of your agent routes (triage, research, refactor) benefit and which are cache-busting. Direct dollar-optimization signal hiding in plain sight.

**How.** `SUM(costs.quantity WHERE cache_hit=1) / SUM(costs.quantity) GROUP BY attribution_route`.

**Fields.** `costs.cache_hit` (C), `costs.attribution_route` (C).

### 11. Time-to-First-Intervention (`interventions`, `runs`)

**Why it matters.** If interventions tend to happen early, the agent is badly scoped; if late, the agent ran too long unsupervised. Distribution shape is a different signal from raw rate.

**How.** `MIN(interventions.detected_at − runs.started_at) per run`; plot distribution.

**Fields.** `interventions.detected_at` (C), `runs.started_at` (C).

### 12. Cost per Hour of Attention Saved (`costs` × ESM)

**Why it matters.** The DX "AI dollar impact" is aggregate and vendor-oriented. The solo operator's real question: am I spending API dollars to save my own hours, and at what exchange rate?

**How.** `SUM(costs.cost_usd) / (SUM(runs.ai_time_saved_min)/60)`. If the ratio exceeds your hourly rate, you're losing money on that route; keep. If below, scale that route.

**Fields.** `costs.cost_usd` (C), `runs.ai_time_saved_min` (E, one Likert + estimate at run end).

### Positioning claim, in one breath

By staking the above 12 metrics — several of them unique to this framework — the Personal OS transcends the legacy canon. It provides the industry's first native vocabulary for the realities of solo, agent-driven software development, proving that while AI makes code generation trivial, **measuring the true cognitive and economic cost of hybrid workflows is the ultimate engineering challenge of 2026**.

---

## Recommended schema (SQLite DDL)

```sql
PRAGMA user_version = 1;
PRAGMA journal_mode = WAL;

CREATE TABLE runs (
    run_id          TEXT PRIMARY KEY,           -- UUIDv7
    parent_run_id   TEXT REFERENCES runs(run_id),
    session_id     TEXT,
    kind            TEXT NOT NULL,              -- agent_orchestrator|content_pipeline|ml_training|eval|survey|manual_task
    name            TEXT NOT NULL,
    entry_point     TEXT,                       -- decorator|context_manager
    project         TEXT NOT NULL,
    git_sha         TEXT,
    code_version    TEXT,
    env             TEXT,
    config_json     TEXT,
    tags_json       TEXT,
    status          TEXT NOT NULL,              -- running|success|error|aborted|timeout
    error_type      TEXT,
    error_message   TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     INTEGER,
    input_summary   TEXT,
    output_summary  TEXT,
    total_tokens    INTEGER,
    total_cost_usd  REAL,
    num_llm_calls   INTEGER,
    num_tool_calls  INTEGER,
    num_interventions INTEGER,
    goal_achieved   INTEGER,                    -- 0|1|NULL (E)
    goal_quality_score REAL,                    -- 1-5 (E)
    satisfaction_score INTEGER,                 -- 1-7 Likert (E)
    flow_state      INTEGER,                    -- 1-7 (E)
    perceived_productivity INTEGER,             -- 1-7 Likert (E)
    ai_time_saved_min INTEGER,                  -- (E)
    pre_task_estimated_min INTEGER,             -- (E) Vibe Calibration
    baseline_duration_ms_estimate INTEGER,      -- (E) perception-reality delta
    notes           TEXT
);
CREATE INDEX idx_runs_started ON runs(started_at);
CREATE INDEX idx_runs_project_started ON runs(project, started_at);
CREATE INDEX idx_runs_kind_status ON runs(kind, status);
CREATE INDEX idx_runs_session ON runs(session_id);

CREATE TABLE tasks (
    task_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    parent_task_id  TEXT REFERENCES tasks(task_id),
    type            TEXT NOT NULL,              -- llm_call|tool_call|agent_step|retrieval|pipeline_stage|train_step|eval_sample|human_review
    name            TEXT NOT NULL,
    status          TEXT NOT NULL,
    error_type      TEXT,
    started_at      TEXT NOT NULL,
    ended_at        TEXT,
    duration_ms     INTEGER,
    ttft_ms         INTEGER,
    context_load_ms INTEGER,                    -- MCP Friction Tax
    generation_ms   INTEGER,                    -- MCP Friction Tax
    model           TEXT,
    provider        TEXT,
    operation       TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    reasoning_tokens INTEGER,
    cached_tokens   INTEGER,
    tool_name       TEXT,
    tool_call_id    TEXT,
    finish_reason   TEXT,
    retry_count     INTEGER DEFAULT 0,
    was_retry_of    TEXT REFERENCES tasks(task_id),
    input_ref       TEXT,
    output_ref      TEXT,
    input_preview   TEXT,
    output_preview  TEXT,
    temperature     REAL,
    max_tokens_req  INTEGER,
    metadata_json   TEXT,
    score_value     REAL,                       -- (E)
    score_label     TEXT,                       -- (E)
    scorer_name     TEXT,                       -- (E)
    accepted        INTEGER,                    -- 0|1 (E)
    task_type_self_report TEXT,                 -- Meyer taxonomy (E)
    perceived_difficulty INTEGER                -- 1-7 (E)
);
CREATE INDEX idx_tasks_run_started ON tasks(run_id, started_at);
CREATE INDEX idx_tasks_type ON tasks(type);
CREATE INDEX idx_tasks_model ON tasks(model);
CREATE INDEX idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX idx_tasks_status ON tasks(status);

CREATE TABLE interventions (
    intervention_id TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    task_id         TEXT REFERENCES tasks(task_id),
    kind            TEXT NOT NULL,              -- approval|rejection|edit|abort|retry_triggered|clarification|manual_override|feedback|tool_denied|rollback|esm_prompt|stream_interrupt|immediate_post_edit
    trigger         TEXT NOT NULL,              -- policy|user_initiated|confidence_gate|error_recovery|schedule|timeout
    detected_at     TEXT NOT NULL,
    responded_at    TEXT,
    wait_ms         INTEGER,
    response_ms     INTEGER,
    outcome         TEXT NOT NULL,              -- approved|approved_with_edits|rejected|ignored|timed_out
    actor           TEXT NOT NULL,
    severity        TEXT,                       -- low|medium|high (E)
    reason          TEXT,                       -- (E)
    edit_distance   INTEGER,
    edit_ref        TEXT,
    tokens_before   INTEGER,
    tokens_after    INTEGER,
    rework_flag     INTEGER DEFAULT 0,          -- (E)
    change_class    TEXT,                       -- behavior|structure|mixed|n/a (E), Beck-style
    is_autonomous   INTEGER DEFAULT 0,          -- silent-loop flag (C)
    confidence_at_trigger REAL,
    metadata_json   TEXT
);
CREATE INDEX idx_interventions_run_detected ON interventions(run_id, detected_at);
CREATE INDEX idx_interventions_task ON interventions(task_id);
CREATE INDEX idx_interventions_kind ON interventions(kind);
CREATE INDEX idx_interventions_trigger ON interventions(trigger);
CREATE INDEX idx_interventions_autonomous ON interventions(is_autonomous);

CREATE TABLE costs (
    cost_id         TEXT PRIMARY KEY,
    run_id          TEXT NOT NULL REFERENCES runs(run_id),
    task_id         TEXT REFERENCES tasks(task_id),
    ts              TEXT NOT NULL,
    category        TEXT NOT NULL,              -- llm_tokens|tool_api|compute_gpu|compute_cpu|storage|human_minutes|egress|third_party
    subcategory     TEXT,                       -- prompt|completion|reasoning|cached_read|cached_write|batch|search|browser|code_exec
    provider        TEXT,
    model           TEXT,
    quantity        REAL NOT NULL,
    unit            TEXT NOT NULL,              -- tokens|seconds|calls|minutes|bytes
    unit_price_usd  REAL,
    cost_usd        REAL NOT NULL,
    pricing_version TEXT,
    attribution_user TEXT,
    attribution_project TEXT,
    attribution_route TEXT,
    cache_hit       INTEGER,
    metadata_json   TEXT
);
CREATE INDEX idx_costs_run ON costs(run_id);
CREATE INDEX idx_costs_task ON costs(task_id);
CREATE INDEX idx_costs_ts ON costs(ts);
CREATE INDEX idx_costs_category_model ON costs(category, model);
CREATE INDEX idx_costs_user_ts ON costs(attribution_user, ts);
```

**Design notes.** UUIDv7 PKs (not autoincrement, not UUIDv4) for merge-safety and btree locality. WAL mode for concurrent reads during agent runs. All post-hoc E fields are nullable so the decorator writes immediately on exit and E fields fill in later via CLI. `metadata_json` on every table as the escape hatch so you don't migrate on every new vendor attribute. Column names on `tasks` align with OpenTelemetry GenAI semantic conventions for future interop with Datadog/Traceloop/Braintrust exporters.

---

## Top 10 to instrument first (under 5 hours/week)

Ranked by (positioning value × cheapness), the instrumentation sequence:

1. **Decorator + context manager writing `runs` rows with timing and status.** Zero-cost capture; everything else depends on this. ~30 min.
2. **LLM client wrapper emitting `costs` rows per call with tokens + $ + cache_hit.** Wrap `anthropic.Anthropic` and `openai.OpenAI` once; never think about it again. Covers Token-Cost-to-Value, Attention Cost, Cache-Hit Attribution, Cost-per-Hour-Saved. ~1 hr.
3. `**tasks` auto-capture for LLM and tool calls from the same wrapper**, with `context_load_ms` / `generation_ms` split. Hooks into step 2. Covers self-correction, model routing, MCP Friction Tax. ~45 min.
4. **Run-end ESM prompt (CLI)** writing `perceived_productivity` + `goal_achieved` + `pre_task_estimated_min` + optional `notes` to `runs`. Single `pos close <run_id>` command, 3 Likert items. Unlocks Vibe Calibration the moment you have enough runs. ~30 min.
5. **Manual `interventions` row via `pos intervene` CLI** with `kind`, `trigger`, `wait_ms`, `outcome`. The single metric that unlocks Section 3's entire agent story. Start with just these five fields; add `severity`/`rework_flag`/`change_class`/`is_autonomous` as tagging rituals settle. ~45 min.
6. **Denormalized rollups on `runs`** (`total_tokens`, `total_cost_usd`, `num_interventions`): trigger on run close. Keeps dashboards snappy on SQLite. ~20 min.
7. `**attribution_route` tagging at decoration time.** Pass one string per decorator invocation; enables cache-hit-by-route, cost-by-route, context-load-by-route analyses. ~15 min incremental.
8. **Git SHA + code version capture.** Subprocess `git rev-parse` at decorator enter. Enables longitudinal analysis across framework changes. ~15 min.
9. `**tasks.accepted` via CLI `pos accept <task_id>` or post-commit hook.** Enables rework-adjusted cost and acceptance-then-persist logic. ~30 min.
10. **Weekly rollup script writing survey-style aggregates as `runs` with `kind='survey'`.** One SQL file run by cron. Gives you the time series you'll actually publish. ~1 hr.

Total: ~6 hours one-time. Weekly overhead after: ~15 min of CLI tagging, plus whatever time you spend looking at your own data (which is the point).

**Explicitly deferred (don't build until you have 100+ runs):** severity weighting on interventions, edit-distance computation, baseline duration estimation, strengthened-test evaluation in `tasks`, physiological sensors, automated task-switch detection. These are Meyer-lineage research-grade; they pay off only at scale.

---

## Explicit disagreement flags

A working list for your own records, sorted by how much they affect schema decisions:

1. **Does AI help or hurt delivery?** DX: yes (16–41% customer gains). DORA 2024: no (−1.5% throughput, −7.2% stability). DORA 2025: yes for throughput in mature orgs, no for stability. METR: −19% for experienced devs, with a 39-point perception gap. Faros: 98% more PRs, +91% review time, flat overall delivery. **Schema implication:** always pair local `tasks.duration_ms` with run-level `runs.duration_ms` and `interventions.rework_flag`. Refuse to commit to a single sign.
2. **Is acceptance rate meaningful?** Ziegler 2022: yes (predicts perceived productivity). DX 2024+, Tacho 2025: no (accepted code gets reverted). CodeRabbit: AI-authored code 1.7× more error-prone; MSR 2026 Cursor paper: long-term complexity increases persistently. **Implication:** don't store bare acceptance rate; pair `tasks.accepted` + `interventions.rework_flag` and derive persistence-adjusted versions on query.
3. **Individual measurement: acceptable or harmful?** McKinsey: yes. SPACE: with strong caveats. Tacho: no, except for manager-of-managers. Beck + Orosz: McKinsey is "absurdly naive." **Implication:** for n=1 self-measurement the ethical objection doesn't apply — but Goodhart does. Don't set personal targets on `diffs/day` or intervention rate; track them as leading indicators. Publish levels, not rankings.
4. **Does SPACE agree with DORA on what matters?** SPACE covers satisfaction + collaboration; DORA originally didn't. DORA 2025 imported SPACE's spirit via human-factor blending in archetypes. **Implication:** the schema supports both — DORA's 4 keys fall out of `runs` timing + `interventions.rework_flag` + failure counts; SPACE satisfaction/flow fall out of ESM fields on `runs`.
5. **Who benefits more — juniors or seniors?** Peng/Cui: juniors gain more from autocomplete. Cursor 2025 (Sarkar): seniors gain more from agents (+6% acceptance per SD of experience). Anthropic Economic Index Feb 2026: seasoned users (6+ mo tenure) get ~10% higher success rate and auto-approve >40% of actions. **Implication:** `config_json` on `runs` should capture task complexity class and user tenure; slice by both.
6. **Benchmark inflation.** Anthropic Opus 4.7 reports 87.6% on SWE-bench Verified; SWE-ABS (Mar 2026) shows ~20% of solves are semantically wrong (top agent drops 78.8% → 62.2%). **Implication:** for `eval` runs, always store multiple `tasks.score_value` rows with different `scorer_name` — raw benchmark, hardened benchmark, human judgment.
7. **Dashboards vs SLOs vs raw events.** Majors: dashboards are "a poor view"; SLOs are the real API. Larson: synthetic metrics from event traces beat pre-aggregated dashboards. SPACE/DORA/DX: dashboards all day. **Implication:** store events (rows), not aggregates. Derive views on query. This is already the design.
8. **Is "developer productivity" even the right term?** Fowler/Noda: use "developer experience" instead. Tacho: uses the word pragmatically. **Implication:** framing only. For the flagship post, use "measurement" or "instrumentation" and avoid "productivity" except in dimensional contexts (e.g., "perceived productivity" as a Likert construct).
9. **Operations-centric vs human-centric schools.** McKinsey-style tracks individual backlog contributions algorithmically. Tacho/Fowler/DX rely on qualitative surveys and team-level outcome measurement. **Implication:** your framework lives in the operations-capable lane (rich telemetry), but the published narrative should sit in the human-centric one — publish per-run experience and gaps, not per-developer scorecards.

---

## Conclusion — the positioning in one sentence each

The canon converges on multi-method measurement and balanced metrics at the team level, but it splinters on individual measurement and breaks outright when the developer becomes an agent. The three-method model (telemetry + surveys + ESM) maps to the `runs`/`tasks`/`costs` telemetry channel cleanly, maps to periodic surveys awkwardly (needs a 5th table or a repurposed `runs.kind='survey'`), and doesn't map to ESM for agents at all — interventions replace ESM in the agent regime. The under-measured territory is concrete and defensible: Vibe Calibration, Micro-Intervention Density, Context-Loading Latency (MCP Friction Tax), Token-Cost-to-Value Yield, Autonomous Rework Rate, Model Routing Leakage, Attention Cost, Structure-vs-Behavior, Sustained-Focus Decay, Cache-Hit by Route, Time-to-First-Intervention, Cost per Hour of Attention Saved. A 4-table schema with UUIDv7 keys, OpenTelemetry-aligned column names, and post-hoc-nullable experiential fields can capture all of them within one weekend of implementation and ~15 min/week of tagging discipline — enough to publish a series, not just a framework.
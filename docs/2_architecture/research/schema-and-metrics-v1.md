# plumb — System Design

> **Scope.** Canonical schema, metric derivation, and design principles for
> plumb v1. The product framing (problem, audiences, non-goals, success
> metrics) lives in `[../../1_product/PRD.md](../../1_product/PRD.md)`. The upstream
> literature synthesis lives in
> `[./measurement-framework-research.md](./measurement-framework-research.md)`.
> This document is the authoritative reference for what plumb measures, how,
> and why each metric earned a column.

## Problem statement and scope

The Personal OS is a multi-agent system: an orchestrator dispatches specialized sub-agents (content pipeline, GNN-based SLO recommender, finance ingestion, others) and every component logs into a single measurement framework that will be published as a flagship portfolio artifact. The framework must serve three audiences — DevEx teams (fast regression gates), AI/ML teams (model-swap experiments with statistical rigor), and agentic-systems teams (production trace forensics) — without becoming three frameworks. The operational constraint is a four-table SQLite schema for the v1 release, so the prescriptive core must be ruthless about what earns a column.

Three framing decisions drive everything below. **First, a multi-agent system fails in ways single-agent systems cannot**: Cemri et al.'s MAST taxonomy (arXiv:2503.13657, March 2025) found that across 1,600+ traces from seven frameworks, roughly 42% of failures were specification/design issues (bad decomposition, duplicated agents, missing termination), 37% were inter-agent misalignment (context collapse, withheld information, reasoning-action mismatch), and 21% were verification/termination failures — none of which a single-agent metric catches. **Second, "offline" and "online" are not two frameworks but one dataflow**: production traces feed regression sets, regression wins validate in production, and a well-designed schema makes the loop cheap. The industry consensus — visible in Braintrust's dataset reconciliation, LangSmith's trace-to-dataset workflow, Galileo's continuous promotion — has moved decisively away from static golden datasets toward this circulation model. **Third, trajectory evaluation is now the default, not the exception**: every major production vendor (LangSmith, Arize, Braintrust, Galileo, Patronus, Humanloop) argues final-answer scoring is inadequate for agents; what matters is the sequence of tool calls, handoffs, and intermediate states. Patronus's TRAIL benchmark reports frontier models score under 11% on trace-level reasoning tasks, suggesting trajectory eval is where the real reliability signal lives.

The framework below is organized as a **prescriptive spine** (what everyone should build for v1) plus **optional extensions** (what to layer on as the system matures). Spine items are mandatory for the portfolio release; extensions are explicitly marked as future work.

---

## The four-table schema: principles before columns

Before naming metrics, fix the schema shape, because the shape determines what metrics are expressible. Four tables, unified across offline and online:

1. `**runs`** — One row per execution unit, whether that unit is an offline eval row or a production trace. Fields: `run_id`, `kind` ∈ {offline, online}, `task_id`, `parent_run_id` (nullable, for sub-agent runs), `orchestrator_model`, `sub_agent_model`, `prompt_version`, `tool_schema_version`, `git_sha`, `start_ts`, `end_ts`, `tokens_in`, `tokens_out`, `dollar_cost`, `status` ∈ {success, failure, aborted, stalled}. The critical move is **unifying offline and online in one table** — this is what every major vendor has converged on (Braintrust's Eval() uses identical row schema for experiments and logs; OpenTelemetry GenAI semantic conventions push vendor-neutral naming precisely so this unification is possible).
2. `**spans`** — One row per step inside a run: tool call, sub-agent invocation, LLM call, handoff. Fields: `span_id`, `run_id`, `parent_span_id`, `kind` ∈ {llm, tool, subagent, handoff, plan, verify}, `name`, `input_hash`, `output_hash`, `tokens`, `latency_ms`, `status`, `error_type`. Hashing input and output (not storing them in the main row) enables cheap loop detection and deduplication without PII bloat; full content lives in a blob store referenced by hash. The span tree captures orchestrator-specific structure: routing decisions are spans of kind `subagent`, handoffs are spans of kind `handoff`, planning steps are spans of kind `plan`.
3. `**scores`** — One row per metric-on-run-or-span observation. Fields: `score_id`, `run_id`, `span_id` (nullable — for trace-level metrics), `metric_name`, `scorer` ∈ {deterministic, judge, human, user_signal}, `scorer_version`, `value_numeric`, `value_label`, `scored_at`. This is the load-bearing table. It makes judge scores, user thumbs-down signals, deterministic checks, and human annotations structurally identical — a convergent principle across LangSmith, Braintrust, Humanloop, and Patronus. The `scorer_version` field is what lets you detect judge drift later without corrupting historical comparisons.
4. `**examples`** — The regression dataset table. Fields: `example_id`, `task_id`, `inputs_hash`, `expected_output_hash`, `rubric`, `source` ∈ {synthetic, production_promotion, human_authored}, `origin_run_id` (nullable — points back to the production trace a case was promoted from), `active` (bool), `created_at`. The `origin_run_id` field is what enables bidirectional offline↔online flow — a production failure becomes a test case that remembers where it came from, and when a regression run fails that example, you can trace back to the original user session.

Four tables, three foreign-key relationships (`spans.run_id`, `scores.run_id`, `examples.origin_run_id`), one bidirectional lineage link. Everything else — dashboards, alerts, model-swap reports, failure clusters — is a query over this shape. **The schema itself is the framework's thesis**: if you can't express it in these four tables, it probably isn't a load-bearing metric.

---

## Core metric taxonomy: must-have versus nice-to-have

The literature generates a long menu of agent metrics. The v1 cut below is informed by what each metric costs to compute, what failure modes it actually catches, and how cleanly it fits the four-table schema. Must-have metrics are the ones that, if absent, leave a category of failure invisible. Nice-to-have metrics enrich diagnosis but can be deferred.

### Must-have: the black-box layer

**Task completion** as a binary per-run outcome is non-negotiable. Every major benchmark and every major vendor treats this as the anchoring metric. Binary, not scalar: Hamel Husain and Shreya Shankar's practitioner consensus — "Replace subjective scales with binary pass/fail on scoped criteria; Likert scales hide ambiguity" — is reinforced by Zheng et al.'s MT-Bench findings (arXiv:2306.05685) that pairwise and binary judgments exhibit lower variance than Likert. The dissent (see Best-Practice Recommendations below) matters only in narrow cases. **End-to-end latency** and **dollar cost** (tokens in/out × price + tool API fees) are captured at the `runs` level. **Intervention rate** — fraction of runs where a human had to step in — is distinctive for multi-agent systems because the orchestrator is often the intervention point; log it as a `scorer=user_signal` score.

### Must-have: the glass-box layer

**Tool call validity** — did the call match the schema? — is a Tier-1 deterministic check, runnable on 100% of traces for near-zero cost. **Tool argument hallucination** (arguments reference entities not present in context) is either a deterministic check (entity extraction against context) or a cheap judge. **Routing quality** — did the orchestrator delegate to the correct sub-agent? — is the single most important orchestrator-specific metric, and Hu et al.'s RouterBench (arXiv:2403.12031) establishes the evaluation pattern: top-1 routing accuracy against a labeled judge set, plus cost-adjusted accuracy (cost-to-match-strongest-model). For the Personal OS, a held-out set of ~200 tasks with annotated correct-sub-agent labels gives a usable v1 signal. **Handoff quality** — measured as a round-trip QA probe: can the parent agent, using only the sub-agent's returned summary, answer a factual question that was in the sub-agent's context? — this operationalizes the "context dump fallacy" work (XTrace, 2025; arXiv:2510.00326 defines a Context Preservation Score as embedding similarity across handoff).

### Must-have: reliability

**pass^k** (task success on *all* k repeated attempts), introduced by Yao et al. in τ-bench (arXiv:2406.12045), is the most underused metric in production eval. GPT-4o dropped from 61% pass@1 to 25% pass@8 on τ-bench retail — exposing a reliability gap that pass@1 hides entirely. For a portfolio artifact, pass^3 or pass^5 on a small hard subset is a differentiated signal; most frameworks still report only pass@1.

### Nice-to-have (defer or mark as extension)

**Memory quality** and **context-window utilization** are worth measuring but diagnostic rather than gating. **Sub-agent coordination metrics** — duplicate-call rate, per-agent contribution share — are in MAST but hard to annotate without human labels. **Plan-vs-execution attribution** is powerful but requires either a counterfactual re-run (stronger executor on the same plan) or a dedicated LLM-judge; ship it in v1.1. **Failure propagation / cascade depth** matters for multi-hop orchestrator graphs but the Personal OS's shallower tree makes it lower-priority. **Communication overhead** (tokens per resolved task, handoff-brief length) is easy to compute and worth including because Anthropic's multi-agent research system found token usage alone explained 80% of performance variance on BrowseComp — this is content-worthy even if it's not gating.

### The v1 metric cut

For the portfolio release, a defensible v1 set is: **task completion (binary), end-to-end latency, dollar cost, tokens-per-resolved-task, tool call validity, tool argument hallucination, routing top-1 accuracy, handoff round-trip accuracy, intervention rate, pass^3 on a reliability subset**. Ten metrics, all computable from the four-table schema, all covering a distinct failure mode. Everything else is an extension.

---

## The offline spine: shipping a change

The offline workflow is the one that answers "how does agent performance change when I swap models?" — the model-swap experiment. It requires a regression set, a way to execute candidate and baseline against it, and statistical machinery strong enough that the resulting LinkedIn post cites real error bars instead of vibes.

### Golden dataset design for multi-agent systems

A golden example for a multi-agent system is not an input-output pair. It is a tuple of (task input, expected terminal state, optional expected trajectory anchors, rubric). Expected terminal state is what τ-bench grades against — a database-state comparison rather than a string match — and this is the right default: **grade terminal state, not trajectory shape**, because multiple valid trajectories can reach the same outcome. Trajectory anchors enter as optional milestone checks (did the agent invoke a search tool before a synthesis tool?) graded with an LLM-judge, not as exact-match requirements. Rubrics should decompose into binary sub-checks (factuality, tone, completeness) rather than a single Likert score, following the Husain/Shankar consensus.

Size requires a real computation, not a rule of thumb. Miller's Anthropic paper (arXiv:2411.00640) and Cameron Wolfe's walkthrough (cameronrwolfe.substack.com/p/stats-llm-evals) give the formula: for a paired binary comparison at baseline p=0.6, 5pp minimum detectable effect, α=0.05, power=0.8, the required N is roughly 300–600 tasks; for 2pp MDE, 2,000–4,000. The Personal OS probably can't reach 2pp-MDE scale in v1, so state the MDE you can afford and stop pretending otherwise. **For v1: target 200 tasks total, accept ~5–7pp MDE, and be explicit about it in the published framework.** This is more credible than claiming higher precision than the sample supports.

### Building the regression set from production traces

The dominant industry pattern is the annotation-queue pipeline: capture trace → auto-flag (low judge score / high latency / user thumbs-down) or manual flag → SME adds expected output → promote to dataset → run in CI on every change. LangSmith, Braintrust, Humanloop, and Patronus all implement variants of this; it is now the default. Metadata that must travel with the promoted case: prompt version, model ID, tool schema version, full span tree, token counts per step, user segment, retrieved context, feedback signals, git SHA. The `examples.origin_run_id` field in the schema above is what preserves the audit trail.

### Statistical rigor applied to trajectories

Anthropic's four recommendations (paired differences, clustered standard errors, resampling to reduce variance, power-aware sample sizes) all extend to agents, but the key extension is **the unit of analysis**. Task is the default unit. Trace is the unit when multiple tasks share a session (cluster SE on session_id). Step-level metrics (tool-call validity rate) require trace-clustered SE or they are anti-conservative — naive SE can be 3× too small, per Anthropic's own reading-comp example. For model-swap experiments, pair candidate and baseline on identical task inputs and use McNemar's test for binary outcomes; Arawjo's evalstats library (github.com/ianarawjo/evalstats) implements this plus smoothed bootstrap for scalar metrics.

**Variance decomposition** is the agent-specific insight worth publishing. Agent variance decomposes into model stochasticity (reducible by averaging K samples, variance ∝ 1/K), tool non-determinism (irreducible by more samples — requires mocked/cached tools), environment variance (only observable across time), and task difficulty (eliminated by pairing). The prescribed recipe: **run two eval regimes**. (1) Capability eval with live tools — measures total variance, reflects reality, reported in absolute numbers. (2) Regression eval with replayed/mocked tools — measures model stochasticity alone, high statistical power, used for model-swap ship decisions. Only compare models with (2); report absolute quality with (1). This is a clean framing that hasn't been codified elsewhere.

**Multiple comparisons correction**: when tracking ten metrics across five user segments you run 50 tests. Benjamini-Hochberg FDR is the practitioner default (Statsig, evalstats) and appropriate for metric sweeps; use Holm-Bonferroni for a small set of pre-registered confirmatory hypotheses (the actual ship decision). Pre-register primary versus exploratory metrics — this is the honest version of the LinkedIn-friendly graph.

---

## The online spine: knowing what's breaking in production

The online workflow answers "what's actually breaking?" without presuming ground truth. Four elements: tiered sampling, no-ground-truth regression signals, failure clustering, and the trace-to-test-case closing loop.

### Tiered evaluation architecture

Nearly every agent observability vendor — Arize, Braintrust, LangSmith, Humanloop, Galileo, Patronus — has converged on three tiers. **Tier 1 (100% coverage, deterministic)**: regex, JSON schema validation, tool-call validity, PII detectors, safety classifiers, length checks. Runs inline, near-zero cost. **Tier 2 (10–20% sampled, LLM-as-judge)**: pointwise reference-free scoring on faithfulness, tool-selection appropriateness, routing quality, handoff fidelity. Braintrust suggests 1–10% for high-volume apps, 50–100% for critical low-volume apps. Galileo's Luna-2 small-LM evaluators (reported sub-200ms, ~$0.02/M tokens) represent a newer approach that pushes Tier 2 toward 100% coverage at SLM cost — plausibly the direction v2 goes. **Tier 3 (1–5% routed, human)**: annotation queue for SME labels, pairwise preference, novel-failure discovery, judge calibration. The gating discipline: traffic routes into Tier 3 via filter (low judge score, high latency, user thumbs-down), not random sampling.

**Sampling strategy for the 10–20%**: a layered design — deterministic 100% capture for errors and safety violations (never sample those out), stratified random ~5% for representative quality baseline, importance-weighted capture for anomalies (low confidence, long latency, retries, user negative feedback). This mirrors distributed-tracing best practice (Datadog head sampling augmented with tail sampling for anomalies) adapted to agents.

### Regression detection without ground truth

Four complementary signals, alerted on conjunction rather than individually:

1. **Reference-free judge signals** — faithfulness, instruction-following, tool validity — tracked as time series. A drop is a candidate regression signal.
2. **Drift detection on three distributions** — input embedding distribution (KS test on reduced-dim embeddings; AWS Prescriptive Guidance recommends reducing before KS rather than testing raw high-dim), output judge-score distribution (PSI or KL), and tool-call distribution (frequency shifts, argument-type shifts).
3. **User-behavior proxies** — retry rate, session abandonment, handoff-to-human rate, task-completion-time — well-correlated with ground-truth quality when it is measured.
4. **Scheduled golden-trace replay** — rerun a fixed canonical trace set daily against current production. The Digital Applied 2026 observability guide argues this is the single most reliable early-warning signal and I agree; it's essentially the offline regression set repurposed as a health probe.

### Failure clustering

Two complementary methods. **Embedding-based clustering**: summarize each failed trace, embed the summary (not raw JSON — too noisy with volatile tokens), reduce with UMAP, cluster with HDBSCAN. PostHog documented this exact pipeline in 2025 and Arize Phoenix ships it natively. **LLM-induced taxonomization**: have an LLM read a sample of failed traces and induce a failure taxonomy (MAST did this and got Cohen's κ=0.88 between human annotators), then classify the rest with a judge. The taxonomy is human-readable; the embedding clusters catch novelty. Track cluster mass over time as a regression signal — a cluster that was 2% last week and is 15% this week is probably a new bug.

### Closing the loop

This is the schema's most elegant property. A production failure flagged in Tier 3 becomes an `examples` row with `source='production_promotion'` and `origin_run_id` pointing to the original trace. When the next regression run fails that example, a query joins back to the origin run, which surfaces the MAST-category, cluster ID, user segment, model version that first exhibited the bug. The bidirectional link is one foreign key — but it is the thing that makes offline and online feel like one framework instead of two.

---

## Orchestrator-specific dimensions that don't exist for single agents

Five dimensions are categorically different for multi-agent systems. All five appear in the research but only the first two belong in v1.

**Routing quality** (v1, already discussed). RouterBench/RouteLLM methodology applied to a 200-task labeled set.

**Sub-agent coordination** (v1 diagnostic). Duplicate-tool-call rate — hash (tool_name, args) and fire when the same hash recurs across sub-agents — is trivially computable from the `spans` table. This catches the MAST "duplicated agents" failure mode (one of the most common specification failures) without human labels.

**Communication overhead** (extension, but publishable). Anthropic's multi-agent research system post (June 2025, anthropic.com/engineering/built-multi-agent-research-system) reports multi-agent consumes ~15× the tokens of a chat turn and that token usage explained 80% of performance variance on BrowseComp. The derived metrics — tokens-per-resolved-task, handoff-brief length, post-handoff QA-probe accuracy — are easy to compute from spans and make unusually good content because they put a price tag on orchestration.

**Failure propagation** (extension). Cascade depth (number of downstream sub-agents whose output was corrupted by an upstream error), recovery rate (fraction of runs where the orchestrator recovered after a detected sub-agent error), and MTTR-equivalent (median orchestrator steps from error signal to recovery). Tool-MVR (Ma et al., 2025) reports an Error Correction Rate of 58.9% — useful as an external baseline.

**Plan-vs-execution attribution** (extension, v1.1). The operational recipe is elegant: when a trajectory fails, re-run the execution phase with the same plan but a stronger model as executor. If it succeeds, it was an execution failure; if not, a plan failure. SWE-EVO (arXiv:2512.18470) observes stronger models fail predominantly on plan-side (instruction-following), weaker models on execution-side (tool use, syntax). This counterfactual attribution is cheap and interpretable and should be in v1.1.

---

## Long-running agents: evaluating a 200-step trace

Multi-hour runs break the default eval model. The research offers four reusable patterns, all appropriate as extensions (not v1 spine).

**Progress-toward-goal via annotated subgoals**. AgentBoard (Ma et al., NeurIPS 2024) is the canonical source: pre-annotate subgoals per task, define a monotone progress rate r ∈ [0,1] as `max_k f(state, subgoal_k)` where f is a regex/state-matcher or LLM-judge, and track progress over the trace. This turns a single binary into a continuous curve that shows where the agent stalls. SUPER (EMNLP 2024) does the same with "landmarks." For the Personal OS, subgoal annotation is a one-time cost per task type, amortized across many runs.

**Anchor-point hybrid**. Milestone-based (cheap, interpretable, requires annotation) plus continuous error-flag overlay (invalid action, repeated action, context overflow). This produces one monotone progress curve plus an event log — readable and statistically clean.

**Sampling strategy for long traces**: a three-way triple-sample — uniform random for unbiased error-rate estimates, error-triggered windows for highest signal-per-token, milestone-triggered entering/leaving each subgoal. Importance-weighted sampling is research-grade only.

**Loop and stagnation detection**. Four detectors, all implementable as simple queries over the `spans` table: exact-action repetition (hash of tool+args recurs N times), oscillation (A-B-A-B pattern in last 4 spans), same-result recurrence (output hash recurs), no-progress window (subgoal rate unchanged over K steps). Paired with a hard step/token budget, these catch the vast majority of real stalls. The "Ralph Wiggum Loop" and dev.to "220 Loops" writeups document these patterns in production. MAST's FM-3.3 ("premature termination") is the complementary failure — the agent gives up too early — which is why both a budget and a progress metric are needed.

**Checkpointing as measured dimension**. Gemini Deep Research explicitly reports this as a design constraint ("a single failure shouldn't restart the whole process"). Measurable: resumability success rate after injected mid-run kill, checkpoint size in bytes per step, cost-to-recover ratio (tokens from checkpoint to completion ÷ tokens from scratch), tool-call idempotency rate. This is probably v2 territory but is differentiated portfolio content because almost no one publishes these numbers.

---

## Skill evaluation: two metrics, then stop

Anthropic's Agent Skills blog (anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills, Dec 2025, with a Skill-Creator 2.0 update March 2026) explicitly positions evaluation as the starting point: run the parent agent on representative tasks, observe gaps, build a skill. Skill-Creator 2.0 added scored tests with ~20 synthetic prompts per skill (half positive, half negative) to measure whether the skill **triggers** correctly. The two metrics worth capturing for v1 — everything else is explicitly future:

1. **Skill triggering accuracy**: on the ~20-prompt test set per skill, does the right skill load for the positive half and stay dormant for the negative half? Reported as F1 across the labeled set. This is the metric Anthropic themselves optimize against.
2. **Skill outcome quality**: conditional on the skill having triggered, did the task completion rate improve versus a no-skill baseline? Paired design: same task, skill-on versus skill-off, compared via McNemar.

Two metrics, two rows of the `scores` table. Full skill lifecycle evaluation (skill decay, skill conflict, skill-of-skills composition) is future work.

---

## Where research converges, where it splits

**Convergent positions** (ship the consensus in v1):

- **Binary scoring for ship decisions**. Hamel Husain, Shreya Shankar, Zheng et al. (MT-Bench). Decompose into multiple binary sub-checks rather than a single Likert.
- **Pairwise > pointwise for judges, but both need position-swap mitigation**. Shi et al. "Judging the Judges" (arXiv:2406.07791) confirmed position bias is not random and varies by judge; order-swap and consensus aggregation are required.
- **Paired differences for model-swap experiments**. Anthropic paper; replicated by evalstats and Braintrust.
- **Task is the statistical unit by default; cluster SE when tasks nest in sessions**.
- **OpenTelemetry GenAI conventions for span naming**, so traces are portable across vendors.
- **Trace-to-dataset promotion is the right replacement for static golden sets**.
- **Three-tier sampling (100% deterministic / 10–20% judge / 1–5% human)**.
- **Krippendorff's α with matched distance function is the right judge-reliability metric**; benchmark against human-human α on the same data. The "Judge's Verdict" paper (arXiv:2510.09738) reports human-human κ=0.801 as an empirical baseline, but that's dataset-specific — reproduce on your own data before using as a threshold.

**Live splits** (flag, don't decide):

- **Head versus tail sampling** for production traces. Tail is better for root-cause, costlier; head simpler, scalable.
- **LLM judge coverage**: 10–20% with frontier models, approaching 100% with small-LM judges (Galileo Luna-2). Unresolved whether SLM judges hold quality at scale.
- **Binary dissent for ordinal-ground-truth tasks**: Godfrey et al. "Likert or Not" (arXiv:2505.19334, May 2025) show fine-grained ordinal pointwise scoring closes the gap with listwise ranking for information retrieval. Medical/regulated domains also require risk tiers. The rule: binary for ship decisions; ordinal when the ground truth itself is ordinal.
- **Benchmarks versus custom environments**. Cognition (SWE-1.5) argues SWE-bench's distribution is too narrow; Patronus (TRAIL) and Microsoft (AutoGenBench) still champion public benchmarks. For the Personal OS, custom environments plus one public benchmark (τ-bench for reliability) is the pragmatic mix.
- **Runtime guardrails versus after-the-fact eval**. Galileo and Patronus ship runtime blocking; Braintrust explicitly doesn't. This is a philosophy split, not a research result.

---

## The research anchors: primary sources worth following up

For the portfolio release, these are the citations that carry weight:

**Foundational (already in user's synthesis)**: Miller, "Adding Error Bars to Evals" (Anthropic, arXiv:2411.00640); Booking.com AI Trip Planner posts; Eugene Yan's eval writing; LangChain tooling.

**Orchestrator and failure taxonomies**: Cemri et al., MAST (arXiv:2503.13657, 2025); Zhu et al., MultiAgentBench/MARBLE (arXiv:2503.01935); Anthropic, "How we built our multi-agent research system" (June 2025, anthropic.com/engineering/built-multi-agent-research-system).

**Benchmarks**: Yao et al., τ-bench (arXiv:2406.12045); Mialon et al., GAIA (arXiv:2311.12983); Jimenez et al., SWE-bench (arXiv:2310.06770) and OpenAI's SWE-bench Verified curation; Liu et al., AgentBench (arXiv:2308.03688); Zhou et al., WebArena (arXiv:2307.13854); Xie et al., OSWorld (arXiv:2404.07972); Kapoor et al., HAL (arXiv:2510.11977); Wei et al., BrowseComp (arXiv:2504.12516); Chan et al., MLE-bench (arXiv:2410.07095).

**Routing and tool selection**: Ong et al., RouteLLM (arXiv:2406.18665); Hu et al., RouterBench (arXiv:2403.12031); Zhang et al., TRAJECT-Bench (arXiv:2510.04550); Microsoft, AppSelectBench (arXiv:2511.19957).

**Planning and long-horizon**: Valmeekam et al., PlanBench (arXiv:2206.10498) and "LLMs Still Can't Plan" (arXiv:2409.13373); Ma et al., AgentBoard (NeurIPS 2024); Kwa & West et al., METR Time Horizon (arXiv:2503.14499, March 2025, metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/); Scale, SWE-bench Pro (arXiv:2509.16941); Cognition, SWE-1.5 (cognition.ai/blog/swe-1-5, Oct 2025); Google, Gemini Deep Research (gemini.google/overview/deep-research/).

**Judges**: Zheng et al., "Judging LLM-as-a-Judge" (arXiv:2306.05685); Liu et al., G-Eval (arXiv:2303.16634); Kim et al., Prometheus 2 (arXiv:2405.01535); Shi et al., "Judging the Judges" (arXiv:2406.07791); "Judge's Verdict" (arXiv:2510.09738); "Rating Roulette" (ACL Findings EMNLP 2025); Godfrey et al., "Likert or Not" (arXiv:2505.19334).

**Industry eval**: Arize (arize.com/ai-agents/agent-observability/); Braintrust (braintrust.dev/articles/ai-agent-evaluation-framework); Galileo (galileo.ai/blog/four-new-agent-evaluation-metrics, Oct 2025); Patronus TRAIL and Percival (patronus.ai/blog/introducing-generative-simulators); LangSmith (docs.langchain.com/langsmith/evaluate-graph); Microsoft AutoGenBench; Anthropic Agent Skills (anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills); Humanloop Flows.

**Statistics**: Miller (above); Arawjo's evalstats (github.com/ianarawjo/evalstats); Cameron Wolfe's synthesis (cameronrwolfe.substack.com/p/stats-llm-evals); Benjamini & Hochberg 1995; Krippendorff 2011; "An Empirical Study of LLM-as-a-Judge" (arXiv:2506.13639).

---

## Prioritized roadmap

**v1 (ship for portfolio launch)**: four-table schema; ten-metric core (task completion, latency, cost, tokens-per-task, tool validity, argument hallucination, routing top-1, handoff round-trip, intervention rate, pass^3); offline spine with 200-task regression set, McNemar paired comparison, BH-FDR correction; online spine with three-tier sampling, four reference-free regression signals, HDBSCAN embedding-cluster failure discovery, annotation-queue trace-to-example workflow; skill triggering and outcome metrics.

**v1.1 (the portfolio's next update)**: plan-versus-execution attribution via stronger-executor counterfactual; MAST-style 14-mode LLM-judge failure tagging; variance decomposition reports (capability-eval vs regression-eval split); judge calibration against human-human α baseline.

**v2 (marked as future)**: long-running agent extension (subgoal annotation, loop detection, checkpointing metrics); communication-overhead analysis with token-per-task efficiency frontier; full skill lifecycle (decay, conflict, composition); Pareto-frontier router evaluation; Luna-2-style SLM judges at 100% coverage.

---

## What's worth publishing on LinkedIn

Five angles from this research that are novel or counterintuitive enough to anchor build-journal content, ranked by contrarian value:

**"pass^k is the metric everyone's ignoring."** GPT-4o drops from 61% pass@1 to 25% pass^8 on τ-bench. If you only report pass@1 — and almost everyone does — you are hiding the reliability story. A short post showing Personal OS pass^k curves across sub-agents, framed as "the reliability gap that pass@1 hides," is directly contrarian to mainstream benchmark reporting and gives the portfolio a defensible analytical stance. (Source: Yao et al., arXiv:2406.12045.)

**"Token usage explained 80% of multi-agent performance variance."** Anthropic's own multi-agent research system post contains this line but it hasn't been widely circulated. Multi-agent costs ~15× the tokens of a chat turn — which reframes orchestration as an efficiency problem, not just a capability one. A post titled "your multi-agent system is not smarter, it is more expensive" lands well because it inverts the dominant narrative. Tie it to Personal OS's tokens-per-resolved-task metric and show the actual Pareto frontier.

**"Run two eval regimes, not one."** The capability-eval (live tools, measures reality) versus regression-eval (replayed tools, measures model alone) split is methodologically clean and not codified elsewhere. This is the kind of framing that DevEx and AI/ML teams both steal, which makes it portfolio-grade. Present it as a one-diagram explainer.

**"The four-table schema is the framework."** A schema-first post is a format AI/ML teams rarely write. Walk through the bidirectional offline↔online lineage via `examples.origin_run_id`, explain why traces and experiments live in the same `runs` table (Braintrust's move), and show how the whole framework is really queries over these four tables. This lands because it reframes eval as a data-modeling problem — which it is, but almost no one describes it that way.

**"Production-failure-to-regression-test is a foreign key."** A narrower riff on the schema post: specifically the single foreign-key link that closes the loop between production forensics and offline regression. Frame it against the tired "golden dataset" metaphor — static datasets are dead, circulating datasets are alive, and the whole difference is one nullable column. Cite Braintrust's dataset reconciliation and LangSmith's trace-to-dataset as convergent industry evidence.

Two honorable mentions that could be second-tier posts: the **MAST 42/37/21 failure breakdown** (specification/misalignment/verification) as a diagnostic lens for any multi-agent system a DevEx team runs across, and the **binary-over-Likert consensus** with the Godfrey et al. dissent — a short post on "when to break the binary rule" carves out a thoughtful position without picking a fight with the consensus.

## Conclusion: a framework, not a checklist

The strongest thread through the 2024–2026 literature is that multi-agent evaluation has stopped being an extension of single-agent evaluation and started being its own discipline. Three specific shifts make this concrete. Trajectory has replaced final-answer as the default evaluation object. Production traces have replaced static golden sets as the primary dataset source. And the statistical unit is now the task, not the prompt, with clustered standard errors when tasks nest in sessions. Everything in the prescriptive spine above is an operationalization of those three shifts inside a four-table schema.

The novel contribution of the Personal OS framework — what makes it worth publishing — is not any individual metric. It is the insistence that one schema, ten metrics, and two workflows can serve DevEx teams (who need fast regression gates), AI/ML teams (who need statistical rigor for model swaps), and agentic-systems teams (who need production forensics) simultaneously. The research supports this: the vendors have already converged on unified schemas, trajectory evaluation, and the three-tier sampling pattern. What has not yet been codified is a prescriptive spine with explicit must-haves, explicit extensions, and a four-table constraint that forces the hard decisions. That's the artifact worth shipping.
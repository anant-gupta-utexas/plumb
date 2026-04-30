# plumb — Deferred features & decisions backlog

> **Purpose.** A single file to track options considered but not shipped in plumb v1, plus features explicitly deferred by the PRD to v1.1 / v2. Future-you reads this to decide what to pick up next without redoing the TRD planning round.
>
> **Scope.** Entries fall into two groups: (A) **design-time decisions** captured during the TRD planning round (2026-04-23) where alternatives were considered and one path was picked; (B) **PRD-deferred features** (v1.1 / v2) that are known-good ideas the PRD explicitly did NOT ship in v1.
>
> **Format.** Every entry uses the same template so diffs are easy to scan:
>
> ```
> ## [Title]
> - Decision: shipped in v1 | deferred to v1.1 | deferred to v2 | not doing
> - Date: YYYY-MM-DD
> - Context: [one sentence: what problem was this solving?]
> - Options considered: [each with one-line pros/cons]
> - Rationale for current pick: [one sentence]
> - Revisit trigger: [what would cause us to re-open this?]
> ```
>
> **Adding entries.** Append a new section at the bottom of the relevant group. Never silently remove or edit historical entries — supersede with a new dated entry and update the old one's Decision line (e.g., `~~deferred to v1.1~~ → shipped in v1.2, see entry dated 2026-08-01`).

---

## Group A — Design-time decisions (TRD planning round, 2026-04-23)

### Deliverable shape: library-only vs library + local service

- **Decision:** shipped in v1 — library + localhost-only FastAPI read service.
- **Date:** 2026-04-23
- **Context:** The PRD says "no custom dashboard" but users still want to query the SQLite file from notebooks / ad-hoc scripts. The TRD had to decide whether the v1 deliverable is *just* a pip-installable package or a package + a thin read-only HTTP service bound to 127.0.0.1.
- **Options considered:**
  - *Library-only* — smallest surface; pushes read access onto user code; matches "no SaaS" most strictly. Pro: minimum maintenance burden. Con: every user has to write their own query harness.
  - **Library + local read service (chosen)** — thin `plumb serve` command that exposes `GET /runs`, `GET /stats/task/{id}`, etc. Pro: unblocks notebook workflows without drawing a dashboard; 127.0.0.1-only keeps the "no SaaS" spirit. Con: extra `fastapi`/`uvicorn` dependencies; a second public surface to test.
  - *Library + local service + auto-generated dashboard* — full web UI. Con: directly contradicts PRD §7 non-goal.
- **Rationale for current pick:** The read service is small (≈100 LOC), covers the "I just want to look at my runs" use case, and respects the PRD non-goal by being read-only and loopback-bound. Avoids forcing every user to reinvent the same five `SELECT` queries.
- **Revisit trigger:** If the HTTP service's test/maintenance burden exceeds ~10% of total plumb effort, reconsider dropping it and publishing a minimal `plumb-queries` SQL recipe file instead.

### Architecture framing: strict Clean Architecture vs ports-and-adapters vs flat

- **Decision:** shipped in v1 — **ports-and-adapters** (hexagonal).
- **Date:** 2026-04-23
- **Context:** The workspace rule in `CLAUDE.md` mandates `domain/application/infrastructure` folders for all projects. plumb is a small library (≈2–3k LOC projected) with two public entry points; strict three-layer CA would roughly double per-feature boilerplate without improving the seams that matter.
- **Options considered:**
  - *Strict Clean Architecture (literal CLAUDE.md)* — `Run`/`Span` entities in `domain/`; `OpenRun`/`CloseRun`/`PromoteExample` use-case classes in `application/`; SQLite writer in `infrastructure/`. Pro: maximum layering rigor; matches CLAUDE.md word-for-word. Con: 2–3× boilerplate for v1's ten-metric scope; use-case-per-CLI-command pattern is ceremonial for a library.
  - **Ports-and-adapters (chosen)** — `plumb/core/` (entities + schema + ports), `plumb/adapters/` (sqlite, blob, judges, attach), thin façades in `plumb/api.py` / `plumb/cli.py` / `plumb/http.py`. Pro: preserves swappable seams (storage, judges, adapters) with minimal ceremony; how idiomatic Python libraries actually look (requests, httpx, pydantic all organize by capability). Con: deviates from CLAUDE.md's literal folder names.
  - *Flat package-by-feature* — `plumb/schema.py`, `plumb/api.py`, `plumb/cli.py`, etc., no architectural split. Pro: fastest to ship. Con: loses explicit seams; reviewers would have to reconstruct intent from module names.
  - *Defer the decision to the first TDS* — let implementation stress-test the layering before committing in the TRD. Pro: empirical. Con: the TRD would have an ambiguous §5 that reviewers can't sign off on.
- **Rationale for current pick:** plumb's load-bearing seams are the storage, the judge provider, and the adapter sources. Ports-and-adapters preserves exactly those seams with Protocols in `plumb/core/ports.py`; strict CA's extra use-case/DTO layer solves a problem plumb doesn't have. Deviation from CLAUDE.md is documented explicitly (TRD §5.3 Assumption 1) and needs user sign-off before the TRD is accepted.
- **Revisit trigger:** If a third public entry point ever emerges (the PRD forbids this, but v3 could change that), or if plumb gains an external driver that isn't the CLI/HTTP/Python-import trio — that's when the use-case layer of strict CA starts paying for itself.

### Judge adapters: one adapter (OpenAI-compatible) vs two vs pluggable extension point

- **Decision:** shipped in v1 — **two concrete adapters**: Anthropic native SDK + OpenAI-compatible chat-completions.
- **Date:** 2026-04-23
- **Context:** The PRD names "Sonnet as default with Opus for routing + handoff." That's Anthropic-centric, but users route models through Cursor or OpenRouter or local runtimes (Ollama, vLLM, LM Studio). The adapter layer has to be flexible without multiplying the test surface unboundedly.
- **Options considered:**
  - *One adapter (OpenAI-compatible only)* — covers OpenAI, OpenRouter, Ollama, vLLM, LM Studio via `base_url` config; Anthropic reachable via its OpenAI-compatible shim. Pro: minimal surface. Con: loses Anthropic-native features (prompt caching, tool-use block streaming, beta headers).
  - **Two adapters (chosen)** — Anthropic native SDK for first-class Sonnet/Opus with prompt caching + streaming; OpenAI-compatible for everything else. Pro: matches PRD's "Sonnet as default" literally while giving OpenRouter users a first-class path; prompt caching on stable judge prompts is a real cost lever. Con: doubles integration-test surface (both adapters need mocked response fixtures).
  - *Provider-agnostic from day one (Anthropic + OpenAI + local stub)* — maximum flexibility. Con: triples test surface; the "local stub" is really just mocked HTTP and doesn't need its own adapter class.
  - *One adapter + documented Protocol/ABC extension seam* — single OpenAI-compatible in core, publish a `JudgeAdapter` Protocol for third parties to implement for Bedrock / Vertex / corp gateways. Pro: future-proof. Con: we don't need this in v1 and external adapter plugins are hard to support.
- **Rationale for current pick:** The two-adapter choice reflects reality — Anthropic's native SDK has features worth accessing (caching especially, since judge prompts are nearly static) and the OpenAI-compatible adapter covers ~6 endpoints with one adapter. Config-driven selection (`PLUMB_JUDGE_PROVIDER`).
- **Revisit trigger:** If someone files an issue asking for Bedrock / Vertex AI native (not via an OpenAI-compatible gateway) support, at that point the Protocol/ABC extension seam becomes worth shipping.

### Performance budget: tight vs moderate vs measure-first

- **Decision:** shipped in v1 — **tight budget** (p95 ≤ 1 ms per span, ≤ 50 ms per run close).
- **Date:** 2026-04-23
- **Context:** plumb wraps production agent runs. Its own overhead must not dominate — but the budget has to be a number we can measure, not vibes.
- **Options considered:**
  - **Tight (chosen)** — 1 ms / 50 ms; WAL mode, batched writes, zero network on hot path. Pro: forces the right architecture from day one (no synchronous judge calls, no per-span fsync). Con: leaves little headroom if we misjudge.
  - *Moderate* — 5 ms / 200 ms. Pro: easier to hit; leaves headroom for ORM overhead if we end up using one. Con: too generous; a span that auto-captures an LLM call should not be a measurable fraction of the LLM call itself.
  - *Measure-first, no hard target in v1* — ship, measure for 2 weeks, set a budget in v1.1. Pro: empirical. Con: the first implementation's shape is the most expensive to change; setting the target late invites architecture drift.
- **Rationale for current pick:** Tight forces batched writes and no hot-path network calls, both of which are the right architecture anyway. The reference benchmark in `tests/perf/` makes the number enforceable.
- **Revisit trigger:** If real atlas instrumentation shows p95 > 1 ms after 2 weeks and the architecture is already clean (no low-hanging optimizations), relax to moderate (5 ms) and document the reason.

### Blob store: plain filesystem vs optional encryption vs cloud vs defer

- **Decision:** shipped in v1 — **plain filesystem, no encryption**.
- **Date:** 2026-04-23
- **Context:** `spans.input_hash` and `spans.output_hash` reference content that has to live somewhere. The PRD's "no SaaS, single-user SQLite file" non-goal rules out cloud storage. Question is whether to add optional encryption for users who share a laptop or sync their home directory.
- **Options considered:**
  - **Plain filesystem with `0600` file mode + `0700` dir mode (chosen)** — content-addressed sha256 keys, fan-out by first byte. Pro: simplest; single-user local posture matches the PRD. Con: content is readable by other local processes running as the same user.
  - *Filesystem + optional at-rest encryption behind a flag* — age / libsodium, off by default. Pro: opt-in safety for shared machines. Con: key management becomes a support vector; envelope encryption is easy to get wrong.
  - *Defer the blob store entirely to v1.1* — v1 stores hashes only; judges can't re-score old rows without the caller re-supplying content. Con: loses a PRD-implied capability (the schema already references `input_hash`/`output_hash`).
  - *Cloud blob store (S3-compatible)* — Con: directly contradicts PRD "no SaaS" non-goal.
- **Rationale for current pick:** Single-user local + user-controlled FileVault/LUKS/BitLocker is the right posture for v1. Users who sync their home folder across machines are already trusting their sync provider; plumb doesn't need to re-solve that problem.
- **Revisit trigger:** First user request for shared-team blob storage (which would itself contradict the PRD's single-user framing — worth questioning before shipping).

### Orchestrator / sub-agent model field: allowlist vs free-text

- **Decision:** shipped in v1 — **free-text string**.
- **Date:** 2026-04-23
- **Context:** `runs.orchestrator_model` and `runs.sub_agent_model` need to record what model the caller's agent used. Callers route through Cursor, OpenRouter, or direct vendor APIs; naming conventions vary.
- **Options considered:**
  - **Free-text string (chosen)** — caller supplies `"cursor/claude-sonnet-4.6"`, `"openrouter/qwen/qwen3-coder"`, `"openai/gpt-5"`, etc. plumb does not validate. Pro: zero maintenance; works with any provider today and any new provider tomorrow. Con: small cardinality sprawl in reports (user can fix with a normalization view).
  - *Allowlist enum* — plumb ships a list of recognized model identifiers and rejects others. Con: breaks the day a new model ships; adds a maintenance burden that doesn't exist in the PRD.
  - *Free-text + optional normalizer hook* — caller can register a callable that canonicalizes strings. Con: overbuild for v1.
- **Rationale for current pick:** plumb is a recorder, not a validator. Free-text matches the PRD non-goal of "not blocking" the caller and keeps the schema future-proof against model/provider churn.
- **Revisit trigger:** If a user asks for grouped analytics ("all Anthropic models vs all OpenAI") and the cardinality is unmanageable, add an optional `plumb.normalize` module (not a schema change).

### Decision-log shape: ADR folder vs single decisions file vs deferred-only

- **Decision:** shipped in v1 — **single `deferred-features.md` file** (this document).
- **Date:** 2026-04-23
- **Context:** User asked to track options considered and decisions made so features deferred now can be picked up later. Two industry patterns exist.
- **Options considered:**
  - *Proper ADR folder* (`docs/2_architecture/adr/0001-*.md`, one file per decision, immutable once accepted) — Michael Nygard's format. Pro: scales cleanly as project grows; easy to link individual decisions from PRs. Con: higher ceremony than a small project needs.
  - *Single `decisions.md` file* (chronological log of accepted decisions + rationale). Pro: low overhead; easy to grep. Con: loses the "here's what's still open" backlog part the user asked for.
  - **Single `deferred-features.md` with both accepted decisions and deferred options (chosen)** — one file, two groups (A: design decisions; B: PRD-deferred items). Pro: matches what the user asked for verbatim; zero ceremony; lowest cognitive overhead. Con: gets long as the project grows.
  - *Both a `decisions.md` AND a `deferred-features.md`* — cleanest separation. Con: two files to keep in sync.
- **Rationale for current pick:** User explicitly picked "deferred features only." Kept it minimal; if the file grows beyond a few hundred lines or we start linking individual decisions from PRs, we'll migrate to an ADR folder.
- **Revisit trigger:** File exceeds ~500 lines OR we want per-decision permalinks from commit messages / PR descriptions.

---

## Group B — PRD-deferred features (v1.1 / v2)

Entries below are features the PRD explicitly defers. They're recorded here so future-you can pick them up without re-reading PRD §4 / §6 / §7.

### v1.1 — Plan-vs-execution attribution

- **Decision:** deferred to v1.1
- **Date:** 2026-04-23 (recorded); PRD §4 sets the target window.
- **Context:** When a trajectory fails, was it the planner that hallucinated a bad step, or the executor that flubbed a clean plan? SWE-EVO (arXiv:2512.18470) shows stronger models fail predominantly on plan-side, weaker on execution-side. A cheap counterfactual recipe exists.
- **Options considered:**
  - *v1 inclusion* — Con: needs a second model judge per failed run; extra cost budget; complicates `plumb judge run`.
  - **v1.1 inclusion (chosen by PRD)** — operational recipe: re-run failed trajectories with the same plan but a stronger executor model; if it now succeeds → execution failure, else → plan failure.
- **Rationale for current pick:** PRD §4 explicitly marks plan-vs-execution as "v1.1 adds plan-vs-execution attribution." Keeps v1 to ten metrics.
- **Revisit trigger:** Phase 2 (Week 9 per PRD §8). Implementation notes: add `scores.metric_name='plan_failure'` and `'execution_failure'`; reuse the existing judge adapters with a different prompt.

### v1.1 — MAST 14-mode failure tagging

- **Decision:** deferred to v1.1
- **Date:** 2026-04-23 (recorded); PRD §4.
- **Context:** Cemri et al.'s MAST taxonomy (arXiv:2503.13657) classifies multi-agent failures into 14 modes across three categories. Having each failed run tagged with one or more MAST modes makes failure dashboards instantly meaningful.
- **Options considered:**
  - *v1 inclusion* — Con: requires a judge prompt per mode (or one long prompt); labeled dataset for prompt validation; extra dependency on the taxonomy's stability.
  - **v1.1 inclusion (chosen by PRD)** — LLM-judge that tags failed runs with one-or-more MAST modes; stored as `scores.metric_name='mast_mode'`, `value_label=<mode_id>`.
- **Rationale for current pick:** PRD §4 marks "v1.1 adds ... MAST-style 14-mode failure tagging."
- **Revisit trigger:** After v1 ships and we have ≥ 30 failed runs to validate the tagger against.

### v1.1 — Variance decomposition reports (capability-eval vs regression-eval split)

- **Decision:** deferred to v1.1 (implicit in PRD §8 Tier-1 "CI regression gate" maturing in Phase 2).
- **Date:** 2026-04-23
- **Context:** The schema-and-metrics research doc recommends running two eval regimes: (1) capability eval with live tools measures reality; (2) regression eval with replayed/mocked tools measures model stochasticity alone for model-swap decisions. Comparing models with (2), reporting absolute quality with (1).
- **Options considered:**
  - *v1 inclusion* — Con: needs a tool replay/mock layer; adds complexity before anyone has used v1.
  - **v1.1 inclusion (chosen)** — `plumb regression-eval` command that runs the regression dataset against a recorded tool transcript; capability-eval is the default.
- **Rationale for current pick:** v1's 200-task regression set is the foundation; the replay layer is additive.
- **Revisit trigger:** When model-swap cadence hits > 1 per month.

### v1.1 — Judge calibration against human-human α baseline

- **Decision:** deferred to v1.1
- **Date:** 2026-04-23
- **Context:** Krippendorff's α between judge and human is the right reliability metric; needs a small human-labeled held-out set. PRD §8 Tier-1 "Judge drift guard" is scaffold (version every row); the calibration run itself is v1.1.
- **Rationale for current pick:** Scaffold first (done in v1 via `scorer_version`), measure second (v1.1), act third (v2 calibration-aware judges).
- **Revisit trigger:** Phase 2 (Week 9 per PRD §8).

### v2 — Long-running agent extension

- **Decision:** deferred to v2
- **Date:** 2026-04-23
- **Context:** Multi-hour agent runs need subgoal annotation, loop / oscillation / stagnation detection, and checkpointing metrics (AgentBoard, SUPER, Gemini Deep Research). PRD §7 explicitly excludes.
- **Options considered:**
  - *v1 inclusion* — Con: the PRD's current atlas components are short-lived; no dogfooding signal yet.
  - **v2 (chosen by PRD)** — add `subgoals` metadata column (would be a schema change), plus loop-detection queries over `spans`.
- **Rationale for current pick:** PRD §7: "Not every failure mode. Skipping: ... long-running-agent subgoal annotation (v2), checkpointing metrics (v2)."
- **Revisit trigger:** First atlas component exceeds 30-minute single-run duration.

### v2 — Communication overhead / tokens-per-resolved-task efficiency frontier

- **Decision:** deferred to v2 (partial — tokens-per-resolved-task IS in the v1 ten-metric cut; the *efficiency frontier analysis* is v2)
- **Date:** 2026-04-23
- **Context:** Anthropic's multi-agent research system reports token usage explained 80% of performance variance on BrowseComp. A Pareto frontier of "tokens per resolved task vs success rate" makes this visible. PRD §4 marks "Communication overhead (v2)."
- **Options considered:**
  - *v1 inclusion (metric only)* — tokens-per-resolved-task IS shipped (item 4 of the ten).
  - **v2 for the frontier analysis (chosen by PRD)** — adds a `plumb report efficiency-frontier` that plots tokens-per-task × pass-rate.
- **Rationale for current pick:** Metric is cheap (sum spans.tokens / count successful runs); the analysis is the content, and content is a v2 deliverable.
- **Revisit trigger:** Any time the flagship post needs an efficiency-frontier chart.

### v2 — Luna-2-style SLM judges at 100% coverage

- **Decision:** deferred to v2
- **Date:** 2026-04-23
- **Context:** Galileo's Luna-2 shows small-LM judges at ~200 ms + ~$0.02/M tokens, enabling 100% judge coverage instead of 10–20% sampled. Research doc flags this as "where v2 probably goes."
- **Options considered:**
  - *v1 inclusion* — Con: no production-ready small-LM judge exists in the Anthropic SDK; Luna-2 is Galileo-hosted.
  - **v2 (chosen)** — add a third adapter class `plumb.adapters.judge_slm.SLMJudge` backed by a local Ollama / vLLM run of a small model (e.g., Llama 3.3 8B) or a Galileo endpoint.
- **Rationale for current pick:** v1's ports-and-adapters seam supports this addition without any schema change.
- **Revisit trigger:** When a cost audit shows judge spend > ~$10/week.

### v2 — Full skill lifecycle metrics (decay, conflict, composition)

- **Decision:** deferred to v2
- **Date:** 2026-04-23
- **Context:** Anthropic's Skill-Creator 2.0 (March 2026) evaluates skill *triggering* (F1 on ~20-prompt test set) and skill *outcome quality* (paired with/without). Skill decay over time, skill-vs-skill conflict resolution, and skill-of-skills composition are larger open problems.
- **Options considered:**
  - *v1 inclusion (two metrics only)* — triggering + outcome. These fit the `scores` table as `metric_name='skill_trigger_f1'` and `metric_name='skill_outcome_delta'`; no schema change needed. Shipped in v1.
  - **v2 for the full lifecycle (chosen by PRD)** — decay (does skill F1 drift over 4 weeks?), conflict (when two skills could both apply, which wins?), composition (skills-that-call-skills).
- **Rationale for current pick:** The v1 two-metric subset catches the most common failure mode (skill doesn't load); the lifecycle work requires more data than Phase 1 generates.
- **Revisit trigger:** When the first user ships their second skill.

### v2 — Pareto-frontier router evaluation (RouteLLM-style)

- **Decision:** deferred to v2
- **Date:** 2026-04-23
- **Context:** Hu et al. RouterBench + Ong et al. RouteLLM evaluate routers along cost-vs-accuracy Pareto frontiers. v1's routing-top-1 accuracy (item 7 of the ten) is a point estimate; the frontier is the richer analysis.
- **Options considered:**
  - *v1 inclusion (metric only)* — routing top-1 IS shipped.
  - **v2 for the frontier (chosen)** — add `plumb report router-frontier` that plots cost × accuracy for each candidate routing policy.
- **Rationale for current pick:** Routing top-1 catches regressions; the frontier is for experiments, which is a v2 content need.
- **Revisit trigger:** First routing policy A/B test.

### Agentic-CLI-backed judge adapter (ClaudeCodeJudge / CodexCLIJudge)

- **Decision:** not doing in v1; open as a v2+ possibility via the Protocol/ABC extension seam (which is itself a deferred item — see "Judge adapters" in Group A).
- **Date:** 2026-04-23
- **Context:** Users who live inside Claude Code or Codex CLI (or Cursor's agent) often ask, "can plumb judge my traces using the same tool I'm coding with?" The natural instinct is a subprocess adapter: `claude -p "score this" --output-format json` or its Codex equivalent. The v1 path instead points the existing `AnthropicJudge` / `OpenAICompatibleJudge` at the underlying model API (or at a LiteLLM proxy), bypassing the CLI layer entirely. See TRD §6.3 for the user-facing articulation.
- **Options considered:**
  - *v1 inclusion — ship a `ClaudeCodeJudge` subprocess adapter* — Pro: judge with exactly the configuration (system prompt, MCP servers, attached files) the user already has. Cons: (1) Claude Code and Codex CLI are optimized for human-interactive use, not `subprocess.Popen` automation; their non-interactive contracts are not long-term-stable. (2) Agentic scaffolding introduces non-determinism that breaks `FR-SCORE-2` (`scorer_version` drift detection) — the same `(prompt, content)` pair can produce different scores depending on what tools the CLI decides to call. (3) Subprocess IPC is 5–50× slower than HTTP. (4) Cost per judgment is 10–100× an equivalent stateless API call because the agent pays for its scaffolding.
  - **v1 exclusion + Path 1 guidance in the TRD (chosen)** — users point `AnthropicJudge` at the Anthropic API directly (same model family Claude Code uses, minus the agent wrapper) or `OpenAICompatibleJudge` at OpenAI / OpenRouter / LiteLLM (same model family Codex CLI uses). This is documented in TRD §6.1 env-var examples and §6.3 non-integrations.
  - *v2+ inclusion via user-defined Protocol adapter* — if the "Judge adapter Protocol/ABC extension seam" from Group A gets shipped, a third party can publish `plumb-claude-code-judge` as a separate package. plumb itself wouldn't maintain it.
- **Rationale for current pick:** Judges must be stateless pure functions for drift detection and cost determinism. Agentic CLIs are the *opposite* — they're multi-turn, tool-using, memory-holding, and version-in-flight. The cost and determinism penalties outweigh the ergonomic gain of "reusing my Claude Code config." Path 1 (point existing adapters at the underlying API) gives users 95% of the value at 0% of the cost.
- **Revisit trigger:** Claude Code or Codex CLI ships a stable, versioned, stateless judging mode (the way `anthropic-bench` or a server-side judging endpoint would look) AND the Group A "Protocol/ABC extension seam" has been shipped. Both conditions needed.

### Not doing — Runtime blocking / guardrails

- **Decision:** not doing (PRD non-goal)
- **Date:** 2026-04-23
- **Context:** Galileo and Patronus ship runtime-blocking guardrails (refuse to return unsafe output). Braintrust does not. This is a philosophy split.
- **Options considered:**
  - *Inclusion* — Con: directly contradicts PRD §7 "No runtime blocking / guardrails. After-the-fact eval only. (Galileo / Patronus philosophy split — we pick after-the-fact.)"
  - **Exclusion (chosen by PRD)** — plumb records, doesn't intervene.
- **Rationale for current pick:** PRD §7 picked after-the-fact eval explicitly. Instrumentation that can block production is a different product.
- **Revisit trigger:** PRD revision (would be a v3-level philosophy change).

### Not doing (v1) — Fifth SQL table

- **Decision:** not doing in v1 (PRD Tier-1 gating)
- **Date:** 2026-04-23
- **Context:** Surveys, ESM (experience sampling), cost ledgers all feel like they might want their own table. The PRD's constraint is "four tables is the thesis."
- **Options considered:**
  - *Fifth table* — Con: PRD §7 "No fifth table. Surveys, ESM prompts, cost ledgers all fold into existing tables (`runs.kind='survey'`, `scores.scorer='user_signal'`) or wait for v2." Also contradicts PRD §8 Tier-1 "Schema stability: zero schema migrations after Week 4."
  - **No fifth table (chosen by PRD)** — fold into `runs.kind`, `scores.scorer`, etc.
- **Rationale for current pick:** The four-table constraint IS the thesis; breaking it would invalidate the publishable framework claim.
- **Revisit trigger:** v2 (major version bump). Any need for a fifth table in v1 is a scope creep signal.

### Not doing (v1) — Third public instrumentation entry point

- **Decision:** not doing in v1 (PRD Tier-1 gating — "a third entry point is a regression")
- **Date:** 2026-04-23
- **Context:** Decorator + context manager is the full public surface. Class hierarchies, plugin systems, middleware patterns all get proposed at some point.
- **Options considered:**
  - *Plugin system* / *class hierarchy* / *middleware pattern* — each tempting, each would broaden the surface.
  - **Two entry points only (chosen by PRD)** — PRD §6 + §8 Tier-1 both say no.
- **Rationale for current pick:** Two entry points is explicitly gating in PRD §8 Tier-1. A third one is a regression per the PRD's own measure.
- **Revisit trigger:** Major version bump (v2+).

---

### v2 — Span `tokens_in` / `tokens_out` column split

- **Decision:** deferred to v2
- **Date:** 2026-04-29
- **Context:** The TRD §7.1 schema has a single `spans.tokens INTEGER` column. The `Span` entity carries both `tokens_in` and `tokens_out` fields, but on write only their sum is stored. On read, the sum is surfaced as `tokens_in`; `tokens_out` is always `None`. This is documented in the `Span` docstring and in `_row_to_span`. The user-visible API therefore silently loses the in/out split after a round-trip.
- **Options considered:**
  - *v1 entity collapse* — change `Span` to a single `tokens: int | None` field matching the schema. Loses the split at the call-site, which is ergonomically worse.
  - *v1 DDL split* — add `tokens_in` + `tokens_out` columns; requires a schema migration (violates PRD §8 Tier-1 schema-stability gate).
  - **v1 documentation + v2 schema change (chosen for v1)** — document the asymmetry clearly, keep both entity fields, and defer the DDL change. Code review finding I-1.
- **Rationale for current pick:** No schema migration is acceptable in v1 (PRD §8 Tier-1). The sum is the only durably correct value the TRD defined; the split is informational at the entity layer.
- **Revisit trigger:** Any consumer (CLI `run stats`, HTTP, judge slice) needs to distinguish input vs. output tokens. Requires a schema migration and a `user_version` bump.

### v1.1 — WAL/SHM file permissions

- **Decision:** deferred to v1.1
- **Date:** 2026-04-29
- **Context:** `SQLiteStorageAdapter.__init__` chmods the `.db` file to `0o600` after opening, but the WAL (`*.db-wal`) and SHM (`*.db-shm`) side-car files inherit the process umask (typically `0644`). On a multi-user system, a second local user can read the WAL and see payloads from transactions that have not yet been checkpointed. The paths are deterministic (`db_path + "-wal"`, `db_path + "-shm"`).
- **Options considered:**
  - *v1 inclusion* — chmod the wal/shm paths after `apply_pragmas` (they're created lazily, so a brief race exists, but it's narrow). Alternatively, set `O_NOFOLLOW` on open and chmod immediately.
  - *Document-only* — note in `getting_started.md` that users should set `umask 077` if sharing a machine.
  - **Deferred (chosen for v1)** — TRS §9.2 explicitly accepted this. Code review finding M-7.
- **Rationale for current pick:** Single-user local posture; FileVault/LUKS/BitLocker is the right layer for shared-machine confidentiality.
- **Revisit trigger:** First user report of WAL content leaking across accounts, OR plumb is used in a shared CI environment (multi-user Linux).

---

*End of backlog. Append new entries at the bottom of the appropriate group.*
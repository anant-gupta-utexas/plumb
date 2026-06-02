# plumb — Technical Requirements Document (TRD)

**Status:** v1.0 shipped; v1.1 / v1.2 / v2.0 specified — derived from [PRD](../1_product_and_research/PRD.md) §10 Release Plan
**Owner:** anant
**Last updated:** 2026-06-01
**Scope:** plumb v1.0 (shipped) → v1.1 (next release) → v1.2 → v2.0, mapped to PRD §10

> **Reading order.** This TRD is the text-heavy specification of *what to build, what rules it follows, how well it must perform.* The **"why"** lives in `[../1_product_and_research/PRD.md](../1_product_and_research/PRD.md)`. The **canonical schema + metric derivation** lives in `[../1_product_and_research/schema-and-metrics-v1.md](../1_product_and_research/schema-and-metrics-v1.md)` — reproduced in §7 with concrete SQL types and constraints. Options considered but not shipped, plus the per-decision rationale for everything scheduled here, are tracked in `[./deferred-features.md](./deferred-features.md)`.

> **Release coverage.** §§1–13 were written for v1.0 and remain the **baseline** specification (every v1.0 FR/NFR/AC still holds, except where a v1.1+ section *explicitly renegotiates* it — each such case is flagged inline). The post-v1.0 roadmap is specified in the **new §§14–18** (§14 is a one-page overview; §19 is the follow-up appendix):
> - **§15** — v1.1 (Atlas unblock + schema v2): one additive `user_version` 1→2 migration, third entry point `resume_run`, fifth handle method `add_example`. Full normative FR/NFR/Data/AC.
> - **§16** — v1.2 (Metric depth): plan-vs-execution, MAST tagging, judge calibration, concurrency, per-metric model overrides. Full normative FR/NFR/AC. **No schema migration.**
> - **§17** — v2.0 (Analysis, scale & alternative judges): scope-level specification only (goals, engineering scope, exit criteria), because these features are experiment-/content-driven and not yet frozen — per-feature AC is deferred to each feature's TDS.
> - **§18** — Development Phases: maps engineering phases to PRD §10 releases (Phase 1→v1.0, Phase 2→v1.1, Phase 3→v1.2, Phase 4→v2.0).
>
> Where a v1.0 FR is renegotiated (FR-API-1 surface cap, FR-API-4 four-method cap, DATA-MIG-1 zero-migration), the original text is **preserved** and a forward-pointer to the renegotiating section is added — the v1.0 record is never silently overwritten.

---

## 1. Executive Summary

plumb is a Python 3.13+ **library + CLI + local read-only HTTP service**, backed by a **four-table SQLite schema**, published to PyPI as `plumb`. It is the measurement spine that records *whether an agent actually worked* for a developer, end-to-end — acceptance, routing, handoff, cost, latency, reliability — across both offline evaluation runs and online production traces, in one unified schema.

The product has two instrumentation entry points and nothing else:

- **Decorator** (`@run(task_id=..., kind=...)`) — wraps a sync or async function as one `runs` row.
- **Context manager** (`with run(...) as r:`) — block-scoped equivalent.

Everything else is queries over the four-table schema, invoked via:

- `plumb` **CLI** — run stats, score writes, example promotion, judge runs.
- A **localhost-only FastAPI read service** (`127.0.0.1:8765` by default) — JSON query endpoints for notebooks / ad-hoc dashboards.

The technical approach is deliberately small: **one SQLite file + one content-addressed blob directory + ~2–3k LOC of pure Python**. No cloud, no SaaS, no real-time streaming, no custom dashboard (all PRD non-goals). Judges run **offline** via `plumb judge run` — never on the instrumented hot path.

Non-technical summary for stakeholders: plumb is the piece of software that sits inside your agent workflow and writes down, in a structured way, *what happened, what it cost, and whether the human accepted the result* — so you can answer model-swap and reliability questions with real data instead of vibes.

---

## 2. Business Context & Objectives

### 2.1 PRD reference & business goals

plumb exists to close the three instrumentation gaps identified in [PRD §1](../1_product_and_research/PRD.md):

1. **Acceptance is invisible** in existing agent-telemetry tools — none emit the intervention rate that DevEx teams actually want.
2. **Orchestrator-specific failures are uncategorized** — per Cemri et al.'s MAST taxonomy (arXiv:2503.13657), ~79% of multi-agent failures are specification or inter-agent misalignment, invisible to single-agent metrics.
3. **Offline and online live in different tools** — there is no minimal, public four-table reference implementation a small team can adopt in an afternoon.

The business outcome is a publishable artifact: a single framework that serves DevEx, AI/ML, and agentic-systems audiences (PRD §3) and produces real data inside 8 weeks of instrumentation (PRD §2).

### 2.2 Technical contribution to business outcomes

Every technical decision in this TRD ladders up to one of the PRD Tier-1 (gating) success metrics:

> This table records the **v1.0** gating contract (Week 6). Two of its rows — "Schema stability" and "Entry-point surface" — were deliberately renegotiated for the v1.1 roadmap per PRD §8 (2026-06-01 gate update): the entry-point surface widens (§15.1/§15.2) and exactly one additive migration is permitted (§15.3). These are tracked decisions, not regressions; see the inline notes at FR-API-1, FR-API-4, and DATA-MIG-1.

| PRD Tier-1 metric (Week 6 target)                         | TRD section that guarantees it                                                                                             |
| --------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------- |
| Instrumented atlas components: 4/4                        | §3 Functional Requirements (decorator + context manager compatible with sync/async, nested calls)                          |
| Runs captured: ≥ 30 real instrumented runs                | §4 NFR-Perf (hot-path overhead ≤ 1 ms per span; won't discourage instrumentation)                                          |
| Backfill coverage: ≥ 2 weeks Claude Code via ATTACH       | §6 Integrations (`agentsview` SQLite adapter, ≥200 LOC cap per PRD §6)                                                     |
| Schema stability: zero migrations after Week 4            | §7 Data Requirements (STRICT tables, explicit schema versioning, migration = v2)                                           |
| Entry-point surface: decorator + context manager only     | §3 FR-API (normative "MUST NOT add a third public entry point in v1")                                                      |
| Judge drift guard: `scorer_version` on every judge row    | §7 Data Requirements (`scores.scorer_version` NOT NULL CHECK) + §6 Integrations (adapter version tag)                      |
| Offline → online link: `examples.origin_run_id` populated | §7 Data Requirements (`examples.origin_run_id` FK → `runs.run_id`, promoted via `plumb example promote`)                   |
| CI regression gate with paired McNemar on 200-task set    | §10 QA Requirements (reference regression run wired into CI) + `plumb.stats` module for paired McNemar + BH-FDR correction |


### 2.3 Tier-2 (reach) objectives

PRD §8 Tier-2 (GitHub stars, public-post engagement, reuse signal) are aspirational, not gating. The TRD's obligation is to not *prevent* them: public repo, clean README, `pip install plumb` works on a fresh machine, quickstart runs in under a minute.

---

## 3. Functional Requirements

FR IDs are normative (`MUST`, `SHOULD`, `MAY` per RFC 2119). Each FR ties to a PRD section.

### 3.1 Public API surface

**FR-API-1 (MUST).** The public API surface is exactly two callables — `plumb.run` as a decorator and `plumb.run` as a context manager (unified via a single `Run` callable object that supports both forms, mirroring the PRD §6 examples). **No third public entry point is permitted in v1** (PRD §7 non-goal + PRD §8 Tier-1 gating metric).

> **Renegotiated in v1.1 (§15.1, FR-RESUME-1).** PRD §7 (2026-06-01) widens this gate to add a *third* entry point, `plumb.resume_run(run_id)`, for atlas's cross-process `code_gen` continuation. The v1.0 two-callable cap stands as the v1.0 record; v1.1 adds exactly one named callable with a documented contract — no plugin system, no class hierarchy. See §15.1.

**FR-API-2 (MUST).** The decorator form wraps sync and async functions equivalently:

```python
from plumb import run

@run(task_id="content-pipeline.ingest", kind="online")
def ingest(url: str) -> Doc: ...

@run(task_id="atlas.stage5.codegen", kind="online")
async def codegen(spec: Spec) -> Code: ...
```

Both produce exactly one `runs` row on function exit (success or failure).

**FR-API-3 (MUST).** The context-manager form is block-scoped and exposes the active `Run` handle:

```python
with run(task_id="atlas.stage5.codegen", kind="online") as r:
    r.add_score("verify_pass", scorer="deterministic", value_label="pass")
    ...
```

**FR-API-4 (MUST).** `Run` handles expose exactly these user-facing methods in v1 (normative surface):

- `r.add_score(metric_name, scorer, *, value_numeric=None, value_label=None, span_id=None, scorer_version=None)`
- `r.add_span(kind, name, *, parent_span_id=None, input_hash=None, output_hash=None, tokens=None, latency_ms=None, status=None, error_type=None)` — for manual span insertion when auto-capture doesn't cover a component.
- `r.set_models(orchestrator_model=None, sub_agent_model=None)` — free-text model identifier strings (see FR-META-1).
- `r.abort(reason: str)` — marks the run `status='aborted'` and closes it.

No public properties are mutable after run close. No plugin system, no middleware, no subclassing hook (PRD §7).

> **Renegotiated in v1.1 (§15.2, FR-ADDEX-1).** PRD §7 (2026-06-01) adds a *fifth* handle method, `r.add_example(...)`, so callers can record rejection examples programmatically from inside an active run instead of reaching into the adapter layer. The v1.0 four-method cap stands as the v1.0 record. See §15.2.

### 3.2 Auto-capture behaviour

**FR-CAP-1 (MUST).** Inside a decorated or context-managed run, calls to the following SDKs MUST be auto-captured as `spans` rows of `kind='llm'` or `kind='tool'`:

- `anthropic` (sync + async Messages API)
- `openai` (sync + async Chat Completions + Responses API)
- `httpx` (when used as tool client, captured as `kind='tool'`)

**FR-CAP-2 (SHOULD).** Auto-capture SHOULD be implemented via **contextvars + monkey-patching at import time** (opt-in via an explicit `plumb.autocapture.install()` call, invoked once from `plumb.__init__` when `PLUMB_AUTOCAPTURE=1`, default `1`). Users opting out (`PLUMB_AUTOCAPTURE=0`) fall back to manual `r.add_span(...)`.

**FR-CAP-3 (MUST).** Auto-capture MUST NOT mutate caller-visible SDK behaviour (return types, exception types, timeouts). On any internal error during capture, plumb MUST log at WARNING and proceed without rethrowing (see NFR-Rel-1).

### 3.3 Orchestrator / sub-agent run graphs

**FR-GRAPH-1 (MUST).** Nested `@run`/`with run(...)` invocations populate `runs.parent_run_id` automatically via contextvars. A sub-agent run started inside an orchestrator run becomes a child row; the span tree inside each run captures tool/LLM calls per run.

**FR-GRAPH-2 (MUST).** Runs MAY cross process boundaries via an explicit `parent_run_id` argument:

```python
@run(task_id="subagent.search", kind="online", parent_run_id=os.environ.get("PLUMB_PARENT_RUN_ID"))
```

Callers are responsible for threading `parent_run_id` through (e.g., via env var or sub-process kwargs). plumb does NOT inject this automatically across process boundaries.

**FR-GRAPH-3 (MUST).** Hand-offs between orchestrator and sub-agent are represented as `spans` rows of `kind='handoff'` on the parent run, with `input_hash` (the brief passed down) and `output_hash` (the summary returned up). The round-trip QA probe for the `handoff_roundtrip` metric (PRD §4) reads these two hashes from the blob store.

### 3.4 Scoring

**FR-SCORE-1 (MUST).** Scores MUST be writable via four independent paths:

- `r.add_score(...)` inside an open run (most common).
- `plumb score write --run-id <id> --metric <name> --scorer <kind> --value-* <v>` CLI.
- `plumb judge run --model <m> --metric <n>` CLI (batch-scores closed runs via judge adapter).
- Direct INSERT into `scores` by a user with repo access (escape hatch; not a stable contract).

**FR-SCORE-2 (MUST).** Every score row MUST carry `scorer_version` (NOT NULL). For `scorer='deterministic'`, this is the git SHA or semver of the check code. For `scorer='judge'`, this is `{provider}:{model}:{prompt_sha}`. For `scorer='human'` or `scorer='user_signal'`, this is a free-text label (e.g., `"anant@2026-04"`).

**FR-SCORE-3 (MUST).** Exactly one of `value_numeric` or `value_label` is populated per row (enforced by CHECK constraint, §7). Binary metrics use `value_label ∈ {'pass','fail'}`. Scalar metrics use `value_numeric`.

### 3.5 CLI

**FR-CLI-1 (MUST).** The `plumb` command is a registered entry point (`[project.scripts]` in `pyproject.toml`) with these subcommands:

```
plumb run stats [--since 7d] [--task-id <id>] [--format {table,json,csv}]
plumb score write --run-id <id> --metric <name> --scorer <kind>
                  (--value-numeric <n> | --value-label <v>)
                  [--span-id <id>] [--scorer-version <v>]
plumb example promote --from-run <run-id> [--rubric <path>]
plumb judge run --model <m> --metric <name>
                [--since 7d] [--task-id <id>] [--dry-run]
plumb serve [--host 127.0.0.1] [--port 8765]
plumb attach <path-to-sqlite> [--as <name>]
plumb version
```

**FR-CLI-2 (MUST).** `plumb serve` starts the local read-only FastAPI service (§3.6). All other subcommands exit with code 0 on success, non-zero on failure.

**FR-CLI-3 (SHOULD).** CLI output SHOULD default to human-readable tables for terminals (rich/tabulate) and newline-delimited JSON when stdout is not a TTY.

### 3.6 Local read-only HTTP service

**FR-HTTP-1 (MUST).** `plumb serve` binds to `127.0.0.1` only by default. Binding to `0.0.0.0` or a non-loopback interface MUST require an explicit `--host` flag and MUST emit a warning log line on startup (single-user local tool; see §4 NFR-Sec).

**FR-HTTP-2 (MUST).** The HTTP service exposes **read-only** endpoints over the SQLite file:

- `GET /runs?since=&task_id=&kind=&limit=` → paginated run summaries.
- `GET /runs/{run_id}` → run row + span tree + scores.
- `GET /examples?task_id=&active=` → regression dataset rows.
- `GET /stats/task/{task_id}?since=` → aggregated metrics per the ten v1 cut (PRD §4).
- `GET /health` → `{"status": "ok"}`.

No `POST`/`PUT`/`DELETE`/`PATCH` routes exist. Writes go through `plumb.run` and the CLI only.

**FR-HTTP-3 (MUST).** All response bodies are JSON (`application/json`). Request validation uses Pydantic v2 models.

### 3.7 Model metadata

**FR-META-1 (MUST).** `runs.orchestrator_model` and `runs.sub_agent_model` are **free-text strings** set by the caller. plumb does NOT validate them against an allowlist.

Examples the caller is expected to use:

- `"cursor/claude-sonnet-4.6"` — Cursor-routed Anthropic model.
- `"openrouter/qwen/qwen3-coder"` — OpenRouter-routed model.
- `"openai/gpt-5"`, `"anthropic/claude-opus-4.6"`, `"local/ollama/llama3.3-70b"` — other common forms.

Rationale: the caller's agent chooses the model (often via Cursor or OpenRouter); plumb's job is to *record* what was used, not to *call* it. Calling happens only in the judge layer (§6.1).

### 3.8 Edge cases and error behaviour

**FR-EDGE-1 (MUST).** If the wrapped function raises, plumb MUST:

- close the run with `status='failure'` and `error_type=<exception class name>`,
- flush all captured spans to SQLite,
- re-raise the original exception unchanged (no wrapping, no swallowing).

**FR-EDGE-2 (MUST).** If the process is killed mid-run (SIGKILL, OOM, power loss), plumb MUST:

- on next startup, detect incomplete runs (`end_ts IS NULL`) older than 1 hour and mark them `status='stalled'`,
- keep any spans that were flushed before the kill.

**FR-EDGE-3 (MUST).** Runs with zero spans are valid (deterministic checks that don't call an LLM are a real use case).

**FR-EDGE-4 (MUST).** Nested decorators on the same function MUST produce exactly one `runs` row (inner decorator detects an active run in contextvars and no-ops the outer call — the inner wins).

**FR-EDGE-5 (MUST).** `r.abort(reason="user cancelled")` sets `status='aborted'` and writes `reason` to an `error_type` field, skipping any remaining auto-capture.

---

## 4. Non-Functional Requirements (NFRs)

### 4.1 Performance

**NFR-Perf-1 (MUST).** p95 added latency per captured span ≤ **1 ms** over 10,000 no-op spans on reference hardware (Apple M-series, Python 3.13, SQLite in WAL mode). Measured by the reference benchmark in `tests/perf/test_span_overhead.py` (§10.3).

**NFR-Perf-2 (MUST).** p95 added latency per run close ≤ **50 ms** for runs with ≤ 100 spans. Includes batched INSERT, fsync, and contextvars teardown.

**NFR-Perf-3 (MUST).** SQLite MUST be opened in **WAL mode** (`PRAGMA journal_mode=WAL`) and **NORMAL synchronous** (`PRAGMA synchronous=NORMAL`) for all plumb-managed connections. `PRAGMA busy_timeout=5000` MUST be set.

**NFR-Perf-4 (MUST).** Span writes within a run are buffered in memory and batch-inserted on run close (single transaction, single fsync). Per-span synchronous fsync is prohibited.

**NFR-Perf-5 (MUST).** **Zero synchronous network I/O on the hot path.** Judges run only via explicit `plumb judge run`. The decorator/context manager MUST NOT call any network adapter during run open, run close, or span capture.

**NFR-Perf-6 (SHOULD).** Cold import of `plumb` ≤ 200 ms. Measured by `python -X importtime -c 'import plumb'` in CI.

### 4.2 Security

**NFR-Sec-1 (MUST).** All secrets (API keys for judge providers) MUST be read through `pydantic-settings` from environment variables. Plumb MUST NOT read credentials from files committed to git and MUST NOT accept secrets as CLI arguments.

**NFR-Sec-2 (MUST).** Secrets MUST NOT appear in log output, error messages, or exception traces. The judge adapters MUST redact `authorization` / `api-key` headers before logging request/response summaries.

**NFR-Sec-3 (MUST).** SQL execution MUST use parameterized queries only. String concatenation into SQL is prohibited (enforced by `ruff` rule `S608`).

**NFR-Sec-4 (MUST).** The local HTTP service (§3.6) MUST bind to `127.0.0.1` by default. No authentication is implemented because loopback-only + single-user machine is the security posture (see §9).

**NFR-Sec-5 (MUST).** The blob store MUST write content-addressed files with mode `0600`. The plumb data directory MUST be created with mode `0700` on first use.

**NFR-Sec-6 (MUST).** No telemetry, usage pings, or auto-update checks. Single-user local software makes zero outbound connections except judge API calls initiated explicitly by `plumb judge run`.

### 4.3 Reliability & Availability

**NFR-Rel-1 (MUST).** The decorator MUST NOT raise into the caller on *plumb's own* failure (storage I/O error, schema mismatch, auto-capture bug). Failures degrade to a structured WARNING log + a best-effort `runs` row with `status='failure'` and `error_type='plumb_internal_error'`. The wrapped function's return value / raised exception reaches the caller unchanged. Rationale: instrumentation that breaks production is worse than no instrumentation.

**NFR-Rel-2 (MUST).** 100% of writes flushed during run close MUST survive process kill post-fsync. SQLite WAL + explicit transaction commit on close provides this.

**NFR-Rel-3 (MUST).** ATTACH-based backfill from external SQLite files (§6.2) MUST be **idempotent**: re-running `plumb attach` on the same source file produces the same rows without duplicates (dedup key: source path + source row PK).

**NFR-Rel-4 (MUST).** Schema creation is idempotent (`CREATE TABLE IF NOT EXISTS`). Re-opening an existing plumb database never destroys data.

**NFR-Rel-5 (MUST).** No SLA, uptime, or RTO/RPO target — plumb is a library + local-user tool with no operator, no paging, no on-call. "Availability" = "the Python interpreter is running."

### 4.4 Usability

**NFR-Use-1 (MUST).** Python 3.13+ only (matches `pyproject.toml`, Assumption 2 below). Support for 3.12 is explicitly out of scope in v1.

**NFR-Use-2 (MUST).** `ruff check .` and `ruff format --check .` MUST pass on every commit to `main` (CI-enforced).

**NFR-Use-3 (MUST).** `mypy --strict` MUST pass on `plumb/core/` (the pure-Python core with no I/O). Adapters MAY use `mypy` in permissive mode.

**NFR-Use-4 (SHOULD).** Public API docstring coverage ≥ **95%** (measured via `interrogate` or equivalent). Every public class and method has a Google-style docstring with at least one usage example.

**NFR-Use-5 (MUST).** `pip install plumb` + `plumb --help` MUST work on a fresh Python 3.13 install with no other setup, validated in CI.

---

## 5. System Constraints & Assumptions

### 5.1 Technology constraints (inherited / fixed)

- **Language / runtime:** Python 3.13+ (`pyproject.toml` pin).
- **Storage:** SQLite 3.38+ — required for `STRICT` tables (3.37+) and JSON1 (bundled ≥ 3.38). Modern macOS / Linux / Windows all ship this.
- **Package manager:** `uv` (recommended per CLAUDE.md); `pip install -e .` supported as a fallback.
- **Project layout philosophy:** Clean-Architecture spirit (dependency inversion, testability) applied via **ports-and-adapters** rather than the literal `domain/application/infrastructure` three-folder split — see §5.3 Assumption 1 below.

### 5.2 Product constraints (from PRD §7 non-goals)

- **No fifth table.** Surveys, ESM prompts, cost ledgers fold into existing tables.
- **No third entry point.** Decorator + context manager only. This is Tier-1 gating in PRD §8.
- **No custom dashboard.** Visualization is out of scope; queries return JSON/DataFrame.
- **No SaaS, no multi-tenant, no auth.** Single-user local SQLite file.
- **No real-time streaming.** Batch writes on run close. Backfill via ATTACH only.
- **No runtime guardrails.** plumb is after-the-fact eval only (Galileo/Patronus philosophy split — PRD picks after-the-fact).

### 5.3 Assumptions

> **Assumption 1 (architectural).** The workspace rule in `[CLAUDE.md](../../CLAUDE.md)` mandates Clean Architecture with folders `domain/`, `application/`, `infrastructure/`. For plumb v1 this TRD interprets that rule as *spirit, not letter* and specifies **ports-and-adapters** (a recognized Clean Architecture expression) with `plumb/core/`, `plumb/adapters/`, `plumb/api.py`, `plumb/cli.py`, `plumb/http.py`. Rationale: plumb is a small library whose "business logic" is schema writes + SQL queries; a strict three-layer split with per-use-case classes and DTOs would roughly double the boilerplate-per-feature without improving the seams that actually matter (swappable storage, swappable judges, swappable adapter sources). The seams it *does* need are preserved via Protocols in `plumb/core/ports.py`. **Published libraries in the Python ecosystem (requests, httpx, pydantic, openai, anthropic, sqlalchemy) do not use the strict three-folder split either**; they organize by capability. **This deviation needs explicit user sign-off before TRD acceptance**, and will trigger a follow-up edit to CLAUDE.md to record plumb's convention. Tracked in `[./deferred-features.md](./deferred-features.md)` under "Architecture framing."

> **Assumption 2 (runtime pin).** Python 3.13+ in `pyproject.toml` is intentional, not a leftover template value. If the intent was actually 3.11+ (broader compatibility), this TRD should be revisited — `typing.Self`, `typing.LiteralString`, `except`* syntax, and several performance assumptions depend on the 3.13 floor.

> **Assumption 3 (read-service security posture).** The localhost-bound read service (§3.6) is the only HTTP surface. No authentication layer is specified because `127.0.0.1`-only binding + single-user machine + read-only endpoints = an acceptable posture for the PRD's "No SaaS, single-user" constraint. Users who sync their home directory across machines (Dropbox/iCloud) accept that the SQLite file is readable by local processes on any of those machines.

### 5.4 Third-party dependencies (v1)


| Dependency          | Floor                          | Purpose                                                                                     |
| ------------------- | ------------------------------ | ------------------------------------------------------------------------------------------- |
| `pydantic`          | ≥ 2.6                          | Domain model validation, API schemas                                                        |
| `pydantic-settings` | ≥ 2.2                          | Env-var driven config                                                                       |
| `anthropic`         | ≥ 0.40                         | Native Anthropic judge adapter (Sonnet 4.6, Opus 4.x)                                       |
| `openai`            | ≥ 1.50                         | OpenAI-compatible judge adapter (covers OpenRouter, Ollama, vLLM, LM Studio via `base_url`) |
| `fastapi`           | ≥ 0.115                        | Local read-only HTTP service                                                                |
| `uvicorn`           | ≥ 0.30                         | ASGI server for the read service                                                            |
| `typer`             | ≥ 0.12                         | CLI framework (preferred over raw `click` for type-hint-driven commands)                    |
| `httpx`             | (pulled by anthropic / openai) | Tool-call auto-capture                                                                      |
| `rich` *(opt)*      | ≥ 13                           | Human-readable CLI tables                                                                   |


Test/dev extras: `pytest`, `pytest-asyncio`, `pytest-cov`, `hypothesis`, `ruff`, `mypy`, `interrogate`.

### 5.5 Timeline & budget

- **Phase 1 (Week 6 per PRD §8):** v1 library + CLI + local read service + four instrumented atlas components + two-week ATTACH backfill.
- **Phase 2 (Week 9):** external repo instrumentation + judge re-calibration run + regression gate under cost budget.
- **Flagship (Week 11):** tagged v0.1 on PyPI + public repo + flagship long-form post.
- No monetary budget — single-developer project.

---

## 6. Integration Requirements

plumb has **exactly two** external integration categories in v1.

### 6.1 Judge LLM providers

**Two concrete adapters ship in v1.** Both implement `plumb.core.ports.JudgeAdapter`:

```python
class JudgeAdapter(Protocol):
    name: str
    version: str

    def score(
        self,
        *,
        metric_name: str,
        prompt: str,
        content: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> JudgeResult: ...
```

**INT-JUDGE-1 (MUST).** `plumb.adapters.judge_anthropic.AnthropicJudge` — uses the Anthropic Python SDK directly. Preserves provider-specific features: **prompt caching** (used for stable judge prompts across runs), **tool-use block streaming**, explicit beta headers. Configured via:

- `PLUMB_JUDGE_ANTHROPIC_API_KEY` (required when this adapter is selected)
- `PLUMB_JUDGE_MODEL` (default `"claude-sonnet-4-6"`)
- `PLUMB_JUDGE_MODEL_ROUTING_TOP1` (default `"claude-opus-4-5"`, per PRD §9)
- `PLUMB_JUDGE_MODEL_HANDOFF_ROUNDTRIP` (default `"claude-opus-4-5"`, per PRD §9)

**INT-JUDGE-2 (MUST).** `plumb.adapters.judge_openai_compat.OpenAICompatibleJudge` — uses the `openai` Python SDK with a configurable `base_url`. One adapter, many endpoints:


| Endpoint         | `PLUMB_JUDGE_BASE_URL`                | `PLUMB_JUDGE_API_KEY`  |
| ---------------- | ------------------------------------- | ---------------------- |
| OpenAI           | `https://api.openai.com/v1` (default) | OpenAI key             |
| **OpenRouter**   | `https://openrouter.ai/api/v1`        | OpenRouter key         |
| Ollama           | `http://localhost:11434/v1`           | any string (unchecked) |
| vLLM / LM Studio | `http://localhost:8000/v1`            | any string (unchecked) |
| LiteLLM proxy    | (user's gateway URL)                  | (user's gateway token) |


Because OpenAI, OpenRouter, Ollama, vLLM, LM Studio, and LiteLLM all speak the OpenAI-compatible chat-completions protocol, one adapter covers all of them via base-URL config. No plumb code changes needed to swap endpoint.

**INT-JUDGE-3 (MUST).** Adapter selection is config-driven:

```
PLUMB_JUDGE_PROVIDER=anthropic   # or "openai_compat"
```

Per-metric model override env vars (`PLUMB_JUDGE_MODEL_{METRIC_NAME_UPPER}`) work for both adapters.

**INT-JUDGE-4 (MUST).** Data exchange format:

- **Request body:** JSON (chat-completions shape). System prompt = the metric's judge prompt; user prompt = the candidate content. Temperature 0 (judge stability). Max tokens 1024.
- **Response:** JSON. Adapter parses the assistant's reply into a `JudgeResult{metric_name, value_numeric|value_label, rationale, tokens_in, tokens_out, latency_ms, scorer_version}`.
- **Auth:** bearer token in `Authorization` header.

**INT-JUDGE-5 (MUST).** Error handling: exponential backoff with jitter, **max 3 retries** on HTTP 429 / 5xx, **fail-open after** — return a `JudgeResult{value_label='error', rationale='<sanitized error>'}` and log at WARNING. Judge errors do NOT fail `plumb judge run`; they are recorded as `scores` rows with `scorer='judge'` and `value_label='error'` so the operator can re-run them.

**INT-JUDGE-6 (MUST).** `scorer_version` for a judge row is `{provider}:{model}:{prompt_sha}` — e.g., `"anthropic:claude-sonnet-4-6:a1b2c3d4"`. The prompt SHA pins the exact judge prompt used, enabling drift detection later without corrupting history (PRD §5, schema-and-metrics-v1.md §"scores").

### 6.2 `agentsview` SQLite adapter (ATTACH-based backfill)

**INT-ATTACH-1 (MUST).** `plumb.adapters.agentsview_attach.AgentsViewAdapter` backfills historical traces from `~/.agentsview/db.sqlite` (or a user-specified path) into plumb's schema via SQLite's `ATTACH DATABASE` + `INSERT INTO ... SELECT ...`. **No external ETL process.**

**INT-ATTACH-2 (MUST).** Implementation size cap: **≤ 200 LOC** (excluding tests and SQL), per PRD §6.

**INT-ATTACH-3 (MUST).** Idempotency: re-running `plumb attach <path>` MUST produce the same plumb rows without duplicates. Dedup key: `(source_db_path, source_session_id, source_step_id)`, stored as a deterministic `run_id = sha256(dedup_key)[:32]`.

**INT-ATTACH-4 (MUST).** Schema drift handling: if the upstream `agentsview` schema changes a column, the adapter MUST fail loudly with a clear error message naming the drifted column — NOT silently drop data. Per PRD §9, the 1-hour migration path is the remediation, not a redesign.

**INT-ATTACH-5 (SHOULD).** The adapter runs as part of `plumb attach <path>` (CLI) or can be invoked programmatically: `from plumb.adapters.agentsview_attach import backfill; backfill(Path("~/.agentsview/db.sqlite"))`.

### 6.3 Non-integrations (explicit)

The following are **NOT** integrations in v1 — called out so the TRD doesn't accidentally pull them in:

- No cloud providers (no AWS / GCP / Azure SDKs).
- No message brokers (no Kafka / RabbitMQ / SQS).
- No Docker registry, no Kubernetes.
- No webhooks, no ingress gateways.
- No OAuth / OIDC / SAML.
- No metrics backend (no Prometheus push, no OpenTelemetry export — spans live in `spans` table, not in OTel).
- **Agentic CLIs as judge runners.** Claude Code, Codex CLI, Cursor's agent, and similar interactive agentic tools are NOT invoked by `plumb judge run`. Users who want to judge with "the same model family I'm coding with" should point the existing `AnthropicJudge` or `OpenAICompatibleJudge` at the underlying model API (Anthropic, OpenAI, OpenRouter, or a LiteLLM proxy). Rationale: judges must be **stateless** `(prompt, content) → score` functions to satisfy `scorer_version` drift detection (FR-SCORE-2) and cost determinism; agentic scaffolding (tool use, memory, multi-turn planning) adds non-determinism and 10–100× cost. These tools remain **first-class as agents whose runs plumb *records*** via `runs.orchestrator_model` / `runs.sub_agent_model` (free-text strings per FR-META-1), e.g., `"claude-code/claude-sonnet-4-6"`, `"codex-cli/gpt-5"`. See `[./deferred-features.md](./deferred-features.md)` "Agentic-CLI-backed judge adapter" for the considered-and-not-shipping rationale.

---

## 7. Data Requirements

### 7.1 Schema — authoritative SQL

The four tables are defined exactly as below. Schema reproduced from PRD §5 and `[../1_product_and_research/schema-and-metrics-v1.md](../1_product_and_research/schema-and-metrics-v1.md)`; this TRD adds concrete SQL types, constraints, and indexes.

```sql
-- plumb v1 schema. STRICT tables require SQLite >= 3.37.
-- Migration from this schema == v2. Zero migrations after Week 4 (PRD §8 Tier-1).

CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT    PRIMARY KEY,
    kind                TEXT    NOT NULL CHECK (kind IN ('offline', 'online')),
    task_id             TEXT    NOT NULL,
    parent_run_id       TEXT             REFERENCES runs(run_id) ON DELETE SET NULL,
    orchestrator_model  TEXT,
    sub_agent_model     TEXT,
    prompt_version      TEXT,
    tool_schema_version TEXT,
    git_sha             TEXT,
    start_ts            TEXT    NOT NULL,                                  -- ISO-8601 UTC
    end_ts              TEXT,
    tokens_in           INTEGER,
    tokens_out          INTEGER,
    dollar_cost         REAL,
    status              TEXT    NOT NULL CHECK (status IN ('pending', 'success', 'failure', 'aborted', 'stalled')),
    error_type          TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_runs_task_start     ON runs(task_id, start_ts);
CREATE INDEX IF NOT EXISTS idx_runs_kind_start     ON runs(kind, start_ts);
CREATE INDEX IF NOT EXISTS idx_runs_parent         ON runs(parent_run_id);

CREATE TABLE IF NOT EXISTS spans (
    span_id         TEXT    PRIMARY KEY,
    run_id          TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    parent_span_id  TEXT             REFERENCES spans(span_id) ON DELETE SET NULL,
    kind            TEXT    NOT NULL CHECK (kind IN ('llm', 'tool', 'subagent', 'handoff', 'plan', 'verify')),
    name            TEXT    NOT NULL,
    input_hash      TEXT,
    output_hash     TEXT,
    tokens          INTEGER,
    latency_ms      INTEGER,
    status          TEXT             CHECK (status IS NULL OR status IN ('success', 'failure', 'aborted')),
    error_type      TEXT
) STRICT;

CREATE INDEX IF NOT EXISTS idx_spans_run           ON spans(run_id);
CREATE INDEX IF NOT EXISTS idx_spans_kind          ON spans(kind);
CREATE INDEX IF NOT EXISTS idx_spans_input_hash    ON spans(input_hash);
CREATE INDEX IF NOT EXISTS idx_spans_output_hash   ON spans(output_hash);

CREATE TABLE IF NOT EXISTS scores (
    score_id         TEXT    PRIMARY KEY,
    run_id           TEXT    NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    span_id          TEXT             REFERENCES spans(span_id) ON DELETE SET NULL,
    metric_name      TEXT    NOT NULL,
    scorer           TEXT    NOT NULL CHECK (scorer IN ('deterministic', 'judge', 'human', 'user_signal')),
    scorer_version   TEXT    NOT NULL,
    value_numeric    REAL,
    value_label      TEXT,
    scored_at        TEXT    NOT NULL,                                      -- ISO-8601 UTC
    CHECK ((value_numeric IS NULL) <> (value_label IS NULL))                -- exactly one
) STRICT;

CREATE INDEX IF NOT EXISTS idx_scores_run_metric   ON scores(run_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_scores_metric_time  ON scores(metric_name, scored_at);
CREATE INDEX IF NOT EXISTS idx_scores_scorer_ver   ON scores(scorer, scorer_version);

CREATE TABLE IF NOT EXISTS examples (
    example_id             TEXT    PRIMARY KEY,
    task_id                TEXT    NOT NULL,
    inputs_hash            TEXT    NOT NULL,
    expected_output_hash   TEXT,
    rubric                 TEXT,
    source                 TEXT    NOT NULL CHECK (source IN ('synthetic', 'production_promotion', 'human_authored')),
    origin_run_id          TEXT             REFERENCES runs(run_id) ON DELETE SET NULL,
    active                 INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at             TEXT    NOT NULL                                 -- ISO-8601 UTC
) STRICT;

CREATE INDEX IF NOT EXISTS idx_examples_task_active ON examples(task_id, active);
CREATE INDEX IF NOT EXISTS idx_examples_source      ON examples(source);
CREATE INDEX IF NOT EXISTS idx_examples_origin      ON examples(origin_run_id);
```

**Foreign-key enforcement:** `PRAGMA foreign_keys=ON` set on every connection (SQLite defaults to OFF).

### 7.2 Content-addressed blob store

**DATA-BLOB-1 (MUST).** Full content referenced by `spans.input_hash` / `spans.output_hash` / `examples.inputs_hash` / `examples.expected_output_hash` lives outside SQLite in a content-addressed filesystem blob store.

**DATA-BLOB-2 (MUST).** Blob layout:

```
$PLUMB_DATA_DIR/blobs/<sha256_hex[0:2]>/<sha256_hex[2:]>
```

Fan-out by first byte (256 subdirs) to keep directory listings manageable.

**DATA-BLOB-3 (MUST).** Blobs are immutable. Writes use `O_CREAT | O_EXCL` and silently succeed if the blob already exists (content-addressed ⇒ same hash ⇒ same content).

**DATA-BLOB-4 (MUST).** Each blob file mode `0600`. Parent dir `0700`.

**DATA-BLOB-5 (MUST).** Hashes are `sha256` hex digests (64 chars). Encoding of the content hashed: UTF-8 JSON for structured content (messages, tool args), raw bytes for binary.

### 7.3 Data directory layout

```
$PLUMB_DATA_DIR/                   # default: ~/.plumb/
├── plumb.db                       # SQLite (the four tables)
├── plumb.db-wal                   # WAL (SQLite-managed)
├── plumb.db-shm                   # shared memory index
├── blobs/                         # content-addressed blob store
│   ├── ab/
│   │   └── cdef012...             # sha256 minus first 2 chars
│   └── ...
└── judge_prompts/                 # versioned judge prompts (git-controlled)
    ├── routing_top1.md
    ├── handoff_roundtrip.md
    └── ...
```

`PLUMB_DATA_DIR` is env-var configurable (`pydantic-settings`). Default `~/.plumb/`.

### 7.4 Retention, backup, migration

**DATA-RET-1.** Retention: **indefinite** — single-user local; user owns deletion. No automated purge in v1.

**DATA-BAK-1.** Backup: **user responsibility**. The data dir is one folder; `cp -r`, Time Machine, rsync all work. No in-product backup feature.

**DATA-MIG-1.** Migration policy: **zero schema migrations after Week 4** (PRD §8 Tier-1 gating). Any schema change = v2 (major version bump). v1 ↔ v2 migration will be a separate tool (`plumb migrate v1-to-v2`); not in v1 scope.

> **Refined in v1.1 (§15.3, DATA-MIG-2).** The "zero migrations" discipline is preserved *per release*, not forever. v1.1 performs exactly **one** documented, additive migration (`user_version` 1→2) and re-freezes the schema for the rest of the release. The migration is additive-only — new columns and indexes on the four existing tables, **no fifth table, no destructive rewrites**. Whether a future bump is "minor + migration" vs. "major" is decided per release in the PRD §10 Release Plan, which is the authority. See §15.3 for the v1.1 migration contract.

---

## 8. Infrastructure & Environment Requirements

### 8.1 Library use

No infrastructure required. `pip install plumb` into any Python 3.13+ environment. plumb creates `$PLUMB_DATA_DIR` on first use.

### 8.2 Local HTTP read service

Single-process `uvicorn` binding to `127.0.0.1:8765` by default. No TLS (loopback only). No reverse proxy, no systemd unit, no Docker image bundled in v1.

### 8.3 Dev / staging / prod

Conceptually there are none. Dev = test = prod = the developer's machine. CI is the only other environment.

### 8.4 CI environment

- **Runner:** GitHub Actions, `ubuntu-24.04` and `macos-14` (matrix).
- **Python:** 3.13 (single-version; 3.14 added when released).
- **System deps:** SQLite 3.38+ (pre-installed on both runners; verified in the CI job).
- **Network:** outbound allowed for `pip install`; judge integration tests use **mocked** OpenAI/Anthropic endpoints via `pytest-httpx` (no real API calls in CI).

### 8.5 Follow-up work

> **Note.** The existing `[docker-compose.yml](../../docker-compose.yml)` at the repo root and the web-app-style examples in `[../3_guides/core_concepts.md](../3_guides/core_concepts.md)` pre-date this TRD and reference FastAPI/SQLAlchemy user-CRUD patterns that don't match plumb's actual shape. They should be rewritten as a follow-up task (out of scope for this TRD round):
>
> - `docker-compose.yml` → either delete (library doesn't need it) or rewrite to run `plumb serve` only.
> - `core_concepts.md` → rewrite around plumb's four-table schema, ports-and-adapters layout, and two-entry-point API instead of the User/CRUD examples.

---

## 9. Compliance & Regulatory Requirements

**None.** plumb is single-user local software with no PII collection.

- **No GDPR scope.** No personal data controller; no data subjects other than the user themselves; content lives in a hashed blob store on the user's own filesystem under the user's own control. The user is data controller and data processor simultaneously.
- **No HIPAA scope.** No PHI by design. If a user chooses to instrument a workflow that *handles* PHI, compliance is the user's responsibility (they control the blob store location and can elect to encrypt it out-of-band with LUKS/FileVault/BitLocker).
- **No SOC 2 / ISO 27001 / SOX.** No service operator, no attested controls, no scope.
- **No PCI DSS.** No cardholder data.
- **No export-controlled code.** Pure Python + standard SDKs.

Called out explicitly so this TRD doesn't accidentally invent compliance obligations the PRD doesn't require.

---

## 10. Quality Assurance Requirements

### 10.1 Test pyramid

Follows `[../4_testing/index.md](../4_testing/index.md)`, scoped to plumb's actual surface:


| Layer       | Scope                                                                                                                   | Coverage target     |
| ----------- | ----------------------------------------------------------------------------------------------------------------------- | ------------------- |
| Unit        | `plumb/core/` entities, scoring rules, schema writers, stats helpers                                                    | **≥ 90%**           |
| Integration | `plumb/adapters/`* against real SQLite temp files + mocked HTTP for judges; `plumb/api.py` wrapping real functions      | **≥ 80%**           |
| Property    | Schema invariants via Hypothesis (generate runs/spans/scores, assert FK integrity + CHECK enforcement)                  | (not measured as %) |
| E2E         | One reference scenario: toy orchestrator + two sub-agents + one judge run, end-to-end, asserting all expected rows land | pass/fail           |
| Performance | `tests/perf/test_span_overhead.py` — 10,000 no-op spans, assert p95 ≤ 1 ms (NFR-Perf-1)                                 | pass/fail           |


**Overall coverage threshold:** **≥ 75%**. CI fails the job below threshold.

### 10.2 Quality gates (pre-merge to `main`)

1. `ruff check .` — zero errors.
2. `ruff format --check .` — zero diffs.
3. `mypy --strict plumb/core/` — zero errors.
4. `pytest` — all pass (incl. performance test).
5. `pytest --cov=plumb --cov-report=term --cov-fail-under=75` — threshold met.
6. `interrogate --fail-under 95 plumb/api.py plumb/cli.py plumb/http.py` — docstring coverage on public API.

All six gates wired into GitHub Actions on pull requests.

### 10.3 Reference benchmark

`tests/perf/test_span_overhead.py` is the reference benchmark for NFR-Perf-1. It:

1. Opens an in-memory SQLite database (`:memory:`) in WAL mode.
2. Runs 10,000 `run(...).__enter__ → add_span(kind='llm', name='noop') → __exit__` cycles.
3. Asserts p95 per-span overhead ≤ 1 ms on the CI runner (with a 2× headroom factor applied locally to absorb CI noise).

### 10.4 Regression gate on the 200-task set (Week 6)

Per PRD §8 Tier-1:

- A curated 200-task regression dataset lives in `tests/regression/dataset/`.
- `pytest tests/regression/ --baseline=<sha> --candidate=HEAD` runs both and produces a paired McNemar comparison + Benjamini-Hochberg FDR correction (implemented in `plumb.stats`).
- At N=200, the minimum detectable effect is ~5–7pp (PRD §9); this MUST be stated in the CI job output and in any published model-swap write-up.
- A `runs.kind='offline'` row is recorded for each task × candidate combination.

### 10.5 Mocking policy

- **Network:** judge adapter tests use `pytest-httpx` to stub OpenAI/Anthropic endpoints. No real API calls in CI.
- **Time:** `freezegun` for `start_ts` / `end_ts` assertions.
- **Filesystem:** `tmp_path` pytest fixture for blob-store tests; in-memory SQLite where speed matters.

---

## 11. Deployment & Operations Requirements

### 11.1 Build & publish

- Build: `uv build` (produces sdist + wheel in `dist/`).
- Publish: `uv publish` (or `twine upload dist/`* as fallback).
- Versioning: semver. v0.1 tag at Phase 1 end. Pre-1.0 allows minor schema additions; **schema-breaking changes = major bump** and require the `plumb migrate` path (§7.4).

### 11.2 CI pipeline (GitHub Actions)

Matrix: `{ubuntu-24.04, macos-14} × Python 3.13`.

```
jobs:
  test:
    steps:
      - checkout
      - setup Python 3.13
      - uv sync
      - ruff check .
      - ruff format --check .
      - mypy --strict plumb/core/
      - pytest --cov=plumb --cov-fail-under=75
      - interrogate --fail-under 95 plumb/api.py plumb/cli.py plumb/http.py
      - pytest tests/perf/   # NFR-Perf-1
  publish:
    needs: test
    if: startsWith(github.ref, 'refs/tags/v')
    steps:
      - uv build
      - uv publish           # PyPI token in GH Secrets
```

### 11.3 Install-smoke job

On every release tag, a separate CI job creates a fresh Python 3.13 venv, runs `pip install plumb==<tag>`, and executes `plumb --help` + `plumb version` + a minimal `@run` decorator smoke script. Fails the release if smoke fails.

### 11.4 Monitoring, logging, alerting

- **Monitoring:** none. Library has no runtime surface to monitor.
- **Logging:** stdlib `logging` with structured output (JSON-lines format when stderr is not a TTY). Log level via `PLUMB_LOG_LEVEL` env var (default `WARNING`). Never logs secrets (NFR-Sec-2).
- **Alerting:** none.
- **On-call:** none.

### 11.5 Maintenance procedures

- Security patches to dependencies: dependabot PRs, auto-merged if CI green (to be configured).
- Schema changes: documented in `CHANGELOG.md`; major version bump; `plumb migrate` tool provided.
- End-of-life: Python version support mirrors upstream (drop 3.13 when it reaches EOL; bump floor).

---

## 12. Dependencies & Risks

### 12.1 Technical dependencies

Listed with version floors in §5.4. Summary: `pydantic`, `pydantic-settings`, `anthropic`, `openai`, `fastapi`, `uvicorn`, `typer`, plus dev extras.

### 12.2 Risks and mitigations

Mirrors PRD §9 with TRD-level mitigations:


| Risk                                                    | Likelihood | Impact | Mitigation                                                                                                                                                                                                    |
| ------------------------------------------------------- | ---------- | ------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Judge-quality regression (Sonnet 4.6 on routing-top-1)  | Medium     | High   | Verify judge F1 against a small labeled held-out set before quoting public numbers; pin judge prompts by SHA (§6.1 INT-JUDGE-6); `scorer_version` on every row enables drift detection.                       |
| 200-task MDE too loose for a model-swap post            | High       | Medium | State MDE (~5–7pp) explicitly in CI output and in any post (§10.4); don't claim precision the sample can't support.                                                                                           |
| `agentsview` schema drift breaks ATTACH adapter         | Low        | Medium | Adapter fails loudly with named-column error (§6.2 INT-ATTACH-4); 1-hour migration path, not a redesign.                                                                                                      |
| Hot-path overhead exceeds NFR-Perf-1 budget (1 ms)      | Medium     | High   | Reference benchmark in CI (§10.3); fallback to moderate budget (5 ms) tracked in `[./deferred-features.md](./deferred-features.md)`; zero synchronous network I/O on hot path is the key architectural guard. |
| Schema evolves despite zero-migration goal              | Medium     | High   | Ports-and-adapters: adding an adapter or a use case does NOT touch the schema; schema changes require TRD revision + user sign-off.                                                                           |
| Scope creep from the 66KB research synthesis doc        | High       | Medium | PRD §10 and this TRD both point at `schema-and-metrics-v1.md` as canonical, not the raw literature synthesis; the v1 cut (ten metrics) is closed.                                                             |
| CLAUDE.md Clean-Arch deviation causes reviewer friction | Medium     | Low    | Flagged in §5.3 Assumption 1; explicit user sign-off requested at TRD acceptance; follow-up CLAUDE.md edit proposed but not done unilaterally.                                                                |
| Secrets leaked via error messages or logs               | Low        | High   | NFR-Sec-2 + adapter-level header redaction; CI grep check for common key patterns (`AKIA`, `sk-`, `anthropic_api_key`) against committed code.                                                                |
| Long-running-agent needs break v1 schema                | Low        | Medium | PRD §7 explicitly defers long-running-agent instrumentation to v2; `spans.parent_span_id` + `runs.parent_run_id` are forward-compatible with subgoal extensions.                                              |


### 12.3 Blockers

- **Judge API quotas.** Week-6 `plumb judge run` on ≥ 30 runs requires Anthropic/OpenAI/OpenRouter budget available. User-provided; not a TRD concern beyond "fail-open on rate limits" (INT-JUDGE-5).
- **Architecture sign-off.** This TRD cannot be accepted until the §5.3 Assumption 1 deviation is approved.

---

## 13. Success Criteria & Acceptance Criteria

All acceptance criteria are stated in Given/When/Then form and tied back to a PRD Tier-1 success metric. Each must be independently testable.

### 13.1 API surface acceptance

**AC-API-1** (→ PRD Tier-1 "Entry-point surface").
*Given* a user imports `plumb`, *When* they enumerate public names on the `plumb` module, *Then* the only public callable for instrumentation is `run` (usable as both decorator and context manager), and any third entry point's presence fails the test.

**AC-API-2** (→ PRD Tier-1 "Instrumented atlas components 4/4").
*Given* a sync function `foo()` and an async function `bar()`, *When* both are wrapped with `@run(task_id=..., kind="online")` and invoked, *Then* exactly two `runs` rows exist with the correct `task_id`, `kind`, `status='success'`, `start_ts < end_ts`, and the sync vs async wrapping produces equivalent rows.

### 13.2 Performance acceptance

**AC-PERF-1** (→ NFR-Perf-1).
*Given* the reference benchmark in `tests/perf/test_span_overhead.py`, *When* it runs 10,000 no-op spans, *Then* the observed p95 added latency per span is ≤ 1 ms on the CI runner (with 2× headroom locally).

**AC-PERF-2** (→ NFR-Perf-2 + PRD Tier-1 "Runs captured ≥ 30").
*Given* a `with run(...)` block containing 100 `r.add_span(...)` calls, *When* the block exits, *Then* the observed run-close overhead is ≤ 50 ms at p95 over 100 iterations.

### 13.3 Schema acceptance

**AC-SCHEMA-1** (→ PRD Tier-1 "Schema stability: zero migrations after Week 4").
*Given* an existing `plumb.db` created by plumb v1.0.0, *When* plumb v1.x.y (x,y ≥ 0) opens it, *Then* no schema migration runs, `PRAGMA user_version` matches v1, and all existing rows are readable without transformation.

**AC-SCHEMA-2** (→ PRD Tier-1 "Judge drift guard").
*Given* a judge run writes 50 `scores` rows, *When* the rows are queried, *Then* 100% have `scorer_version` of the form `{provider}:{model}:{prompt_sha}` with a non-empty prompt SHA.

**AC-SCHEMA-3** (→ PRD Tier-1 "Offline → online link").
*Given* a production run R1 with a failed score, *When* `plumb example promote --from-run R1` is invoked, *Then* a new `examples` row exists with `source='production_promotion'`, `origin_run_id = R1.run_id`, `active=1`, and joining `examples → runs` on `origin_run_id` returns R1 exactly once.

### 13.4 Integration acceptance

**AC-INT-1** (→ PRD Tier-1 "Backfill coverage ≥ 2 weeks").
*Given* a `~/.agentsview/db.sqlite` file with 14 days of sessions, *When* `plumb attach ~/.agentsview/db.sqlite` runs, *Then* the resulting `runs` rows span ≥ 14 days AND re-running the same command produces zero new rows (idempotency; NFR-Rel-3).

**AC-INT-2** (→ INT-JUDGE-2).
*Given* `PLUMB_JUDGE_PROVIDER=openai_compat` and `PLUMB_JUDGE_BASE_URL=https://openrouter.ai/api/v1`, *When* `plumb judge run --model qwen/qwen3-coder --metric routing_top1 --dry-run` is invoked, *Then* the adapter sends a correctly-formed chat-completions request to OpenRouter's base URL with the bearer-token auth header (verified against a mock server).

**AC-INT-3** (→ INT-JUDGE-5).
*Given* the judge endpoint returns HTTP 429 three times then HTTP 200, *When* the judge adapter scores one row, *Then* the request is retried with exponential backoff + jitter and the final `scores` row is written with `scorer_version` populated and `value_label != 'error'`.

### 13.5 Reliability acceptance

**AC-REL-1** (→ NFR-Rel-1).
*Given* plumb's SQLite file is replaced mid-run by a read-only empty file (simulating storage failure), *When* a wrapped function completes, *Then* the wrapped function's return value reaches the caller unchanged AND a WARNING log line is emitted referencing `plumb_internal_error`.

**AC-REL-2** (→ NFR-Rel-2 + FR-EDGE-2).
*Given* a run with 50 spans flushed and the process is SIGKILLed before run close, *When* plumb is restarted 2 hours later, *Then* the run's existing spans are intact AND the run row is marked `status='stalled'` (1-hour threshold elapsed).

### 13.6 Security acceptance

**AC-SEC-1** (→ NFR-Sec-2).
*Given* the judge adapter receives an error from the judge API containing the raw API key in the upstream error body, *When* the error is logged, *Then* the log line contains no prefix of the API key (verified by regex `sk-[a-zA-Z0-9]{20,}` and `[Aa]uthorization:` checks).

**AC-SEC-2** (→ NFR-Sec-4 + FR-HTTP-1).
*Given* `plumb serve` is started without flags, *When* the bound socket is inspected, *Then* it is bound to `127.0.0.1:8765` AND connecting from a non-loopback interface fails.

### 13.7 QA acceptance

**AC-QA-1** (→ PRD Tier-1 "CI regression gate with paired McNemar").
*Given* the 200-task regression dataset and two candidate git SHAs, *When* `pytest tests/regression/` runs, *Then* a paired McNemar + BH-FDR result is produced, `runs.kind='offline'` rows are written for every task×candidate combination, and the stated MDE (~5–7pp) appears in the output.

---

## 14. Roadmap overview (v1.1 → v2.0)

§§1–13 specify v1.0 (shipped). The sections below specify the post-v1.0 roadmap, mapped 1:1 to the PRD §10 Release Plan. Each release's full per-decision rationale lives in `[./deferred-features.md](./deferred-features.md)`; this TRD adds the normative engineering contract.

| Section | PRD §10 release | Theme | Schema impact | Surface impact | Spec depth |
| --- | --- | --- | --- | --- | --- |
| §15 | **v1.1** | Atlas unblock + schema v2 | **one** additive migration `user_version` 1→2 | +1 entry point (`resume_run`), +1 handle method (`add_example`) | Full normative FR/NFR/Data/AC |
| §16 | **v1.2** | Metric depth (flagship post) | **none** — new scores fit existing `scores` table | none | Full normative FR/NFR/AC |
| §17 | **v2.0** | Analysis, scale & alt judges | none expected (revisit per feature) | none expected | Scope-level only (per-feature AC → TDS) |
| §18 | — | Development Phases | — | — | Phase→release mapping |

**Sequencing principle (inherited from PRD §10): dependency before label.** The backlog labels some metric work "v1.1"; that work sits *behind* v1.1's schema/judge-throughput work in dependency order, so it is scheduled as **v1.2** here. The PRD §10 Release Plan is the authority; backlog labels are traceability pointers, not commitments.

---

## 15. v1.1 — Atlas unblock + schema v2

**Goal.** Close the silent-data-loss gaps surfaced by atlas dogfooding and unblock the atlas integration. One additive schema migration (`user_version` 1→2) carries the whole data cluster; the surface gate is renegotiated for two API items. Maps to PRD §10 "v1.1 — Atlas unblock + schema v2".

**Five features** (each maps to a `deferred-features.md` entry):

| # | Feature | Backlog entry | Type |
| --- | --- | --- | --- |
| 1 | `plumb.resume_run(run_id)` | "v2 — `plumb.resume_run(run_id)`" (2026-05-06) | API — third entry point |
| 2 | `RunHandle.add_example(...)` | "v2 — `RunHandle.add_example(...)`" (2026-05-06) | API — fifth handle method |
| 3 | `scores.rationale` durable column | "v2 — `scores.rationale` durable column" (2026-05-06) | Schema (additive) |
| 4 | Idempotent score ingestion | "v2 — Idempotent score ingestion" (2026-05-06) | Schema (additive index) + API |
| 5 | `spans.tokens_in` / `tokens_out` split | "v2 — Span token column split" (2026-04-29) | Schema (additive) |

### 15.1 `plumb.resume_run(run_id)` — third entry point

**FR-RESUME-1 (MUST).** A new public callable `plumb.resume_run(run_id: str)` is added as the **third** instrumentation entry point. It is a context manager only (not a decorator) that re-opens an *existing* `runs` row and yields a `RunHandle` bound to it. This renegotiates FR-API-1 (§3.1); see PRD §7 and §8 gate update.

```python
import plumb

# Process A (atlas orchestrator) opens the run:
with plumb.run(task_id="atlas.codegen", kind="online") as r:
    run_id = r.run_id
    # ... emits PLUMB_PARENT_RUN_ID / run_id to process B ...

# Process B (atlas code_gen stage) continues the SAME run:
with plumb.resume_run(run_id=run_id) as r:
    r.add_span(kind="llm", name="codegen.call", ...)
    r.add_score("verify_pass", scorer="deterministic", value_label="pass")
```

**FR-RESUME-2 (MUST).** `resume_run` MUST append spans/scores to the existing `runs` row and MUST NOT:
- write a new `start_ts` (the row's original `start_ts` is preserved),
- create a child run (this is same-run continuation, distinct from FR-GRAPH-1 child runs),
- reset `status` away from a terminal state. If the target run is already `status IN ('success','failure','aborted')`, `resume_run` MUST raise `ValidationError` before yielding — re-opening a closed run is a caller error, not a silent no-op.

**FR-RESUME-3 (MUST).** On `resume_run` block exit, the run is **re-finalized**: `end_ts` is updated to the new exit time, terminal `status` is set from block outcome (success / exception → `failure`), and newly buffered spans flush in one transaction (NFR-Perf-4 still applies). The bidirectional invariant from FR-EDGE-1 (re-raise unchanged) holds.

**FR-RESUME-4 (MUST).** If `run_id` does not exist, `resume_run` MUST raise `NotFoundError` before yielding. This is distinct from the FR-RESUME-2 already-terminal case.

**FR-RESUME-5 (SHOULD).** Cross-process safety: because two processes MAY hold the same `run_id`, the adapter relies on SQLite WAL + `busy_timeout=5000` (NFR-Perf-3) for write serialization. plumb does NOT add application-level locking in v1.1; concurrent `resume_run` on the *same* row from two live processes is an unsupported caller pattern (documented, not enforced). The supported pattern is *sequential* hand-off (process A closes or hands off, then process B resumes).

**Storage contract.** The adapter grows an `open_or_resume(run_id)` path: `SELECT` the row, assert non-terminal, return a handle whose `finalize_run` performs an `UPDATE ... WHERE run_id=?` (not an `INSERT`). No new `start_ts`.

### 15.2 `RunHandle.add_example(...)` — fifth handle method

**FR-ADDEX-1 (MUST).** `RunHandle` gains a fifth user-facing method, renegotiating FR-API-4 (§3.1):

```python
r.add_example(
    inputs_hash: str,
    *,
    source: Literal["synthetic", "production_promotion", "human_authored"],
    expected_output_hash: str | None = None,
    rubric: str | None = None,
) -> str   # returns example_id
```

**FR-ADDEX-2 (MUST).** `add_example` writes one `examples` row with `task_id` taken from the active run, `origin_run_id` set to the active run's `run_id`, `active=1`, and `created_at` from the injected `Clock`. It returns the generated `example_id`.

**FR-ADDEX-3 (MUST).** `inputs_hash` and (when provided) `expected_output_hash` MUST be 64-char sha256 hex (same validation as `Example` entity, §7.1). Invalid hashes raise `ValidationError` without writing a row.

**FR-ADDEX-4 (MUST).** `add_example` is the programmatic equivalent of `plumb example promote` (§3.5) but callable from inside an open run. It does NOT replace the CLI path; both write structurally identical `examples` rows.

### 15.3 Schema v2 migration contract

**DATA-MIG-2 (MUST).** v1.1 performs **exactly one** schema migration, `user_version` 1→2, applied automatically on first open of a v1 database by a v1.1 build. The migration is **additive only**:

- `ALTER TABLE scores ADD COLUMN rationale TEXT;` (§15.4)
- `ALTER TABLE spans ADD COLUMN tokens_in INTEGER;` and `ALTER TABLE spans ADD COLUMN tokens_out INTEGER;` (§15.5)
- `CREATE UNIQUE INDEX idx_scores_idem ON scores(run_id, metric_name, scorer_version, IFNULL(span_id, ''));` (§15.6)

**DATA-MIG-3 (MUST).** The migration MUST be **idempotent and non-destructive**: it MUST NOT drop, rename, or rewrite any existing column or row, MUST NOT create a fifth table, and re-running a v1.1 build against an already-migrated (`user_version=2`) database MUST be a no-op. `SCHEMA_VERSION` bumps to `2`; after the migration runs, the schema re-freezes for the remainder of the v1.1 release line (DATA-MIG-1 discipline, preserved per-release).

**DATA-MIG-4 (MUST).** Migration is wrapped in a single transaction. On any failure mid-migration, the transaction rolls back and `user_version` stays at `1`; plumb raises `StorageError` naming the failed step. A partially-migrated database is never committed.

**DATA-MIG-5 (MUST).** The `_bootstrap_schema` version gate (currently: `0 → set`, `== SCHEMA_VERSION → ok`, else → error) is extended with a `1 → run migration → 2` arm. A database at `user_version > SCHEMA_VERSION` (a newer plumb wrote it) still raises `StorageError` — downgrade is unsupported.

**DATA-MIG-6 (MUST — duplicate-row safety, per 2026-06-01 decision).** The idempotency UNIQUE index (§15.6) can fail to build if a v1.0 database already contains duplicate score rows under the new key. The migration MUST **pre-check** for such duplicates and, if any exist, **abort loudly** (`StorageError` naming the conflicting `(run_id, metric_name, scorer_version, span_id)` tuples and the row count) **without deleting any rows**. plumb MUST NOT auto-dedup user data (NFR-Rel-4 "never destroys data"). The error message MUST point the user at a documented manual-dedup recipe. Rationale: silently deleting score history to satisfy an index is a worse failure than a blocked upgrade the user can resolve deliberately.

### 15.4 `scores.rationale` durable column

**FR-RATIONALE-1 (MUST).** The `scores` table gains a `rationale TEXT` (nullable) column. The `Score` entity already carries `rationale: str | None` (v1.0) and `RunHandle.add_score(..., rationale=...)` already accepts it (v1.0) — v1.1 closes the silent drop at the storage boundary.

**FR-RATIONALE-2 (MUST).** `_score_to_row` MUST persist `rationale`; `_row_to_score` MUST read it back. A round-trip of a score with `rationale="..."` MUST return the same string. Judge adapters (§6.1) already produce rationale text; their `write_score` path now persists it.

**FR-RATIONALE-3 (MUST).** Pre-migration rows (written by v1.0) have `rationale = NULL` after the `ALTER`; this is correct (the data was never captured) and MUST NOT be backfilled or fabricated.

### 15.5 `spans.tokens_in` / `tokens_out` column split

**FR-TOKENS-1 (MUST).** The `spans` table gains `tokens_in INTEGER` and `tokens_out INTEGER` (both nullable). The v1.0 single `tokens` column is **retained** (additive-only rule, DATA-MIG-3) and continues to hold the sum for backward-compatible reads.

**FR-TOKENS-2 (MUST).** On write (post-migration), `_span_to_row` MUST populate all three: `tokens_in`, `tokens_out`, and `tokens = (tokens_in or 0) + (tokens_out or 0)`. On read, `_row_to_span` MUST surface `tokens_in` and `tokens_out` from the new columns directly — eliminating the v1.0 round-trip asymmetry (v1.0 surfaced the sum as `tokens_in` and always returned `tokens_out=None`; see entity docstring `plumb/core/entities.py:120`).

**FR-TOKENS-3 (MUST).** Pre-migration span rows have `tokens_in = NULL`, `tokens_out = NULL`, and the original summed `tokens`. Readers MUST treat a NULL `tokens_in` with a non-NULL `tokens` as "split unknown, sum = `tokens`" — i.e., fall back to the v1.0 behaviour for legacy rows (surface `tokens` as `tokens_in`). This MUST be covered by an explicit test (AC-TOKENS-2).

**FR-TOKENS-4 (SHOULD).** Aggregate queries that currently sum `tokens` (e.g. `plumb run stats`, the HTTP `/stats` slice) SHOULD prefer `COALESCE(tokens_in,0)+COALESCE(tokens_out,0)` only when `tokens_in IS NOT NULL`, else fall back to `tokens`, so mixed legacy/new databases report consistent totals.

### 15.6 Idempotent score ingestion

**FR-IDEM-1 (MUST).** A UNIQUE index `idx_scores_idem` on `(run_id, metric_name, scorer_version, IFNULL(span_id, ''))` is added (§15.3). The `IFNULL(span_id,'')` term makes the constraint NULL-safe (two run-level scores with the same metric+version collide; SQLite would otherwise treat `NULL != NULL`).

**FR-IDEM-2 (MUST).** `RunHandle.add_score` and `plumb score write` gain an optional `idempotency_key: str | None` parameter. When the underlying write would violate `idx_scores_idem`, the storage layer MUST use `INSERT ... ON CONFLICT DO NOTHING` semantics (the first write wins; subsequent identical writes are silent no-ops). The method MUST return a flag or the existing `score_id` so the caller can tell insert from no-op.

**FR-IDEM-3 (MUST).** Error scores are exempt from collision suppression where it would hide a re-run: a row with `scorer_version` ending in `:error` (judge fail-open, INT-JUDGE-5) MUST NOT block a later successful re-score of the same `(run_id, metric_name)`. The index key includes `scorer_version`, so `provider:model:sha` and `provider:model:sha:error` are distinct keys — this falls out of the schema, but MUST be asserted by test (AC-IDEM-2).

**FR-IDEM-4 (MUST).** `idempotency_key` is **not** stored as a column (no fifth-table-style sprawl); it is a *client-supplied assertion* that the call is safe to retry. The actual dedup is enforced by the UNIQUE index on the semantic key. If a caller passes an `idempotency_key` but the semantic key differs from a prior write, a new row IS written (the key is advisory, the index is authoritative). This is documented behaviour, not a contradiction.

### 15.7 v1.1 NFRs (deltas from §4)

**NFR-MIG-1 (MUST).** The `user_version` 1→2 migration MUST complete in ≤ **500 ms** for a database with ≤ 100k score rows on reference hardware (the duplicate pre-check in DATA-MIG-6 is the dominant cost — it is a single indexed `GROUP BY ... HAVING COUNT(*)>1` scan).

**NFR-MIG-2 (MUST).** Migration runs **once**, inside the existing connection bootstrap (`_bootstrap_schema`), before any user query. It adds zero hot-path cost after the one-time run (NFR-Perf-1/2 unaffected).

**NFR-RESUME-1 (MUST).** `resume_run` open (re-`SELECT` + handle construction) MUST add ≤ **5 ms** p95 over the existing `run(...)` open path; re-finalize cost is bounded by the same NFR-Perf-2 (≤ 50 ms for ≤ 100 spans) budget as a normal close.

**NFR-RESUME-2 (MUST).** All v1.0 NFR-Sec / NFR-Rel guarantees hold unchanged for `resume_run` and `add_example`: parameterized SQL (NFR-Sec-3), no secrets in logs (NFR-Sec-2), fail-degraded-not-raise on plumb's own internal error (NFR-Rel-1).

### 15.8 v1.1 acceptance criteria

**AC-RESUME-1** (→ FR-RESUME-1/2/3).
*Given* a run R opened and closed-by-handoff in process A with 3 spans, *When* process B calls `with plumb.resume_run(R.run_id) as r:` and adds 2 spans, *Then* exactly one `runs` row exists for R with 5 spans total, R's original `start_ts` is unchanged, and `end_ts` reflects the process-B exit time.

**AC-RESUME-2** (→ FR-RESUME-2).
*Given* a run R already at `status='success'`, *When* `plumb.resume_run(R.run_id)` is called, *Then* it raises `ValidationError` before yielding a handle and writes no new rows.

**AC-RESUME-3** (→ FR-RESUME-4).
*Given* a `run_id` that does not exist, *When* `plumb.resume_run(...)` is called, *Then* it raises `NotFoundError`.

**AC-ADDEX-1** (→ FR-ADDEX-1/2).
*Given* an open run R, *When* `r.add_example(inputs_hash=<64hex>, source="production_promotion")` is called, *Then* one `examples` row exists with `origin_run_id=R.run_id`, `task_id=R.task_id`, `active=1`, and the returned `example_id` matches that row.

**AC-ADDEX-2** (→ FR-ADDEX-3).
*Given* an open run, *When* `r.add_example(inputs_hash="not-hex")` is called, *Then* it raises `ValidationError` and no `examples` row is written.

**AC-MIG-1** (→ DATA-MIG-2/3/5 + PRD §8 gate update "one documented additive migration").
*Given* a `plumb.db` at `user_version=1` written by v1.0, *When* a v1.1 build opens it, *Then* `user_version` becomes `2`, the `scores.rationale`, `spans.tokens_in`, `spans.tokens_out` columns and `idx_scores_idem` index exist, and every pre-existing row is readable unchanged.

**AC-MIG-2** (→ DATA-MIG-3 idempotency).
*Given* an already-migrated `user_version=2` database, *When* a v1.1 build re-opens it, *Then* no `ALTER`/`CREATE INDEX` runs again and the open succeeds with no error.

**AC-MIG-3** (→ DATA-MIG-6 duplicate safety).
*Given* a `user_version=1` database seeded with two score rows sharing `(run_id, metric_name, scorer_version, span_id)`, *When* a v1.1 build opens it, *Then* the migration aborts with `StorageError` naming the conflicting tuple and row count, `user_version` stays `1`, and **both** duplicate rows are still present (zero deletions).

**AC-MIG-4** (→ DATA-MIG-4 atomicity).
*Given* a migration step is forced to fail (injected error on the index creation), *When* a v1.1 build opens the database, *Then* the whole migration rolls back, `user_version` stays `1`, and the `scores.rationale` column added earlier in the same migration is NOT present.

**AC-RATIONALE-1** (→ FR-RATIONALE-2).
*Given* a v1.1 database, *When* `r.add_score("m", scorer="judge", value_label="pass", rationale="because X")` is written and the row re-read, *Then* `Score.rationale == "because X"`.

**AC-TOKENS-1** (→ FR-TOKENS-2).
*Given* a v1.1 database, *When* a span is written with `tokens=(10, 25)` and re-read, *Then* `Span.tokens_in==10` and `Span.tokens_out==25` (no round-trip asymmetry).

**AC-TOKENS-2** (→ FR-TOKENS-3 legacy fallback).
*Given* a span row written by v1.0 (only summed `tokens=35`, `tokens_in/out` NULL after migration), *When* it is re-read by v1.1, *Then* `Span.tokens_in==35` and `Span.tokens_out is None` (v1.0 fallback semantics preserved).

**AC-IDEM-1** (→ FR-IDEM-1/2).
*Given* an open run, *When* `r.add_score(...)` is called twice with the identical `(metric_name, scorer, scorer_version, span_id, value)`, *Then* exactly one `scores` row exists and the second call reports a no-op (no new `score_id`).

**AC-IDEM-2** (→ FR-IDEM-3).
*Given* a judge fail-open row with `scorer_version="anthropic:claude-sonnet-4-6:abc:error"`, *When* a successful re-score writes `scorer_version="anthropic:claude-sonnet-4-6:abc"` for the same `(run_id, metric_name)`, *Then* both rows coexist (distinct keys; the error does not block the re-score).

---

## 16. v1.2 — Metric depth

**Goal.** Richer failure analysis for the long-form write-up. **No schema migration** — every new score fits the existing `scores` table via `metric_name`; `user_version` stays at `2`. Maps to PRD §10 "v1.2 — Metric depth".

**Renumber note (inherited from PRD §10).** The backlog labels these features "v1.1"; they are scheduled here as **v1.2** because they depend on v1.1's judge-throughput (concurrency) and migration work landing first.

**Five features:**

| # | Feature | Backlog entry | Storage |
| --- | --- | --- | --- |
| 1 | Plan-vs-execution attribution | "v1.1 — Plan-vs-execution attribution" | `scores.metric_name ∈ {'plan_failure','execution_failure'}` |
| 2 | MAST 14-mode failure tagging | "v1.1 — MAST 14-mode failure tagging" | `scores.metric_name='mast_mode'`, `value_label=<mode_id>` |
| 3 | Judge calibration vs human α | "v1.1 — Judge calibration against human-human α baseline" | new `plumb.stats` helper; scores compared, not stored as new shape |
| 4 | Concurrent judge calls | "v1.1 — Concurrent judge calls" | none (throughput only) |
| 5 | Per-metric model env overrides | "v1.1 — Per-metric model env overrides" | none (config only) |

### 16.1 Plan-vs-execution attribution

**FR-PLANEX-1 (MUST).** A new `plumb judge run` mode (or a dedicated `plumb attribute plan-vs-exec`) implements the counterfactual recipe: for each failed run, re-run the **same plan** with a **stronger executor model**; if it now succeeds → `execution_failure`, else → `plan_failure`. Results are written as `scores` rows with `scorer='judge'`, `metric_name ∈ {'plan_failure','execution_failure'}`, `value_label ∈ {'pass','fail'}` (or `value_numeric` confidence).

**FR-PLANEX-2 (MUST).** The stronger-executor model is configurable via the per-metric override mechanism (§16.5) — plan-vs-exec defaults to an Opus-class model; the original run's executor is read from `runs.sub_agent_model`.

**FR-PLANEX-3 (MUST).** Attribution scores carry `scorer_version` in the standard `{provider}:{model}:{prompt_sha}` form (FR-SCORE-2), so a later prompt change is drift-detectable. No schema change: the recipe writes ordinary `scores` rows.

### 16.2 MAST 14-mode failure tagging

**FR-MAST-1 (MUST).** An LLM-judge tags each failed run with one-or-more of Cemri et al.'s 14 MAST failure modes (arXiv:2503.13657). Each tag is one `scores` row: `metric_name='mast_mode'`, `value_label=<mode_id>` (a stable enumerated identifier, e.g. `"1.1"`…`"3.3"`), `scorer='judge'`.

**FR-MAST-2 (MUST).** Multiple modes per run are represented as multiple rows (one per mode), not a delimited string — this keeps `GROUP BY value_label` failure dashboards trivial and respects the "no fifth table / no array column" constraint.

**FR-MAST-3 (SHOULD).** The MAST mode-id vocabulary is pinned in a versioned prompt/reference file under `judge_prompts/` so the 14-mode taxonomy can be re-cut without rewriting history (the `prompt_sha` in `scorer_version` records which vocabulary version produced each tag).

**FR-MAST-4 (MUST — validation gate).** The MAST tagger MUST NOT be quoted publicly until validated against ≥ **30 failed runs** with human-confirmed mode labels (PRD §4 + backlog "needs ≥30 failed runs to validate"). This is a release gate, captured in AC-MAST-1.

### 16.3 Judge calibration vs human α

**FR-CALIB-1 (MUST).** A `plumb.stats` helper computes **Krippendorff's α** between a judge's labels and a human-labeled held-out set for a given metric. The scaffold (`scorer_version` on every row, v1.0) already enables pairing judge rows to human rows by `(run_id, metric_name)`.

**FR-CALIB-2 (MUST).** A CLI surface (`plumb judge calibrate --metric <name> --against human`) reports α plus the human–human baseline α (the ceiling). Output states the held-out set size and warns when N is too small for a stable α.

**FR-CALIB-3 (SHOULD).** Calibration is read-only over existing `scores` rows — it computes a statistic, it does not write a new score shape. (If a calibration *result* is recorded, it is an ordinary `scores` row, e.g. `metric_name='judge_alpha'`, `scorer='deterministic'`.)

### 16.4 Concurrent judge calls

**FR-CONC-1 (MUST).** `plumb judge run` gains `--concurrency N` (default `1`, preserving v1.0 sequential behaviour). Concurrency is backed by a bounded thread pool (`concurrent.futures.ThreadPoolExecutor`), sized by `N`.

**FR-CONC-2 (MUST).** The fail-open retry path (INT-JUDGE-5: 3 retries, exp backoff + jitter) MUST remain correct under concurrency. A semaphore or the pool bound MUST cap in-flight requests so rate-limit retries don't stampede. Per-row failures stay isolated — one row's `value_label='error'` MUST NOT abort sibling rows in the pool.

**FR-CONC-3 (MUST).** Score writes from concurrent judges MUST be serialized at the storage boundary (single writer connection or a write lock) — SQLite WAL allows one writer; the thread pool fans out the *network* calls, not the writes. Combined with v1.1 idempotency (FR-IDEM-1), a retried row cannot create a duplicate.

**FR-CONC-4 (SHOULD).** Progress reporting (rows done / total / errors) MUST remain coherent under concurrency (a thread-safe counter or `rich` progress bar).

### 16.5 Per-metric model env overrides

**FR-MODELOV-1 (MUST).** A per-metric model override cascade is added to `Settings`: `PLUMB_JUDGE_MODEL_<METRIC_NAME_UPPER>` (e.g. `PLUMB_JUDGE_MODEL_PLAN_FAILURE=claude-opus-4-7`). Resolution order: explicit `--model` CLI flag → per-metric env var → global `PLUMB_JUDGE_MODEL` → adapter default. This generalizes the v1.0 routing/handoff overrides (INT-JUDGE-1) to *any* metric.

**FR-MODELOV-2 (MUST).** Override resolution lives in the judge-adapter factory (`get_judge_adapter`), not scattered through call sites. Cheap binary metrics can target a Haiku-class model; plan-vs-exec / MAST can target Opus — without per-call `--model` flags.

### 16.6 v1.2 NFRs (deltas)

**NFR-CONC-1 (SHOULD).** With `--concurrency 8`, a 200-run judge backlog SHOULD complete in ≤ **1/4** the wall-clock of the sequential path on the same hardware/endpoint (network-bound; subject to provider rate limits). This targets the backlog's ">5 min for 200 runs" revisit trigger.

**NFR-CONC-2 (MUST).** Concurrency MUST NOT change recorded results: the set of `scores` rows produced by `--concurrency N` MUST equal the set produced by `--concurrency 1` for the same input (determinism of *content*, not of *order*).

### 16.7 v1.2 acceptance criteria

**AC-PLANEX-1** (→ FR-PLANEX-1).
*Given* a failed run R with a recorded plan and `sub_agent_model`, *When* the plan-vs-exec recipe re-runs R's plan with a stronger executor that succeeds, *Then* a `scores` row with `metric_name='execution_failure'`, `scorer='judge'`, and a populated `scorer_version` is written for R.

**AC-MAST-1** (→ FR-MAST-1/4).
*Given* ≥ 30 failed runs with human-confirmed MAST labels, *When* the MAST tagger runs and is compared to the human labels, *Then* per-mode agreement is reported AND each tagged run has ≥ 1 `scores` row with `metric_name='mast_mode'` and a valid `value_label` mode-id. (Release gate: tagger is not quoted publicly below this bar.)

**AC-CALIB-1** (→ FR-CALIB-1/2).
*Given* a metric with both judge and human `scores` rows on a shared held-out set, *When* `plumb judge calibrate --metric <name>` runs, *Then* it reports Krippendorff's α (judge vs human) and the human–human baseline α, with the held-out N stated.

**AC-CONC-1** (→ FR-CONC-2/NFR-CONC-2).
*Given* a 50-run backlog where the mock judge returns HTTP 429 on a subset, *When* `plumb judge run --concurrency 8` runs, *Then* the resulting `scores` rows are identical (as a set) to a `--concurrency 1` run, retried rows produce no duplicates (FR-IDEM-1), and per-row errors don't abort siblings.

**AC-MODELOV-1** (→ FR-MODELOV-1).
*Given* `PLUMB_JUDGE_MODEL_PLAN_FAILURE=claude-opus-4-7` and no `--model` flag, *When* the plan-failure judge runs, *Then* the adapter is invoked with `claude-opus-4-7`; *and given* a `--model` flag is also present, *then* the flag wins.

---

## 17. v2.0 — Analysis, scale & alternative judges (scope-level)

**Goal.** Reporting frontiers, alternative judge backends, and judge throughput at scale. This is the largest, most experiment-/content-driven release; per PRD §10 it is the next *major* version. Maps to PRD §10 "v2.0 — Analysis, scale & alternative judges".

**Specification depth (deliberate).** Unlike §§15–16, v2.0 is specified at **scope level only** — goals, engineering-scope summary, and exit criteria per feature cluster. Per-feature functional requirements and acceptance criteria are **deferred to each feature's TDS** under `dev/active/`, because these features are gated on real usage signals (cost audits, model-swap cadence, external adapter requests) that don't exist yet. Freezing detailed AC now would over-specify work the backlog itself marks "revisit on trigger." Each cluster below names its backlog entry and its **revisit trigger** — the signal that promotes it from scope-level to a detailed TDS.

### 17.1 Reporting & analysis cluster

**Scope.** Three read-only report commands over existing schema (no migration):
- `plumb regression-eval` — variance decomposition: capability-eval (live tools) vs regression-eval (replayed/mocked tools) to isolate model stochasticity for model-swap decisions. Needs a tool-replay/transcript layer. *Backlog: "v1.1 — Variance decomposition." Trigger: model-swap cadence > 1/month.*
- `plumb report efficiency-frontier` — Pareto plot of tokens-per-resolved-task × pass-rate (the metric ships in v1.0; the frontier *analysis* is here). *Backlog: "v2 — Communication overhead / efficiency frontier." Trigger: flagship post needs the chart.*
- `plumb report router-frontier` — cost × accuracy Pareto per candidate routing policy (v1.0 routing-top-1 is a point estimate; this is the frontier). *Backlog: "v2 — Pareto-frontier router evaluation." Trigger: first routing-policy A/B test.*

**Exit criteria.** Each command emits JSON/DataFrame (PRD "no custom dashboard" still holds — charts are one-off notebooks). No schema change. The regression-eval transcript/replay layer is the only non-trivial new component and gets its own TDS.

### 17.2 Alternative judge backends cluster

**Scope.** Extend the judge layer beyond the two v1.0 adapters:
- **Judge-adapter Protocol/ABC extension seam** — the published `JudgeAdapter` Protocol becomes a *supported third-party extension point* (Bedrock / Vertex / corp gateways). This gates the two items below. *Backlog Group A "Judge adapters" + Deferred list. Trigger: a concrete third-party adapter (Bedrock/Vertex) is requested.*
- **Luna-2-style SLM judges at 100% coverage** — third adapter `plumb.adapters.judge_slm.SLMJudge` (local Ollama/vLLM small model or a hosted SLM endpoint) for cheap full-coverage judging. *Backlog: "v2 — Luna-2-style SLM judges." Trigger: judge spend > ~$10/week.*
- **Multi-judge consensus / ensembling** — run a metric through multiple providers, aggregate by majority. `scorer_version` becomes a composite; `write_score` grows a consensus step. *Backlog: "v2 — Multi-judge consensus." Trigger: single-judge α < 0.7 vs human.*
- **Streaming verdicts** — streaming `messages.create`/`chat.completions` for time-to-first-token on long rationales. *Backlog: "v2 — Streaming verdicts." Trigger: interactive judge UX need.*
- **Tool-use judges (CLI-style)** — judges that call tools/run code; depends on both the Protocol seam *and* a stable stateless judging mode (breaks `scorer_version` determinism otherwise). *Backlog: "v2 — Tool-use judges" + Group A "Agentic-CLI-backed judge adapter." Trigger: both conditions hold.*

**Exit criteria.** The Protocol/ABC seam is documented and at least one alternative backend (SLM **or** an external Protocol adapter) ships against it. Consensus/streaming/tool-use judges remain individually trigger-gated and MAY ship later within the v2.x line. Any adapter that breaks `scorer_version` determinism (tool-use, agentic CLI) MUST NOT ship until the determinism contract is reconciled (this is the standing blocker from `deferred-features.md`).

### 17.3 Long-running agent & reporting-ergonomics cluster

**Scope.**
- **Long-running-agent extension** — subgoal annotation, loop/oscillation/stagnation detection, checkpointing metrics. This is the **one v2.0 item that may require a schema change** (a `subgoals` representation); `spans.parent_span_id` + `runs.parent_run_id` are forward-compatible, but subgoal metadata may need a new additive column. Its TDS MUST decide migration vs. fold-into-spans. *Backlog: "v2 — Long-running agent extension." Trigger: first atlas component exceeds 30-min single-run duration.*
- **`plumb run stats` top-level-only display** — `--include-children` flag to suppress sub-agent child runs by default. *Backlog: "v2 — run stats top-level-only." Trigger: first complaint about child-run clutter, or >50% of runs are children.*
- **File-backed prompt edit UX** — `plumb judge prompt create/list/show` for managing `judge_prompts/`. *Backlog: "v1.1 — File-backed prompt edit UX." Trigger: user confusion about prompt-file location/versioning.*
- **WAL/SHM file permissions hardening** — chmod `*.db-wal` / `*.db-shm` to `0600` for shared-machine posture. *Backlog: "v1.1 — WAL/SHM permissions." Trigger: WAL leak report OR shared-CI use.*

**Exit criteria.** Each ships independently when its trigger fires; none blocks the others. The long-running-agent extension is the only item that may touch the schema, and if it does, it follows the DATA-MIG-2/3/4 additive-migration contract (one migration, additive, transactional, `user_version` bump) established in v1.1 — **not** a fifth table.

### 17.4 v2.0 standing constraints (still in force)

These PRD §7 non-goals remain **permanent** through v2.0 and are NOT renegotiated by any cluster above:
- **No fifth SQL table** (the four-table constraint is the thesis).
- **No runtime blocking / guardrails** (after-the-fact eval only).
- **No SaaS / multi-tenant / auth** beyond the loopback read service.
- **No custom dashboard** (reports emit JSON/DataFrame; charts are notebooks).

---

## 18. Development Phases

Engineering phases map 1:1 to PRD §10 releases (per the *Shared Nomenclature*: a Phase is an engineering tranche delivering one or more PRD Releases). Task-level breakdown for each phase is produced per-phase by the `/dev-docs-be` TRS command under `dev/active/[task-name]/`; it is NOT enumerated here.

### Phase 1 — v1.0 (shipped)

- **Goal:** Minimal measurement spine — four tables, two entry points, ten metrics, CLI, read-only HTTP, ATTACH backfill, two judge adapters.
- **Delivers Release(s):** `v1.0`.
- **Dependencies:** none.
- **Engineering Scope Summary:** `plumb/core` (entities, ports, stats), `plumb/api.py` (decorator + context manager), `plumb/adapters` (sqlite, blobstore, two judges, agentsview attach), `plumb/cli.py`, `plumb/http.py`, autocapture installers. `SCHEMA_VERSION=1`.
- **Exit Criteria:** all §13 v1.0 acceptance criteria pass; PRD §8 Tier-1 gates met; `SCHEMA_VERSION=1`, zero migrations. **Status: COMPLETE** (package 1.0.x).

### Phase 2 — v1.1 (next release)

- **Goal:** Unblock atlas integration and close silent-data-loss gaps via one additive schema migration plus the two renegotiated API additions.
- **Delivers Release(s):** `v1.1`.
- **Dependencies:** Phase 1.
- **Engineering Scope Summary:** the schema-v2 migration machinery in `plumb/adapters/_schema.py` + `storage_sqlite.py` (`_bootstrap_schema` migration arm, additive DDL, duplicate pre-check, transactional apply, `SCHEMA_VERSION=2`); `scores.rationale` + `spans.tokens_in/out` round-trip in `_score_to_row`/`_row_to_score`/`_span_to_row`/`_row_to_span`; `idx_scores_idem` UNIQUE index + `INSERT ... ON CONFLICT` write path + `idempotency_key` on `add_score`/`plumb score write`; `plumb.resume_run` third entry point + adapter `open_or_resume`; `RunHandle.add_example` fifth method. Doc updates: PRD §7/§8 already reflect the gate renegotiation; CLAUDE.md/getting_started as needed.
- **Exit Criteria:** all §15.8 acceptance criteria (AC-RESUME-*, AC-ADDEX-*, AC-MIG-*, AC-RATIONALE-1, AC-TOKENS-*, AC-IDEM-*) pass; migration is one-shot, additive, transactional, and abort-safe on duplicates (AC-MIG-3/4); `SCHEMA_VERSION=2` and schema re-frozen; all §13 v1.0 ACs still pass against a migrated database (no regression).

### Phase 3 — v1.2 (metric depth)

- **Goal:** Richer failure analysis for the flagship long-form post, with **no** schema migration.
- **Delivers Release(s):** `v1.2`.
- **Dependencies:** Phase 2 (needs the judge-throughput/concurrency path and the migrated schema in place; this is the PRD §10 dependency-driven renumber from backlog "v1.1").
- **Engineering Scope Summary:** plan-vs-execution counterfactual recipe (new judge mode writing `plan_failure`/`execution_failure` scores); MAST 14-mode tagger (judge prompt + versioned mode vocabulary in `judge_prompts/`); Krippendorff's α calibration helper in `plumb.stats` + `plumb judge calibrate` CLI; `--concurrency N` thread-pool in `plumb judge run` with serialized writes; per-metric `PLUMB_JUDGE_MODEL_<METRIC>` override cascade in `Settings`/`get_judge_adapter`. `user_version` stays `2`.
- **Exit Criteria:** all §16.7 acceptance criteria pass; MAST tagger validated against ≥ 30 human-labeled failed runs (AC-MAST-1 release gate) before any public quotation; `--concurrency` produces results identical-as-a-set to sequential (NFR-CONC-2); zero schema migration (`user_version` unchanged at 2).

### Phase 4 — v2.0 (analysis, scale & alternative judges)

- **Goal:** Reporting frontiers, alternative judge backends, judge throughput at scale, long-running-agent support — each shipping when its trigger fires.
- **Delivers Release(s):** `v2.0` (major).
- **Dependencies:** Phase 3 for the metric foundations the reports analyze; the judge-backend cluster depends on the Protocol/ABC seam shipping first.
- **Engineering Scope Summary:** report commands (`regression-eval` with a tool-replay layer, `report efficiency-frontier`, `report router-frontier`); judge-adapter Protocol/ABC extension seam → SLM judge adapter, multi-judge consensus, streaming verdicts, tool-use judges (each trigger-gated, determinism-blocked where applicable); long-running-agent extension (subgoal annotation, loop/stagnation detection — the only cluster that may require an additive migration, following the Phase 2 contract); `plumb run stats --include-children`; `plumb judge prompt` UX; WAL/SHM permission hardening. Per-feature FR/AC produced in each feature's TDS (§17 is scope-level by design).
- **Exit Criteria:** per-cluster — the reporting cluster emits JSON/DataFrame with no schema change; the judge cluster ships the documented Protocol seam + ≥ 1 alternative backend; the long-running-agent extension (if it migrates) follows the additive `user_version` bump contract and a fresh full-suite regression. The four §17.4 standing constraints (no fifth table, no guardrails, no SaaS, no dashboard) hold throughout.

---

## 19. Appendix — Follow-ups requested

These are TRD-acceptance-blocking or TRD-deferred items. Resolution is tracked outside this document.

**v1.0 (historical — resolved at v1.0 ship):**

1. **User sign-off on the ports-and-adapters deviation** from CLAUDE.md's literal three-folder mandate (§5.3 Assumption 1). *Resolved — v1.0 shipped on the ports-and-adapters layout (see `CLAUDE.md` source-code section).*
2. **Proposed follow-up edit to CLAUDE.md** to document plumb's actual convention. *Resolved — `CLAUDE.md` now documents the ports-and-adapters layout.*
3. **Rewrite of `[docker-compose.yml](../../docker-compose.yml)` and `[../3_guides/core_concepts.md](../3_guides/core_concepts.md)`** to remove the web-app framing (§8.5).
4. **First TDS** translating the v1.0 TRD into an implementation plan. *Resolved — v1.0 feature folders archived under `dev/archive/` (v1-core-and-api, v1-storage-adapter, v1-cli, v1-http, v1-judge-adapters, v1-autocapture).*

**v1.1 → v2.0 (open):**

5. **Per-phase TRS task lists.** Run the `/dev-docs-be` command per phase (Phase 2 first) to produce flat task lists under `dev/active/[task-name]/`. Phase 2 (v1.1) is the next to detail.
6. **Schema-and-metrics-v1 doc update.** When v1.1 lands, `schema-and-metrics-v1.md` should reflect the `user_version=2` additive columns (`scores.rationale`, `spans.tokens_in/out`) and the `idx_scores_idem` index, so the canonical schema doc stays authoritative.
7. **Documented manual-dedup recipe** referenced by DATA-MIG-6's abort message — a short `getting_started`/migration note showing how to resolve pre-existing duplicate score rows before a v1.1 upgrade.

---

*End of TRD — v1.0 baseline (§§1–13) + v1.1 / v1.2 / v2.0 roadmap (§§14–19).*
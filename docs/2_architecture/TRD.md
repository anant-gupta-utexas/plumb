# plumb — Technical Requirements Document (TRD)

**Status:** Draft v1 — derived from [PRD](../1_product/PRD.md) (Phase 0 → Phase 1 hand-off)
**Owner:** anant
**Last updated:** 2026-04-23
**Scope:** plumb v1 (Phase 1 ship, Week 6 target per PRD §8)

> **Reading order.** This TRD is the text-heavy specification of *what to build, what rules it follows, how well it must perform.* The **"why"** lives in `[../1_product/PRD.md](../1_product/PRD.md)`. The **canonical schema + metric derivation** lives in `[./research/schema-and-metrics-v1.md](./research/schema-and-metrics-v1.md)` — reproduced in §7 with concrete SQL types and constraints. Options considered but not shipped in v1 are tracked in `[./deferred-features.md](./deferred-features.md)`.

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

plumb exists to close the three instrumentation gaps identified in [PRD §1](../1_product/PRD.md):

1. **Acceptance is invisible** in existing agent-telemetry tools — none emit the intervention rate that DevEx teams actually want.
2. **Orchestrator-specific failures are uncategorized** — per Cemri et al.'s MAST taxonomy (arXiv:2503.13657), ~79% of multi-agent failures are specification or inter-agent misalignment, invisible to single-agent metrics.
3. **Offline and online live in different tools** — there is no minimal, public four-table reference implementation a small team can adopt in an afternoon.

The business outcome is a portfolio-grade artifact: a single framework that serves DevEx, AI/ML, and agentic-systems audiences (PRD §3) and produces publishable data inside 8 weeks of instrumentation (PRD §2).

### 2.2 Technical contribution to business outcomes

Every technical decision in this TRD ladders up to one of the PRD Tier-1 (gating) success metrics:


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


### 2.3 Tier-2 (portfolio) objectives

PRD §8 Tier-2 (GitHub stars, LinkedIn engagement, reuse signal) are aspirational, not gating. The TRD's obligation is to not *prevent* them: public repo, clean README, `pip install plumb` works on a fresh machine, quickstart runs in under a minute.

---

## 3. Functional Requirements

FR IDs are normative (`MUST`, `SHOULD`, `MAY` per RFC 2119). Each FR ties to a PRD section.

### 3.1 Public API surface

**FR-API-1 (MUST).** The public API surface is exactly two callables — `plumb.run` as a decorator and `plumb.run` as a context manager (unified via a single `Run` callable object that supports both forms, mirroring the PRD §6 examples). **No third public entry point is permitted in v1** (PRD §7 non-goal + PRD §8 Tier-1 gating metric).

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

The four tables are defined exactly as below. Schema reproduced from PRD §5 and `[./research/schema-and-metrics-v1.md](./research/schema-and-metrics-v1.md)`; this TRD adds concrete SQL types, constraints, and indexes.

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
    status              TEXT    NOT NULL CHECK (status IN ('success', 'failure', 'aborted', 'stalled')),
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

## 14. Appendix — Follow-ups requested

These are TRD-acceptance-blocking or TRD-deferred items. Resolution is tracked outside this document:

1. **User sign-off on the ports-and-adapters deviation** from CLAUDE.md's literal three-folder mandate (§5.3 Assumption 1). Blocks TRD acceptance.
2. **Proposed follow-up edit to CLAUDE.md** once (1) is approved, to document plumb's actual convention. Not done unilaterally.
3. **Rewrite of `[docker-compose.yml](../../docker-compose.yml)` and `[../3_guides/core_concepts.md](../3_guides/core_concepts.md)`** to remove the web-app framing (§8.5).
4. **First TDS (Technical Design Specification)** under `dev/active/v1-core/` translating this TRD into an implementation plan and task list per the repo workflow in `[CLAUDE.md](../../CLAUDE.md)`.

---

*End of TRD v1.*
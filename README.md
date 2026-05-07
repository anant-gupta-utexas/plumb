# plumb

> A measurement spine for orchestrator + sub-agent systems.

[![Tests](https://img.shields.io/badge/tests-568%20passing-brightgreen)](tests/)
[![Python](https://img.shields.io/badge/python-3.13%2B-blue)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

plumb captures what current agent-telemetry tools don't: **whether a human accepted the agent's output**, how the orchestrator routed, how sub-agents handed off, and what it cost to get the answer — all in one four-table SQLite schema.

---

## Why plumb

Every major observability vendor (Arize, Braintrust, LangSmith, Humanloop, Patronus) logs that the agent *ran*. None emit the intervention rate — the fraction of runs where a human had to step in. For an agentic dev workflow, that's the number that actually matters.

Three gaps drive the design:

1. **Acceptance is invisible.** Tools log execution, not acceptance. The *intervention rate* is what DevEx teams want; none of the agent tools emit it.
2. **Orchestrator failures are uncategorized.** Cemri et al.'s MAST taxonomy (arXiv:2503.13657) shows ~79% of multi-agent failures are specification or inter-agent misalignment — invisible to single-agent metrics.
3. **Offline and online live in different tools.** The industry has converged on a unified schema (Braintrust, LangSmith) but there's no minimal, public, four-table reference implementation a developer can adopt in an afternoon.

plumb is that reference implementation.

---

## What you get

- **Four-table SQLite schema** — `runs`, `spans`, `scores`, `examples`. If a signal can't be expressed in these four tables, it isn't v1.
- **Two entry points** — decorator and context manager. No class hierarchy, no plugin system, no third entry point.
- **`plumb` CLI** — `run stats`, `score write`, `example promote`, `judge run`, `serve`, `attach`, `version`.
- **Judge adapters** — Anthropic native + OpenAI-compatible (OpenRouter / Ollama / vLLM / LM Studio / LiteLLM).
- **agentsview ATTACH** — backfill from `~/.agentsview/db.sqlite` with ~200 lines of adapter, no ETL, no nightly job.
- **Ten v1 metrics** — task completion, latency, cost, tokens-per-resolved-task, tool-call validity, tool-argument hallucination, routing top-1, handoff round-trip, intervention rate, pass^3.
- **568 tests, ruff-clean, mypy strict on core.**

---

## Quick start

```bash
git clone https://github.com/anant-gupta-utexas/plumb.git
cd plumb
uv venv && source .venv/bin/activate
uv sync
pytest
```

**Decorator**

```python
from plumb import run

@run(task_id="content-pipeline.ingest", kind="online")
def ingest(url: str) -> Doc: ...
```

**Context manager**

```python
from plumb import run

with run(task_id="atlas.stage5.codegen", kind="online") as r:
    r.add_score("verify_pass", scorer="deterministic", value_label="pass")
```

**CLI**

```bash
plumb run stats --since 7d
plumb score write --run-id <id> --metric routing_top1 --scorer judge --value-label pass
plumb example promote --from-run <id> --rubric rubric.md
plumb judge run --model claude-sonnet-4-6 --metric routing_top1
```

## Schema at a glance

```
runs       (run_id, kind ∈ {offline, online}, task_id, parent_run_id?,
            orchestrator_model, sub_agent_model, prompt_version,
            git_sha, start_ts, end_ts, tokens_in, tokens_out, dollar_cost, status)

spans      (span_id, run_id, parent_span_id?,
            kind ∈ {llm, tool, subagent, handoff, plan, verify},
            name, input_hash, output_hash, tokens, latency_ms, status, error_type)

scores     (score_id, run_id, span_id?,
            metric_name, scorer ∈ {deterministic, judge, human, user_signal},
            scorer_version, value_numeric, value_label, scored_at)

examples   (example_id, task_id, inputs_hash, expected_output_hash,
            rubric, source ∈ {synthetic, production_promotion, human_authored},
            origin_run_id? → runs, active, created_at)
```

`runs.kind` unifies offline evals and production traces in one table. `scores.scorer_version` lets you detect judge drift without corrupting history. `examples.origin_run_id` closes the offline ↔ online loop: a production failure remembers the trace it came from.

## Project layout

```
plumb/
├── core/        # Pure-Python core: entities, ports (Protocols), stats
├── adapters/    # storage_sqlite, blobstore_fs, judge_*, agentsview_attach
├── autocapture/ # Monkey-patch installers for anthropic, openai, httpx
├── api.py       # Public `run` decorator + context manager
├── cli.py       # `plumb` typer-based CLI
├── http.py      # FastAPI loopback-only read service (port 8765)
└── config.py    # pydantic-settings

docs/   # PRD, TRD, SDD, guides, testing strategy
dev/    # Work-in-progress feature plans (active/ + archive/)
tests/  # unit/ + integration/ + e2e/
```

## Documentation

| What you need | Where |
|---|---|
| Product framing (problem, goals, non-goals) | [PRD](docs/1_product_and_research/PRD.md) |
| Technical requirements + acceptance criteria | [TRD](docs/2_architecture/TRD.md) |
| Architecture + data flow | [System Design](docs/2_architecture/SYSTEM_DESIGN.md) |
| Schema + metric derivation | [schema-and-metrics-v1](docs/1_product_and_research/schema-and-metrics-v1.md) |
| Deferred features (v2+) | [deferred-features](docs/2_architecture/deferred-features.md) |

## Development

```bash
ruff check .                       # lint
ruff format .                      # format
mypy --strict plumb/core/          # type-check pure core
pytest --cov=plumb                 # run tests with coverage
```

Feature workflow (plan → build → archive) is in [CLAUDE.md](CLAUDE.md). Contribution guidelines are in [CONTRIBUTING.md](CONTRIBUTING.md).

## Used by

**atlas** — the companion agent orchestrator — writes every pipeline run into plumb's four-table schema via the decorator + context manager surface.

## License

MIT — see [LICENSE](LICENSE).

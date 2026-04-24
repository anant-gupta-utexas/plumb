# plumb

**A measurement spine for orchestrator + sub-agent systems.** A small Python package plus a four-table SQLite schema that captures what current agent-telemetry tools don't: whether a human accepted the agent's output, how the orchestrator routed, how sub-agents handed off, and what it cost to get the answer.

## Overview

plumb is an opinionated reference implementation of a unified offline + online measurement framework for multi-agent systems. It ships a four-table SQLite schema (`runs`, `spans`, `scores`, `examples`), two entry points (decorator + context manager), and a `plumb` CLI. The design is prescriptive: if a signal can't be expressed in those four tables, it isn't v1.

One artifact, three audiences:

- **DevEx teams** — intervention rate, acceptance, routing quality on real dev work.
- **AI/ML engineers** — four-table schema, paired-McNemar ship decisions, statistical rigor.
- **Agentic-systems teams** — orchestrator routing, handoff round-trip, pass^k, MAST-aligned span tree.

## Quick Start

Requires **Python 3.13+** and `[uv](https://github.com/astral-sh/uv)` (or pip).

```bash
git clone https://github.com/anant-gupta-utexas/plumb.git
cd plumb
uv venv && source .venv/bin/activate
uv sync
pytest
```

plumb is a library, not an app — there is no `main` to run. Once v1 lands, usage will look like:

```python
from plumb import run

@run(task_id="content-pipeline.ingest", kind="online")
def ingest(url: str) -> Doc: ...

with run(task_id="atlas.stage5.codegen", kind="online") as r:
    r.add_score("verify_pass", scorer="deterministic", value_label="pass")
    ...
```

## Project Structure

> **Transitional note.** The `src/domain|application|infrastructure/` folders on disk are empty scaffolding from an earlier template. The authoritative layout for v1 code is the `plumb/` ports-and-adapters shape below (per [CLAUDE.md](CLAUDE.md) and [SDD §3](docs/2_architecture/SYSTEM_DESIGN.md)); the `src/` skeleton will be removed / renamed at first-code time.

```
plumb/
├── core/        # Pure-Python core: entities, ports (Protocols), stats
├── adapters/    # storage_sqlite, blobstore_fs, judge_*, agentsview_attach
├── autocapture/ # Monkey-patch installers for anthropic, openai, httpx
├── api.py       # Public `run` decorator + context manager
├── cli.py       # `plumb` typer-based CLI
├── http.py      # FastAPI loopback-only read service
└── config.py    # pydantic-settings

docs/   # Evergreen documentation (PRD, TRD, SDD, guides, testing)
dev/    # Work-in-progress feature plans (active/ + archive/)
tests/  # unit/ + integration/ + e2e/
```

## Documentation

Start here depending on what you're after:

- **Product framing** — [PRD](docs/1_product_and_research/PRD.md) (problem, goals, audiences, non-goals, success metrics)
- **What to build** — [TRD](docs/2_architecture/TRD.md) (FR/NFR IDs, SQL types + constraints, acceptance criteria)
- **How it's shaped** — [System Design](docs/2_architecture/SYSTEM_DESIGN.md) (architecture diagrams, component layout, data flow, trade-offs)
- **Schema + metric derivation** — [schema-and-metrics-v1](docs/1_product_and_research/schema-and-metrics-v1.md)
- **Decisions considered but deferred** — [deferred-features](docs/2_architecture/deferred-features.md)
- **Literature synthesis backlog** — [measurement-framework-research](docs/1_product_and_research/measurement-framework-research.md)
- **Contributor workflow** — [CLAUDE.md](CLAUDE.md) (repo signpost) and [CONTRIBUTING.md](CONTRIBUTING.md)

## Development

```bash
ruff check .                       # lint
ruff format .                      # format
mypy --strict plumb/core/          # type-check pure core
pytest --cov=plumb                 # run tests with coverage
```

Feature workflow (plan → build → archive) is described in [CLAUDE.md](CLAUDE.md#directory-structure--walkthrough). Detailed guidelines are in [CONTRIBUTING.md](CONTRIBUTING.md).

## License

MIT — see [LICENSE](LICENSE).
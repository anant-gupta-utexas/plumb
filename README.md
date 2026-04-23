# plumb

**A measurement spine for orchestrator + sub-agent systems.** A small Python
package plus a four-table SQLite schema that captures what current agent-
telemetry tools don't: whether a human accepted the agent's output, how the
orchestrator routed, how sub-agents handed off, and what it cost to get the
answer.

## Overview

plumb is an opinionated reference implementation of a unified offline + online
measurement framework for multi-agent systems. It ships a four-table SQLite
schema (`runs`, `spans`, `scores`, `examples`), two entry points (decorator +
context manager), and a `plumb` CLI. The design is prescriptive: if a signal
can't be expressed in those four tables, it isn't v1.

One artifact, three audiences:

- **DevEx teams** — intervention rate, acceptance, routing quality on real dev work.
- **AI/ML engineers** — four-table schema, paired-McNemar ship decisions, statistical rigor.
- **Agentic-systems teams** — orchestrator routing, handoff round-trip, pass^k, MAST-aligned span tree.

See [`docs/1_product/PRD.md`](docs/1_product/PRD.md) for the full product
framing and [`docs/2_architecture/research/schema-and-metrics-v1.md`](docs/2_architecture/research/schema-and-metrics-v1.md)
for the canonical schema and metric derivation.

## Features

- **Four-table schema** (`runs`, `spans`, `scores`, `examples`) — unified offline + online
- **Two entry points** — a `@run(...)` decorator and a `with run(...)` context manager
- **`plumb` CLI** — `run stats`, `score write`, `example promote`, `judge run`
- **ATTACH-based adapters** — backfill from existing agent-telemetry SQLite files (~200 LOC)
- **Clean Architecture** — three-layer separation (Domain, Application, Infrastructure)
- **Python 3.13** with full type hints (mypy), modern tooling (uv, ruff)

## Quick Start

### Prerequisites
- Python 3.13 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone https://github.com/anant-gupta-utexas/plumb.git
cd plumb

# Set up virtual environment with uv
uv venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
uv sync

# Run the application
python main.py
```

## Project Structure

```
plumb/
├── dev/          # WORK-IN-PROGRESS: Technical designs for features being built.
│   ├── active/   # Active feature development plans (TDS, tasks).
│   └── archive/  # Historical record of plans for completed features.
│
├── docs/         # EVERGREEN DOCS: The single source of truth for the project.
│   ├── 1_product/      #   "Why": PRD.md — problem, goal, audiences, non-goals, metrics.
│   ├── 2_architecture/ #   "High-Level How": system_design.md, TRD.md, research/ (schema + metrics).
│   ├── 3_guides/       #   "How-to": getting_started.md, core_concepts.md.
│   └── 4_testing/      #   "Quality": Testing strategy, scenarios, coverage.
│
├── src/          # SOURCE CODE: The plumb package itself.
│   ├── application/    #   "Use Cases": Orchestrates workflows (e.g., promote trace to example).
│   ├── domain/         #   "Business Logic": Pure entities & rules (runs, spans, scores, examples).
│   └── infrastructure/ #   "Frameworks": SQLite persistence, CLI, adapters.
│
├── tests/                 # Test suite
│   ├── unit/              # Unit tests
│   ├── integration/       # Integration tests
│   └── e2e/               # End-to-end tests
│
├── CLAUDE.md              # Project signpost and workflow guide
├── CONTRIBUTING.md        # Contribution guidelines
└── README.md              # This file
```

## Development

### Code Quality

```bash
# Lint code
ruff check .

# Format code
ruff format .

# Type checking
mypy src/
```

### Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src --cov-report=html

# Run specific test types
pytest tests/unit
pytest tests/integration
pytest tests/e2e
```

### Development Workflow

1. **Plan**: Create feature docs in `dev/active/[feature-name]/`
   - `[feature-name]-plan.md`: Technical Design Specification
   - `[feature-name]-context.md`: Context and dependencies
   - `[feature-name]-tasks.md`: Implementation checklist

2. **Build**: Implement following Clean Architecture
   - Write tests first (TDD)
   - Keep domain layer pure (no framework dependencies)
   - Use dependency injection

3. **Document**: Update `docs/` with any architectural or API changes

4. **Archive**: Move completed feature docs to `dev/archive/`

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines.

## Architecture

This project follows **Clean Architecture** principles:

### Domain Layer (`src/domain/`)
- Pure business logic
- No external dependencies
- Contains: Entities, Value Objects, Repository Interfaces, Domain Services

### Application Layer (`src/application/`)
- Use cases and orchestration
- Depends only on Domain layer
- Contains: Use Cases, DTOs, Service Interfaces

### Infrastructure Layer (`src/infrastructure/`)
- Framework-specific code
- Implements Domain interfaces
- Contains: API routes, Database implementations, External services

**Dependency Rule**: Dependencies point inward (Infrastructure → Application → Domain)

## Documentation

- **[Product Requirements (PRD)](docs/1_product/PRD.md)**: Problem, goal, audiences, non-goals, success metrics
- **[Schema & metrics v1](docs/2_architecture/research/schema-and-metrics-v1.md)**: Canonical four-table schema, metric derivation, design principles
- **[Research backlog](docs/2_architecture/research/measurement-framework-research.md)**: Literature synthesis (SPACE, DORA, DX Core 4, MAST, TRAIL, …)
- **[Getting Started Guide](docs/3_guides/getting_started.md)**: Detailed setup instructions
- **[Core Concepts](docs/3_guides/core_concepts.md)**: Clean Architecture principles
- **[Testing Guide](docs/4_testing/index.md)**: Testing strategy and best practices

## Contributing

Contributions are welcome! Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our development workflow and code standards.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Resources

- [Clean Architecture](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Python Type Hints](https://docs.python.org/3/library/typing.html)
- [uv Documentation](https://github.com/astral-sh/uv)
- [pytest Documentation](https://docs.pytest.org/)

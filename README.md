# Python Scaffolding

A modern Python project template following Clean Architecture principles.

## Overview

This project provides a solid foundation for building maintainable, testable, and scalable Python applications. It implements Clean Architecture to separate business logic from infrastructure concerns, making your codebase more resilient to change.

## Features

- **Clean Architecture**: Three-layer architecture (Domain, Application, Infrastructure)
- **Python 3.13**: Latest Python features and performance improvements
- **Type Safety**: Full type hints support with mypy
- **Modern Tooling**: uv for dependency management, ruff for linting/formatting
- **Comprehensive Documentation**: Structured docs for product, architecture, guides, and testing
- **Development Workflow**: Planning templates in `dev/` directory for feature development

## Quick Start

### Prerequisites
- Python 3.13 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Installation

```bash
# Clone the repository
git clone <repository-url>
cd python-scaffolding

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
python-scaffolding/
├── dev/          # WORK-IN-PROGRESS: Technical designs for features being built.
│   ├── active/   # Active feature development plans (TDS, tasks).
│   └── archive/  # Historical record of plans for completed features.
│
├── docs/         # EVERGREEN DOCS: The single source of truth for the project.
│   ├── 1_product/      #   "Why": Product Requirements Documents (PRD).
│   ├── 2_architecture/ #   "High-Level How": System Design, TRD, diagrams.
│   ├── 3_guides/       #   "How-to": Developer setup, core concepts, examples.
│   └── 4_testing/      #   "Quality": Testing strategy, scenarios, coverage.
│
├── src/          # SOURCE CODE: The application itself.
│   ├── application/    #   "Use Cases": Orchestrates workflows (e.g., CreateConversation).
│   ├── domain/         #   "Business Logic": Pure entities & rules (e.g., Conversation entity).
│   └── infrastructure/ #   "Frameworks": API (FastAPI), DB (SQLAlchemy), etc.
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

**Dependency Rule**: Dependencies point inward (Infrastructure � Application � Domain)

## Documentation

- **[Getting Started Guide](docs/3_guides/getting_started.md)**: Detailed setup instructions
- **[Core Concepts](docs/3_guides/core_concepts.md)**: Clean Architecture principles
- **[System Design](docs/2_architecture/system_design.md)**: High-level architecture
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
- [FastAPI Documentation](https://fastapi.tiangolo.com/)

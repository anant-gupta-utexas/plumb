# Getting Started

## Prerequisites

- Python 3.13 or higher
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

---

## Installation

### From source (development)

```bash
git clone https://github.com/anant-gupta-utexas/plumb.git
cd plumb

# Create virtual environment and install all dependencies
uv venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
uv sync
```

### As a library (once published to PyPI)

```bash
pip install plumb
# or
uv add plumb
```

---

## Quickstart: instrument your first run

The only import you need for instrumentation is `plumb.run`.

```python
from plumb import run, SpanKind

@run(task_id="hello-plumb", kind="online")
def answer_question(question: str) -> str:
    return f"The answer to '{question}' is 42."

answer_question("What is the meaning of life?")
# plumb records a Run with status="success" when the function returns
```

Or use the context manager form when you want access to the `RunHandle` (`r`) to add spans and scores:

```python
from plumb import run, SpanKind

with run(task_id="summarise", kind="online", orchestrator_model="claude-sonnet-4-6") as r:
    # Simulate an LLM call
    span_id = r.add_span(
        SpanKind.LLM,
        "generate-summary",
        latency_ms=280.0,
        tokens=(512, 128),
    )
    r.add_score("answer_relevance", "deterministic", value_numeric=0.95, span_id=span_id)
    r.set_models(orchestrator_model="claude-sonnet-4-6")
# Run, span, and score are written to storage here
```

---

## Storage

Until you wire a storage adapter, plumb uses a no-op writer — all writes are accepted and silently discarded. This means the quickstart example above runs without any database setup.

To capture data, assign a writer to `plumb.api._storage_writer`. Once the SQLite storage adapter is available:

```python
import plumb.api as _plumb_api
from plumb.adapters.storage_sqlite import StorageSQLite

_plumb_api._storage_writer = StorageSQLite(db_path="~/.plumb/plumb.db")
```

For tests, use a `FakeStorageWriter` (available in `tests/conftest.py` fixtures):

```python
class FakeStorageWriter:
    def __init__(self):
        self.runs = []
        self.scores = []

    def write_run(self, run, spans):
        self.runs.append((run, spans))

    def write_score(self, score):
        self.scores.append(score)

    def write_example(self, example):
        pass

import plumb.api as _plumb_api

fake = FakeStorageWriter()
_plumb_api._storage_writer = fake

with run(task_id="test") as r:
    r.add_span("llm", "call")

assert len(fake.runs) == 1
assert fake.runs[0][0].task_id == "test"
```

---

## Environment variables

plumb reads configuration from `PLUMB_*` environment variables. All have sensible defaults.

| Variable | Default | Purpose |
|---|---|---|
| `PLUMB_DATA_DIR` | `~/.plumb` | Root directory for SQLite DB and blobs |
| `PLUMB_LOG_LEVEL` | `WARNING` | Python logging level for plumb internals |
| `PLUMB_AUTOCAPTURE` | `false` | Enable automatic SDK monkey-patching on import |

Set them in a `.env` file or export them before running your code. Settings are read once and cached.

---

## Run the local HTTP service (optional)

plumb ships a read-only HTTP service useful for querying recorded runs from notebooks or ad-hoc scripts:

```bash
plumb serve   # binds 127.0.0.1:8765 by default
```

The service is read-only and binds to loopback only. It requires the SQLite adapter to be configured.

---

## Run tests

```bash
pytest                         # full suite
pytest tests/unit              # unit tests only
pytest tests/perf              # performance benchmarks
pytest --cov                   # with coverage report
```

---

## Code quality

```bash
ruff check .       # lint
ruff format .      # format
mypy plumb/core/   # strict type checking on the core
```

---

## Development workflow

1. Create a feature branch: `git checkout -b feature/my-feature`
2. Create planning documents in `dev/active/my-feature/` (TDS + tasks)
3. Write tests first, then implement
4. Update `docs/` to reflect any API or behaviour changes
5. Run `pytest` and `ruff check .` before opening a PR
6. After merge, move `dev/active/my-feature/` to `dev/archive/`

---

## Troubleshooting

### Virtual environment issues

```bash
deactivate
rm -rf .venv
uv venv
source .venv/bin/activate
uv sync
```

### Dependency conflicts

```bash
uv cache clean
uv sync --reinstall
```

### plumb silently drops writes

If your runs are not appearing in storage, check that `plumb.api._storage_writer` is not still the default `_NoopStorageWriter`. A quick diagnostic:

```python
import plumb.api as _api
print(type(_api._storage_writer))
# Should be your adapter class, not _NoopStorageWriter
```

---

## Next steps

- Read [Core Concepts](core_concepts.md) for a deeper look at entities, ports, and the ports-and-adapters layout
- See [Testing Guide](../4_testing/index.md) for test structure and coverage expectations
- Review the architecture docs in `docs/2_architecture/` for the full system design

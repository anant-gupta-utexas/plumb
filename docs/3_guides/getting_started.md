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

## Autocapture works automatically

With `PLUMB_AUTOCAPTURE=1` (the default), plumb automatically patches supported
SDK calls the first time a run starts. Any `anthropic` Messages call or `openai`
Chat Completions / Responses call inside a `@run` or `with run(...)` block is
captured as a `kind="llm"` span.

```python
import anthropic
from plumb import run

client = anthropic.Anthropic(api_key="sk-...")

with run(task_id="llm-summary") as r:
    client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": "Summarise this text."}],
    )
# plumb records one llm span with redacted request/response blobs
```

Opt out with `PLUMB_AUTOCAPTURE=0`, or control patching manually with
`plumb.autocapture_install()` and `plumb.autocapture_uninstall()`. Direct `httpx`
tool-call capture and full streaming response capture are follow-up slices;
streaming calls currently keep the SDK stream working and record an unsupported
stream marker span.

---

## Storage

plumb writes all data to a SQLite database and a content-addressed blob store under `$PLUMB_DATA_DIR` (default `~/.plumb/`). Both are created automatically on first use — no manual setup required.

After running the quickstart snippet above:

```bash
# Inspect the database
sqlite3 ~/.plumb/plumb.db ".tables"
# runs  scores  spans  examples

sqlite3 ~/.plumb/plumb.db "SELECT run_id, task_id, status FROM runs LIMIT 5;"

# Blob store (if any spans used input_hash / output_hash)
ls ~/.plumb/blobs/
```

### File and directory permissions

plumb enforces strict mode bits to protect your data:

| Path | Mode | Meaning |
|---|---|---|
| `~/.plumb/` | `0700` | Only you can list or enter |
| `~/.plumb/plumb.db` | `0600` | Only you can read or write |
| `~/.plumb/blobs/<ab>/` | `0700` | Only you can list or enter |
| `~/.plumb/blobs/<ab>/<cdef…>` | `0600` | Only you can read blob files |

> **iCloud / Dropbox warning:** Sync providers do not preserve POSIX mode bits. If `~/.plumb/` ends up inside a synced folder, the mode bits will not survive a round-trip, which means other users on shared machines could read your data after a sync. Keep `PLUMB_DATA_DIR` outside of any cloud-sync folder.

### Override the data directory

```bash
PLUMB_DATA_DIR=/tmp/my-plumb-test python my_script.py
```

or set it permanently in your shell profile:

```bash
export PLUMB_DATA_DIR="$HOME/.plumb"   # already the default
```

### For tests — monkeypatch the adapter

In tests, replace the singleton with a fake before the code under test runs:

```python
import plumb.api as _api

class FakeStorageWriter:
    def __init__(self):
        self.runs = []

    def write_run(self, run, spans):
        self.runs.append((run, spans))

    def write_score(self, score): pass
    def write_example(self, example): pass
    def open_run(self, *args, **kwargs): pass
    def finalize_run(self, *args, **kwargs): self.runs.append(args)

monkeypatch.setattr(_api, "_storage_writer", FakeStorageWriter())
```

---

## Environment variables

plumb reads configuration from `PLUMB_*` environment variables. All have sensible defaults.

| Variable | Default | Purpose |
|---|---|---|
| `PLUMB_DATA_DIR` | `~/.plumb` | Root directory for SQLite DB and blobs |
| `PLUMB_LOG_LEVEL` | `WARNING` | Python logging level for plumb internals |
| `PLUMB_AUTOCAPTURE` | `true` | Enable automatic SDK monkey-patching on first run |

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

If runs are not appearing in `~/.plumb/plumb.db`, check that the storage singleton was initialised. A quick diagnostic:

```python
import plumb.api as _api
print(type(_api._storage))
# Should be SQLiteStorageAdapter, not None
# (None means _init_storage_singletons has not been called yet)
```

The singleton is initialised lazily on the first `with run(...)` / `@run(...)` call. If you are inspecting the module before any run, `_storage` will be `None` — that is expected.

---

## Next steps

- Read [Core Concepts](core_concepts.md) for a deeper look at entities, ports, and the ports-and-adapters layout
- See [Testing Guide](../4_testing/index.md) for test structure and coverage expectations
- Review the architecture docs in `docs/2_architecture/` for the full system design

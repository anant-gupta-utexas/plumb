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
# Core instrumentation only (no CLI, no HTTP service):
pip install plumb

# With CLI (plumb run stats, plumb judge run, …):
pip install 'plumb[cli]'

# With read-only HTTP service (plumb serve):
pip install 'plumb[http]'

# With LLM judge adapters (Anthropic + OpenAI):
pip install 'plumb[judge]'

# Everything:
pip install 'plumb[all]'
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

## Running a judge

plumb can score recorded runs with an LLM judge. Set `PLUMB_JUDGE_PROVIDER` to
`anthropic` or `openai_compat`, place a prompt file in
`$PLUMB_DATA_DIR/judge_prompts/<metric_name>.md`, then run:

```bash
plumb judge run --metric routing_top1 --model claude-sonnet-4-6
```

### Anthropic (native SDK)

```bash
export PLUMB_JUDGE_PROVIDER=anthropic
export PLUMB_JUDGE_ANTHROPIC_API_KEY=sk-ant-...
export PLUMB_DATA_DIR=~/.plumb   # judge_prompts/ lives here

# Place your prompt:
mkdir -p ~/.plumb/judge_prompts
cat > ~/.plumb/judge_prompts/routing_top1.md <<'EOF'
You are an evaluator. Given the run output below, respond with JSON:
{"verdict": "pass" or "fail", "rationale": "<one sentence>"}
EOF

plumb judge run --metric routing_top1 --model claude-sonnet-4-6
```

### OpenAI-compatible (OpenAI / OpenRouter / Ollama / vLLM / LiteLLM)

```bash
export PLUMB_JUDGE_PROVIDER=openai_compat
export PLUMB_JUDGE_API_KEY=sk-...
export PLUMB_JUDGE_BASE_URL=https://openrouter.ai/api/v1  # omit for api.openai.com

plumb judge run --metric routing_top1 --model gpt-4o
```

### Prompt file convention

- Location: `$PLUMB_DATA_DIR/judge_prompts/<metric_name>.md`
- Content: plain text / Markdown system prompt; no special syntax required.
- Verdict contract: the model **must** reply with valid JSON containing
  `"verdict"` (`"pass"`, `"fail"`, or a float 0–1) and `"rationale"`.
- Fail-open: if the model errors or returns malformed JSON, plumb writes a
  score row with `value_label="error"` and exits 0. No run data is lost.

### Judge env vars

| Variable | Default | Purpose |
|---|---|---|
| `PLUMB_JUDGE_PROVIDER` | *(required)* | `anthropic` or `openai_compat` |
| `PLUMB_JUDGE_ANTHROPIC_API_KEY` | `None` | API key for `provider=anthropic` |
| `PLUMB_JUDGE_API_KEY` | `None` | API key for `provider=openai_compat` |
| `PLUMB_JUDGE_BASE_URL` | `None` | Base URL override (OpenRouter, Ollama, …) |
| `PLUMB_JUDGE_MODEL` | `claude-sonnet-4-6` | Default model (overridable via `--model`) |

---

## Run the local HTTP service (optional)

plumb ships a read-only HTTP service useful for querying recorded runs from notebooks or ad-hoc scripts:

```bash
plumb serve                          # binds 127.0.0.1:8765 by default
plumb serve --port 9000              # custom port
plumb serve --host 0.0.0.0 --port 9000  # ⚠ non-loopback — see security note below
```

The service exposes five endpoints. All are GET-only — no writes are possible through HTTP.

### `GET /health` — liveness probe

```bash
curl -s http://127.0.0.1:8765/health
# {"status":"ok"}
```

### `GET /runs` — paginated run list

```bash
# All runs (default limit=100)
curl -s http://127.0.0.1:8765/runs | python3 -m json.tool

# Last 7 days, offline runs only, page 2
curl -s "http://127.0.0.1:8765/runs?since=7d&kind=offline&limit=50&offset=50"

# Filter to a specific task
curl -s "http://127.0.0.1:8765/runs?task_id=summarise&limit=20"
```

Query parameters: `since` (ISO-8601 or relative: `7d`, `2w`, `1h`, `30m`), `task_id`, `kind` (`offline`|`online`), `limit` (1–500, default 100), `offset` (default 0).

### `GET /runs/{run_id}` — run detail with spans and scores

```bash
# Replace <run_id> with a 32-char lowercase hex ID from /runs
curl -s http://127.0.0.1:8765/runs/a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4 | python3 -m json.tool
```

The response includes the run row, all spans (root spans first, then by `parent_span_id`/`span_id`), and all scores. Span `input_hash` and `output_hash` are 64-char hex SHA-256 values — blob bodies are never inlined. To read a blob:

```bash
# Blob files live at: $PLUMB_DATA_DIR/blobs/<sha[:2]>/<sha[2:]>
# Example for hash aabbcc...ff (64 chars):
cat ~/.plumb/blobs/aa/bbcc...ff
```

### `GET /examples` — regression-set examples

```bash
# All examples
curl -s http://127.0.0.1:8765/examples

# Active examples for a specific task
curl -s "http://127.0.0.1:8765/examples?task_id=summarise&active=true"
```

Query parameters: `task_id`, `active` (`true`|`false`). No pagination — the examples table is intentionally bounded in v1.

### `GET /stats/task/{task_id}` — aggregated task statistics

```bash
# v1 ten-metric cut for a task
curl -s http://127.0.0.1:8765/stats/task/summarise | python3 -m json.tool

# Restrict to the last 30 days
curl -s "http://127.0.0.1:8765/stats/task/summarise?since=30d"
```

Returns run-level metrics (latency p50/p95, dollar cost, tokens, completion rate, intervention rate) and scored metrics (tool call validity, routing top-1, etc.) for the task. Returns 404 if no runs match the window.

### Interactive API docs

With the server running, open these in a browser:

- **Swagger UI** — <http://127.0.0.1:8765/docs>
- **ReDoc** — <http://127.0.0.1:8765/redoc>
- **OpenAPI JSON** — <http://127.0.0.1:8765/openapi.json>

### Security note

The service binds to `127.0.0.1` only by default. No authentication is implemented because loopback-only + single-user machine + read-only endpoints is the accepted security posture for plumb's "No SaaS, single-user" constraint — see [TRD §5.3 Assumption 3](../2_architecture/TRD.md#53-assumptions). If you expose the service on a non-loopback interface (`--host 0.0.0.0`), all local network users can read your run data; add your own reverse proxy with authentication if this is unacceptable.

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
- Read [Orchestrator Handoff Patterns](orchestrator_handoff.md) for multi-process and cross-process run wiring
- See [Testing Guide](../4_testing/index.md) for test structure and coverage expectations
- Review the architecture docs in `docs/2_architecture/` for the full system design

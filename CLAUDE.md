# plumb

`A measurement spine for orchestrator + sub-agent systems: four-table SQLite schema with decorator + context-manager entry points, for DevEx / AI-ML / agentic-systems teams.`

This document is the central "signpost" for our repository. It provides quick setup commands, links to our core documentation library, and explains our development workflow.

## Virtual Environment (Claude Agent Rule)

**Always activate the venv using its absolute path before running any Python or shell command.** Worktrees do not inherit the shell's activated venv, so relative `source .venv/bin/activate` will fail with "no such file or directory".

```bash
source /Users/anant/PersonalProjects/plumb/.venv/bin/activate
```

This applies at the start of every worktree session — run it before `pytest`, `ruff`, `python`, `uv`, or any other tool that requires the project environment.

## Quick Start: Developer Setup
```bash
# 1. Set up the virtual environment and install dependencies
source /Users/anant/PersonalProjects/plumb/.venv/bin/activate
uv sync

# 2. Run the local read-only HTTP service (optional; notebooks / ad-hoc queries)
plumb serve   # binds 127.0.0.1:8765 by default

# 3. Run local tests
pytest
```

## Directory Structure & Walkthrough

### Core Documentation (`docs/`)
**EVERGREEN DOCS**: The single source of truth for the project.
```
docs/
├── 1_product_and_research/ # "Why": Product Requirements (PRD.md) + research docs
├── 2_architecture/         # "High-Level How": System Design, TRD, diagrams
├── 3_guides/               # "How-to": Developer guides (getting_started.md, core_concepts.md)
└── 4_testing/              # "Quality": Testing strategy (index.md, unit_tests.md)
```

### Development Documentation (`dev/`)
**WORK-IN-PROGRESS**: Technical designs and planning for features being built.
```
dev/
├── active/   # Active feature development plans (TDS, tasks)
└── archive/  # Historical record of completed features
```

**Dev Workflow:**
1. **Start Planning**: Create `dev/active/[feature-name]/`
2. **Define the Spec**: Create inside your feature folder:
   * `[feature-name]-plan.md` - Technical Design Specification (TDS)
   * `[feature-name]-context.md` - Key decisions, dependencies, files to touch
   * `[feature-name]-tasks.md` - Progress checklist
3. **Build**: Get TDS reviewed, then implement
4. **Update Core Docs**: Update `docs/` to reflect changes (part of Definition of Done)
5. **Archive**: Move folder from `dev/active/` to `dev/archive/` after merge

### Source Code (`plumb/`)
**Ports-and-adapters** layout — a recognized expression of Clean Architecture, chosen over the literal `domain/application/infrastructure` three-folder split because plumb is a ~2–3k LOC library whose business logic is schema writes + SQL queries + stats helpers. Architectural framing rationale: see [docs/2_architecture/SYSTEM_DESIGN.md §3 & §10](docs/2_architecture/SYSTEM_DESIGN.md) and [TRD §5.3 Assumption 1](docs/2_architecture/TRD.md).
```
plumb/
├── core/           # Pure-Python core (no I/O): entities, ports (Protocols), stats helpers
│   ├── entities.py # Run, Span, Score, Example (frozen dataclasses)
│   ├── ports.py    # StorageWriter, StorageReader, JudgeAdapter, BlobStore, Clock, IdGenerator
│   └── stats.py    # Paired McNemar + Benjamini-Hochberg FDR
├── api.py          # Public `run` (decorator + context manager, sync + async); Run handle
├── cli.py          # typer-driven CLI (run stats, score write, example promote, judge run, serve, attach)
├── http.py         # FastAPI read-only service bound to 127.0.0.1:8765
├── autocapture/    # Import-time monkey-patch installers (anthropic, openai, httpx)
├── adapters/       # Port implementations (depend on core; core never imports these)
│   ├── storage_sqlite.py          # STRICT tables, WAL mode, foreign_keys=ON
│   ├── blobstore_fs.py            # Content-addressed filesystem (mode 0600/0700)
│   ├── judge_anthropic.py         # Native Anthropic SDK adapter
│   ├── judge_openai_compat.py     # OpenAI / OpenRouter / Ollama / vLLM / LM Studio / LiteLLM
│   └── agentsview_attach.py       # ≤200 LOC ATTACH-based historical backfill
└── config.py       # pydantic-settings env-var config
```

**Key Principles** (apply to `plumb/core/` inward; adapters depend on ports, never the reverse):
* Dependency Inversion: Inner layers define interfaces, outer layers implement
* Single Responsibility: Each component has one reason to change
* Testability: Pure business logic independent of frameworks
* Immutability: Use frozen dataclasses for domain entities, never mutate existing objects
* Security-First: Validate all inputs, no hardcoded secrets, parameterized queries only

## Coding Style

- Frozen `dataclass(frozen=True)` for domain entities; `pydantic.BaseModel` for API schemas
- Functions < 50 lines, files < 400 lines (800 max)
- No deep nesting (> 4 levels) — use early returns and extract helpers
- Use `pydantic_settings.BaseSettings` for configuration, never `os.environ` directly

## Error Handling

- Custom exception hierarchy per domain (`DomainError` → `NotFoundError`, `ValidationError`, etc.)
- Never silently swallow errors
- Log detailed context server-side, return user-friendly messages in API responses
- Use FastAPI exception handlers for consistent error response format

## Security Checklist

Before every commit, verify:
- No hardcoded secrets (API keys, passwords, tokens)
- All user inputs validated (Pydantic schemas at API boundary)
- SQL injection prevention (SQLAlchemy parameterized queries)
- Authentication/authorization verified on all protected routes
- Rate limiting on public endpoints
- Error messages don't leak internal details (stack traces, DB errors)

## Anti-Patterns (Avoid)

- Never use Pydantic V1 APIs (`class Config:`, `.dict()`, `.json()`) — use V2 equivalents
- Never put business logic in API routers — use application layer use cases
- Never import domain from infrastructure (dependency rule violation)
- Never commit `.env` files or hardcoded credentials

## Agent Working Rules (Lessons Learned)

These rules exist because we've already paid the cost. Re-read them before any non-trivial change.

### 1. Tests assert behavior — never edit a test to make it green

When a test fails, the default assumption is **the production code is wrong**, not the test. Before changing any test:

- **Read the test's docstring / AC reference** (e.g. `FR-GRAPH-1`, `NFR-Rel-1`). The test is encoding a requirement.
- **Reproduce the failure and trace the root cause** in the production code path. State the root cause in plain English before touching anything.
- A test edit is only legitimate when:
  1. The requirement itself changed (cite the PRD / TRD / task delta), **or**
  2. The test was asserting an implementation detail that has been refactored away (cite the new contract), **or**
  3. The test had a genuine bug (wrong fixture, race, stale mock target) — and you can name it.
- If you find yourself "weakening" an assertion (`assert len(rows) >= 1` instead of `== 2`, removing a field check, swapping `==` for `in`) **stop**. That is the smell of hiding a bug. Fix the production code instead.
- Mocks/patches must target the **call site the production code actually uses**. When the API surface changes (e.g. `write_run` → `finalize_run`), update the patch target as part of the same commit that changed the production call — not after the test fails.
- Fakes (`FakeStorageWriter`, etc.) must implement the **full current protocol**. When the port grows a method, the fake grows with it in the same commit.

### 2. Never `git stash` mid-task — branch instead

`git stash` + `git stash pop` silently lost in-progress changes to `plumb/api.py` during Phase 6 and forced a full re-implementation of the lazy singletons + two-phase `__enter__` / `__exit__`. Stash is unsafe whenever:

- Multiple files are mid-edit.
- A pop could conflict with anything (it will, and the resolution is invisible).
- You plan to switch context for more than a few seconds.

**Use these instead:**

- **Just commit.** A WIP commit on the current branch is recoverable; a lost stash is not. Squash before PR.
  ```bash
  git add -A && git commit -m "wip: <what you were doing>"
  ```
- **Spin a scratch branch** for genuine experiments:
  ```bash
  git switch -c wip/<topic>
  ```
- If you must stash, stash **one file at a time with a message**, verify with `git stash list`, and pop **immediately** in the same shell — never across tool restarts:
  ```bash
  git stash push -m "<why>" -- <single/file/path>
  git stash pop  # same session, same shell, no other edits in between
  ```
- After any `git stash pop`, **always** run `git diff` against the file(s) you expected to restore and confirm the restored hunks are present **before** running tests or making further edits.

### 3. Verify the working tree before declaring done

Before saying "all tests pass" or marking a task complete:

1. `git status` — no unintended modifications.
2. `git diff --stat` — the changed files match the task's expected scope.
3. Re-run the **full** relevant test suite (`pytest`), not just the file you were editing.
4. `ruff check .` and `ruff format --check .` — fix what you introduced; don't paper over with `# noqa` unless the suppression is genuinely required (and comment why on the same line).
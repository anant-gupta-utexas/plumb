---
project: plumb
status: building
phase: v1 (Phase 1, Week 3)
last_updated: 2026-04-24
next_gate: v1.0 tag — schema stable, atlas path-install ready
blocked_on: null
---

# plumb — status

## Current

v1 core + API complete. `plumb/core/` (entities, ports, stats, errors) and
`plumb/api.py` (sync+async decorator + context-manager) shipped with full
test coverage (≥90%) and performance gates (p95 ≤1ms span overhead, cold
import ≤200ms). Next: storage adapter (SQLite), CLI, HTTP service, and
judge adapters to unlock end-to-end integration with atlas.

## Recent (last 7 days)

- v1-core-and-api: all 8 phases complete (Phase 1–7 in dev, Phase 8 docs).
- Implemented `Run`, `Span`, `Score`, `Example` frozen dataclasses with
  invariant validation; `Clock`, `IdGenerator`, `StorageWriter`,
  `StorageReader`, `BlobStore`, `JudgeAdapter` Protocols.
- `@run` decorator + `with run(...) as r:` for sync + async; `RunHandle`
  methods (`add_span`, `add_score`, `set_models`, `abort`) fully wired.
- McNemar's paired test + Benjamini-Hochberg FDR pure-function stats.
- CI gates: ruff format/check, mypy --strict, pytest with 90% coverage,
  perf benchmarks, cold import ≤200ms warn / 400ms fail.

## Next

- Implement v1-storage-adapter: SQLite STRICT tables, WAL mode, foreign
  keys enforcement; replace in-memory fake with real `StorageWriter`.
- Implement v1-autocapture: monkey-patch hooks for `anthropic`, `openai`,
  `httpx` SDKs to auto-capture spans.
- Implement v1-cli: typer commands for `stats`, `serve`, `judge run`.
- Implement v1-http: FastAPI read-only service (port 8765).
- Implement v1-judge-adapters: Anthropic + OpenAI/OpenRouter compat.
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- Atlas Day 2 integration is the acceptance signal for plumb v1.0. Unblocked.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/system_design.md`
- Active work: `dev/active/`

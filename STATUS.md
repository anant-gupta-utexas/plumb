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

Scaffold and docs complete. PRD, TRD, and SDD are in place. v1 schema
(`runs`, `spans`, `scores`, `examples`) is defined. Core Python package
structure is laid out under Clean Architecture. Focus is on making the
package installable as a local path dependency so atlas can pin to a
commit SHA in its `pyproject.toml`.

## Recent (last 7 days)

- SDD added: ports-and-adapters layout documented, v1 schema locked.
- TRD added: NFRs, integration contract, deferred-features backlog.
- Docs structure aligned to `1_product_and_research` / `2_architecture`
  / `3_guides` / `4_testing` pattern.

## Next

- Implement `runs` / `spans` / `scores` / `examples` write path via
  decorator + context-manager API.
- Expose `plumb.api` surface atlas will call directly (in-process).
- Tag `v1.0` once atlas Day 2 integration test passes end-to-end.

## Blocked / waiting

- Atlas Day 2 integration is the acceptance signal for plumb v1.0. Unblocked.

## Pointers

- PRD: `docs/1_product_and_research/PRD.md`
- TRD: `docs/2_architecture/TRD.md`
- SDD: `docs/2_architecture/system_design.md`
- Active work: `dev/active/`

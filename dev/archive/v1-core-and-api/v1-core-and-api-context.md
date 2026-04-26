# Context — `plumb/core/` + `plumb/api.py` TRS

**Companion to** [`v1-core-and-api-plan.md`](./v1-core-and-api-plan.md) | **Created:** 2026-04-25 | **Owner:** anant

---

## 1. Key files this slice touches

### 1.1 To delete (legacy `src/` Clean-Architecture scaffold)

The repo currently has a stub `src/` tree from an old project template. Per [TRD §5.3 Assumption 1](../../../docs/2_architecture/TRD.md#53-assumptions), plumb uses ports-and-adapters under `plumb/`, not `src/domain/application/infrastructure`. Deletion list:

- `src/__init__.py`
- `src/application/__init__.py`, `src/application/dtos/__init__.py`, `src/application/use_cases/__init__.py`
- `src/domain/__init__.py`, `src/domain/entities/__init__.py`, `src/domain/repositories/__init__.py`, `src/domain/services/__init__.py`
- `src/infrastructure/__init__.py`, `src/infrastructure/api/__init__.py`, `src/infrastructure/database/__init__.py`
- `tests/unit/domain/__init__.py`, `tests/unit/application/__init__.py`

`main.py` at repo root: keep as-is unless it references `src.*` (verify in Phase 1 Task 1.1).

### 1.2 To create (new `plumb/` package)

```
plumb/__init__.py
plumb/api.py
plumb/config.py
plumb/core/__init__.py
plumb/core/entities.py
plumb/core/ports.py
plumb/core/stats.py
plumb/core/errors.py
```

### 1.3 To modify (existing repo files)

- `pyproject.toml` — add `[tool.hatch.build.targets.wheel]` `packages = ["plumb"]`; add `pydantic`, `pydantic-settings` runtime deps; configure `[tool.ruff]` and `[tool.mypy]` (strict for `plumb/core/`).
- `tests/conftest.py` — strip any `from src.* import` lines if present; add the three shared fakes (`FakeClock`, `FakeIdGenerator`, `FakeStorageWriter`).
- `docs/3_guides/core_concepts.md` — Phase 8 Task 8.1 rewrite around plumb's actual shape (currently web-app-shaped per [TRD §8.5](../../../docs/2_architecture/TRD.md#85-follow-up-work)).
- `docs/3_guides/getting_started.md` — Phase 8 Task 8.2 quickstart for `@run`.

### 1.4 NOT to touch in this slice

- `docker-compose.yml` (TRD §8.5 — separate follow-up).
- `STATUS.md`, `README.md`, `CLAUDE.md` — out of slice.
- Anything under `docs/2_architecture/` — TRD/SDD/deferred-features are upstream of this TRS, not downstream.

---

## 2. Decisions made

### 2.1 Component-first scoping (Q1 = B)

Rather than a single full-system TRS, each component slice gets its own folder under `dev/active/`. This slice is the foundation; six follow-ups defined in plan §14.

**Why:** the core's contracts (Protocols, entities) are the load-bearing seams that downstream slices implement. Specifying them precisely first prevents adapter rework. Also keeps each TRS document actionable — a 30-page mega-doc is not.

### 2.2 Explicit `src/` → `plumb/` migration plan (Q2 = A)

Phase 1 deletes the legacy scaffold before creating the new layout. Listed in §1.1 above.

**Why:** leaving the old `src/` tree around invites accidental imports and confuses `mypy`/`ruff`'s file discovery. Better to delete in a focused commit so reviewers can see the boundary.

### 2.3 Dependency-ordered phases (Q3 = A)

Phase 1: skeleton → Phase 2: entities → Phase 3: ports + stats → Phase 4: config → Phase 5: sync API → Phase 6: async API → Phase 7: perf gates → Phase 8: docs.

**Why:** each phase produces a working, testable slice. The performance benchmark (Phase 7) needs the full API surface, so deferring it past Phase 6 is correct. Risk-ordering would have moved Phase 7 earlier, but the perf benchmark needs `add_span` to *exist* — there's no useful benchmark without it.

### 2.4 Entities use `dataclass(frozen=True, slots=True)`, not Pydantic

Following CLAUDE.md guidance: "Frozen `dataclass(frozen=True)` for domain entities; `pydantic.BaseModel` for API schemas." Performance also matters — `dataclass+slots` is roughly 5× faster to instantiate than a Pydantic model, which matters for the 1 ms `add_span` budget.

`Settings` and `JudgeResult` use Pydantic because they cross system boundaries (env vars and HTTP responses respectively).

### 2.5 No SciPy dependency for stats

The chi-squared df=1 CDF reduces to `erf(sqrt(x/2))`, which is in stdlib `math`. McNemar and BH-FDR are both implementable in pure Python without numerical headaches at the sample sizes plumb cares about (200 tasks). Avoiding SciPy keeps cold-import budget healthy and reduces wheel size.

### 2.6 In-memory `FakeStorageWriter` for testing this slice

The storage TRS will deliver the real SQLite adapter. This slice's tests use a list-based fake. Trade-off:
- **Pro:** unit tests stay pure (no SQLite, no temp files); fast (≤ 5 s for the perf benchmark).
- **Con:** the 1 ms NFR-Perf-1 measurement against the fake is *optimistic*. The real measurement happens against SQLite WAL in storage TRS.

This is the right trade-off because: (a) the fake establishes a *floor* for `add_span` overhead — if it's already over 1 ms with no I/O, the SQLite adapter won't save it; (b) splitting the perf check between slices keeps each TRS's CI gate self-contained.

### 2.7 Module-level singletons for clock/id_gen/storage in `plumb/api.py`

Resolved (§3.1 below). Implementation: `plumb.api._clock`, `_id_gen`, `_storage_writer` populated lazily on first use; tests substitute fakes via `monkeypatch.setattr`.

---

## 3. Decisions resolved (signed off 2026-04-25)

All four design questions in this section were posed for reviewer input and resolved on 2026-04-25 with the recommended options. Captured here with full rationale so future readers see *why* each was picked, not just *what*.

### 3.1 API dependency-injection pattern → **A (module-level singletons)**

`plumb/api.py` needs a `Clock`, an `IdGenerator`, and a `StorageWriter`. Three options were considered:

| Option | Pattern | Pros | Cons |
|---|---|---|---|
| **A — Module-level singletons (CHOSEN)** | `plumb.api._clock`, `_id_gen`, `_storage_writer` populated lazily on first use; tests `monkeypatch.setattr(api, "_clock", FakeClock())` | Zero ceremony; matches `requests`/`httpx` defaults pattern; trivial test setup | Implicit; harder to swap per-call |
| B — Explicit DI container | `plumb.runtime.Container` holding all deps; `run` reads from it | Explicit; user could swap per-process | Overbuild for ~6 dependencies; adds a third public type to learn |
| C — Per-call kwargs | `run(task_id=..., _clock=..., _writer=...)` | Fully explicit | Pollutes public API; users have to import internals |

**Rationale for A:** TRD doesn't mandate a style; A is the smallest viable thing and matches Python library convention. The tests already use `monkeypatch.setattr` cleanly via the `configured_api` fixture in plan §10.3.

### 3.2 `RunHandle` importable for type hints → **A (public for types, with construct guard)**

| Option | Pros | Cons |
|---|---|---|
| **A — Public for types only (CHOSEN)** | Users can annotate; runtime guard in `__init__` raises if user constructs directly, so it's not an alternative entry point | One more name in `__all__` |
| B — Stay private | Smallest public surface | Users have to use `Any` or `# type: ignore` |

**Rationale for A:** AC-API-1 is about *instrumentation* entry points; a type alias with a "you can't construct this" guard satisfies the spirit. Implementation: `RunHandle.__init__` requires a non-None `_builder` argument and raises `TypeError("RunHandle is not user-constructible; obtain one via `with run(...) as r:`")` otherwise. The runtime guard is the load-bearing piece — it converts the type from "alternate entry point" into "type alias only."

### 3.3 `r.abort()` flush vs discard buffered spans → **A (flush partial buffer)**

[TRD FR-EDGE-5](../../../docs/2_architecture/TRD.md#38-edge-cases-and-error-behaviour) says "skipping any remaining auto-capture" but is silent on already-buffered spans.

| Option | Behavior | Trade-off |
|---|---|---|
| **A — Flush partial buffer (CHOSEN)** | Write `Run` row + already-captured spans; `status='aborted'`, `error_type=reason` | Preserves forensic trace; matches "aborted" intent |
| B — Discard everything | Empty `Run` row with `status='aborted'` | Cleaner but loses data |

**Rationale for A:** the whole point of `aborted` vs `failure` is that the user explicitly chose to stop — they probably want the partial trace. "Skipping any remaining auto-capture" means *future* spans (post-`abort()`) are no-ops; already-buffered spans are kept.

### 3.4 Cold-import gate: hard-fail vs warn → **B (warn at 200 ms, fail at 400 ms)**

[NFR-Perf-6](../../../docs/2_architecture/TRD.md#41-performance) is **SHOULD** in TRD.

| Option | Behavior | Pros |
|---|---|---|
| A — Hard fail at 200 ms | CI fails | Strong signal |
| **B — Warn at 200 ms, fail at 400 ms (CHOSEN)** | Reviewer sees the warning; only catastrophic regressions break CI | Matches NFR-Perf-1's 2× headroom convention; SHOULD-level NFRs deserve warnings, not hard fails |

**Rationale for B:** SHOULD-level NFRs deserve warnings, not hard fails; 2× headroom is consistent with NFR-Perf-1's CI tolerance.

### 3.5 Items NOT pending (firm via TRD/SDD)

- Frozen dataclasses for entities (CLAUDE.md mandate).
- `JudgeResult` lives in `entities.py` (symmetry with other dataclasses; `JudgeAdapter` Protocol in `ports.py` referencing it works via Python forward-refs).
- Python 3.13+ floor (NFR-Use-1).

---

## 4. Dependencies on other systems / TRSes

### 4.1 Upstream (this slice depends on)

- **TRD v1** — full normative spec ([docs/2_architecture/TRD.md](../../../docs/2_architecture/TRD.md))
- **SDD v1** — architecture + sequence diagrams ([docs/2_architecture/SYSTEM_DESIGN.md](../../../docs/2_architecture/SYSTEM_DESIGN.md))
- **schema-and-metrics-v1.md** — column-by-column rationale ([docs/1_product_and_research/schema-and-metrics-v1.md](../../../docs/1_product_and_research/schema-and-metrics-v1.md))
- **deferred-features.md** — design alternatives considered ([docs/2_architecture/deferred-features.md](../../../docs/2_architecture/deferred-features.md))

### 4.2 Downstream (consume this slice's outputs)

- `dev/active/v1-storage-adapter/` — implements `StorageWriter`, `StorageReader`, `BlobStore`. Replaces `FakeStorageWriter` in real `plumb.api` runtime.
- `dev/active/v1-autocapture/` — calls `RunHandle.add_span(...)` from monkey-patched `anthropic`/`openai`/`httpx`.
- `dev/active/v1-cli/` — reads via `StorageReader`; uses `plumb.core.stats` for regression report.
- `dev/active/v1-http/` — reads via `StorageReader`.
- `dev/active/v1-judge-adapters/` — implements `JudgeAdapter` (Anthropic native + OpenAI-compatible).
- `dev/active/v1-attach-adapter/` — uses `StorageWriter` directly via `INSERT INTO ... SELECT` from ATTACHed `agentsview` DB.

---

## 5. Integration points

### 5.1 Outside this slice → into this slice

Nothing — this slice is the foundation; nothing yet exists upstream of it (besides docs).

### 5.2 Inside this slice → out (interfaces other slices will hold against)

- **`StorageWriter` Protocol** in `plumb/core/ports.py`. Storage TRS implements three methods: `write_run`, `write_score`, `write_example`.
- **`StorageReader` Protocol** in `plumb/core/ports.py`. Storage + CLI/HTTP TRSes use this.
- **`JudgeAdapter` Protocol** in `plumb/core/ports.py`. Judge-adapter TRS implements two adapters.
- **`BlobStore` Protocol** in `plumb/core/ports.py`. Storage TRS implements; autocapture TRS uses (for handoff hashing).
- **`Clock` and `IdGenerator` Protocols** in `plumb/core/ports.py`. Default impls in `plumb/api.py` (uuid + datetime); tests substitute fakes.
- **`RunHandle` (semi-public)** in `plumb/api.py`. Autocapture TRS uses `_active_run.get()` to find the current handle and call `.add_span(...)` on it.
- **Entities** in `plumb/core/entities.py`. CLI/HTTP TRSes serialize them to JSON; storage TRS persists them.

### 5.3 Stable contracts vs internal

| Surface | Stability | Notes |
|---|---|---|
| `plumb.run` | Stable (semver) | Public — TRD AC-API-1 enforces |
| `plumb.{Run, Span, Score, Example, ...}` entities | Stable for type hints | Frozen dataclasses; constructor args are part of the contract |
| `plumb.{PlumbError, ...}` | Stable | Catchable by users |
| `RunHandle` methods (`add_score`, `add_span`, `set_models`, `abort`) | Stable (FR-API-4) | Adding a method = minor bump; removing = major |
| Module-level singletons (`plumb.api._clock`, etc.) | **Internal** | May refactor to a container later; tests use them via `monkeypatch` |
| `_RunFactory`, `_RunBuilder` | Internal | Implementation detail |
| `_active_run` ContextVar | **Stable for autocapture TRS only** | The autocapture monkey-patches will call `_active_run.get()`; this is documented as the integration point |

---

## 6. Smaller decisions (signed off 2026-04-25)

Three additional items resolved on 2026-04-25:

1. **`plumb.__version__` source → hardcoded for now.** `__version__ = "0.1.0"` literal in `plumb/__init__.py`. Switch to `importlib.metadata.version("plumb")` when we ship the first PyPI release. Saves a startup-time `metadata` query that costs ~5 ms (relevant to NFR-Perf-6).

2. **`StorageWriter.write_run` signature → separate args.** `write_run(run: Run, spans: Sequence[Span]) -> None` — no wrapper class. Simpler to test; the storage TRS implements the single-transaction guarantee at the adapter level.

3. **`tests/regression/` placeholder → defer to CLI TRS.** The 200-task regression set ([TRD §10.4](../../../docs/2_architecture/TRD.md#104-regression-gate-on-the-200-task-set-week-6)) needs the `pytest tests/regression/` runner that the CLI TRS will add. This slice doesn't need it.

---

*End of context doc.*

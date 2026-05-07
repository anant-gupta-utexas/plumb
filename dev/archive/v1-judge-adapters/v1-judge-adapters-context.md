# Context — v1 Judge Adapters

**Plan:** [`v1-judge-adapters-plan.md`](./v1-judge-adapters-plan.md)
**Tasks:** [`v1-judge-adapters-tasks.md`](./v1-judge-adapters-tasks.md)
**Last updated:** 2026-04-30

---

## 1. Why this slice exists

The TRD specifies two `JudgeAdapter` implementations under `plumb/adapters/` that satisfy `plumb.core.ports.JudgeAdapter`. The CLI slice (already merged) wired `plumb judge run` against an `_load_judge_adapter()` stub that raises `NotImplementedError`. This slice replaces that stub.

This slice is on the **critical path** for the Week-6 PRD Tier-1 metric *"CI regression gate with paired McNemar on 200-task set"* — without working judge adapters, the regression gate cannot run.

---

## 2. Files this slice touches

### 2.1 New files (production)

| File | Purpose | LOC target |
|---|---|---|
| `plumb/_prompt_loader.py` | `load_prompt(metric_name)` → `(text, sha8)` | ≤ 50 |
| `plumb/adapters/_judge_common.py` | Retry, redaction, error types, reply parser | ≤ 150 |
| `plumb/adapters/judge_anthropic.py` | `AnthropicJudge` | ≤ 200 |
| `plumb/adapters/judge_openai_compat.py` | `OpenAICompatibleJudge` | ≤ 200 |

### 2.2 Modified files (production)

| File | Change |
|---|---|
| `plumb/adapters/__init__.py` | Add `get_judge_adapter()` factory |
| `plumb/config.py` | Add 5 `judge_*` fields to `Settings` |
| `plumb/cli.py` | Replace `_load_judge_adapter()` stub; pass `metric` as `metric_name` |
| `pyproject.toml` | Add `tenacity>=9.0` |

### 2.3 New files (tests)

| File | Purpose |
|---|---|
| `tests/unit/test_prompt_loader.py` | Prompt-loading + SHA + path-traversal guard |
| `tests/unit/adapters/test_judge_common_retry.py` | Tenacity wiring, exception classification |
| `tests/unit/adapters/test_judge_common_redact.py` | Header + body redaction |
| `tests/unit/adapters/test_judge_parse_reply.py` | Reply parsing + Hypothesis property test |
| `tests/unit/adapters/test_judge_anthropic.py` | Anthropic adapter — happy + error branches |
| `tests/unit/adapters/test_judge_openai_compat.py` | OpenAI-compat adapter — happy + error branches + base-URL HTTP-level test |
| `tests/unit/adapters/test_judge_factory.py` | `get_judge_adapter()` provider switch + lazy-import |
| `tests/cli/test_cli_judge_run.py` | End-to-end CLI integration (closes CLI plan T3.1) |
| `tests/helpers/fake_judge.py` | `FakeJudgeAdapter` reusable across slices |

### 2.4 Modified files (tests)

| File | Change |
|---|---|
| `tests/unit/test_config.py` | Add tests for new `judge_*` Settings fields |
| `tests/perf/test_cold_import.py` | Assert `anthropic` / `openai` not loaded after `import plumb` |

---

## 3. Decisions made (during clarification round, 2026-04-30)

| # | Decision | Picked | Rationale |
|---|---|---|---|
| 1 | Prompt loading | **CLI/factory-owned** | Adapters stay thin HTTP wrappers; `scorer_version` composed in one place. |
| 2 | `scorer_version` ownership | **Adapter computes** | Matches INT-JUDGE-6 contract at the adapter boundary. |
| 3 | Retry library | **`tenacity` ≥ 9.0** | User-confirmed; avoids 30 LOC of custom retry; well-maintained. |
| 4 | `_load_judge_adapter` location | **Factory in `plumb/adapters/__init__.py`** | Keeps CLI thin; adapter package self-contained; reusable from HTTP layer if needed later. |

### 3.1 Sub-decisions implied by the four picks

- **Prompt SHA length:** 8 hex chars (32 bits). Plenty for ≤ 20 prompts per user; keeps `scorer_version` strings under 40 chars.
- **`prompt` parameter on `score()`:** ignored at the adapter layer (the canonical prompt is held by the adapter from constructor). Documented in the docstring; the parameter exists to satisfy the Protocol contract.
- **Fail-open `scorer_version`:** appends `:error` so existing rows can be filtered out and re-run later (`WHERE scorer_version NOT LIKE '%:error'`).
- **`time.sleep` for backoff:** synchronous, called inside the worker. `plumb judge run` is batch-mode CLI; no async story needed.
- **Logging:** module-level `logger = logging.getLogger(__name__)` per file, with one shared `plumb.adapters.judge` namespace for redaction tests.

---

## 4. Decisions deliberately deferred

These will land in `docs/2_architecture/deferred-features.md` as part of T5.1, but are listed here so the next reviewer doesn't surface them as gaps:

| Item | Why deferred |
|---|---|
| Per-metric model env overrides (`PLUMB_JUDGE_MODEL_ROUTING_TOP1`) | CLI `--model` flag covers v1; env-var per metric is convenience, not capability. |
| Concurrent judge calls | At N≤500 sequential is fine; concurrency adds rate-limit complexity. |
| File-backed prompt edit UX | Users manage `.md` files manually in v1. |
| Streaming verdicts | Irrelevant for batch metrics. |
| Tool-use judges | TRD §6.3 explicitly out of scope (requires stateless judges). |
| Agentic-CLI judges (Claude Code, Codex CLI) | TRD §6.3 explicitly out of scope. |
| Multi-judge consensus / ensembling | v2. |
| In-memory result cache for re-runs | Conflicts with delete-and-re-run UX expectation. |

---

## 5. Dependencies on other slices

### 5.1 Hard prerequisites (must be merged first)

- **v1 Core + API** (archived): provides `JudgeAdapter` Protocol, `JudgeResult` entity, `Score` entity, `ValidationError`.
- **v1 Storage Adapter** (archived): provides `SQLiteStorageAdapter` for the score-write path.
- **v1 CLI** (active, Phase 1+2 merged): `plumb judge run` skeleton, `_load_judge_adapter` stub, `FakeJudgeAdapter` Protocol-compliance test in `tests/unit/core/test_ports_compliance.py`.

### 5.2 Things this slice does NOT depend on

- v1 Autocapture — unrelated; judges score finalized runs.
- v1 HTTP read service — read-only; does not invoke judges.
- AgentsView ATTACH adapter — unrelated.

### 5.3 Things this slice unblocks

- **Week-6 regression gate** (PRD Tier-1) — needs working judge adapters to score the 200-task set.
- **Judge re-calibration run** (Phase 2 / Week 9 PRD Tier-1).
- **Public flagship post** with real judge data (Phase 3 / Week 11).

---

## 6. Integration points

### 6.1 With existing CLI

`plumb/cli.py::_load_judge_adapter()` currently raises. This slice replaces its body with a one-line delegate to `plumb.adapters.get_judge_adapter()`. The CLI's existing un-scored-runs query, `--dry-run` path, and fail-open score writes are unchanged — they were correct in the CLI slice.

### 6.2 With existing tests

- `tests/unit/core/test_ports_compliance.py::test_fake_judge_adapter_satisfies_judge_adapter_protocol` already exists and verifies `FakeJudgeAdapter` is `isinstance(JudgeAdapter)`. The new adapters must pass the same Protocol check (asserted in unit tests T2.1 and T3.1).
- `tests/perf/test_cold_import.py` already asserts cold-import latency. Extending it to assert `anthropic` / `openai` are absent from `sys.modules` after `import plumb` is a minimal change.

### 6.3 With docs

- `docs/3_guides/getting_started.md` gains a "Running a judge" section.
- `docs/2_architecture/deferred-features.md` gains seven entries (one per deferred item in §4 above).
- `docs/3_guides/core_concepts.md` is **NOT rewritten** in this slice (TRD §8.5 tracks that as separate work).

---

## 7. Risks specific to this slice

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Anthropic SDK breaks `cache_control` shape between versions | Low | Medium | Pin `anthropic>=0.40,<1.0` in `pyproject.toml`; ship a unit test that asserts the call kwargs include `cache_control`. |
| OpenAI SDK signature drift on `chat.completions.create` | Low | Medium | Pin `openai>=1.50,<2.0`; same kwarg-assertion test. |
| `tenacity` 9 → 10 retry-decorator API change | Low | Low | Pin floor; CI catches at upgrade time. |
| Real network call leaks in CI | Medium | High | Session-scoped `socket.socket.connect` monkeypatch fixture (already in repo for autocapture tests); reuse it for all judge-adapter unit tests. |
| Secrets logged via SDK debug output | Medium | High | Adapters never enable SDK debug logging; tests assert WARNING-level log records do not contain key patterns. |
| Reply-parser brittleness against real LLM output | Medium | Medium | Hypothesis property test; fail-open path captures the raw (redacted) reply for diagnosis. |
| Prompt SHA collision (8 hex chars = 32 bits) | Very Low | Low | At ≤ 20 prompts per user, birthday-paradox collision probability ≈ 1e-7. Documented in plan §3.2. |

---

## 8. Open questions

None blocking Phase 1. All four design decisions resolved in clarification round (2026-04-30).

If something surfaces during implementation, append it here with a date stamp and one of: `[resolved YYYY-MM-DD]`, `[deferred to v1.1]`, `[blocking — needs anant input]`.

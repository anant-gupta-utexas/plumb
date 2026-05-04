# Tasks — v1 Judge Adapters

**Plan:** `[v1-judge-adapters-plan.md](./v1-judge-adapters-plan.md)`
**Context:** `[v1-judge-adapters-context.md](./v1-judge-adapters-context.md)`

Effort: **S** ≤ 1 h · **M** ≤ 4 h · **L** ≤ 1 day · **XL** > 1 day.

---

## Phase 1 — Shared scaffolding ✅

**Objective:** Land the prompt loader, common utilities, and config extensions so the adapters have a stable foundation.

### T1.1 — Add `tenacity` dependency `[S]` ✅

**Description:** Add `tenacity>=9.0` to `pyproject.toml [project.dependencies]`; regenerate lock file; run `uv sync`.

**Acceptance Criteria:**

- `pyproject.toml` lists `tenacity>=9.0` under `[project.dependencies]`.
- `uv lock` regenerated and committed.
- `uv sync` succeeds locally and in CI.
- `python -c "from tenacity import retry"` succeeds.

**Files to Create/Modify:**

- `pyproject.toml`
- `uv.lock`

**Dependencies:** none.
**Tests:** `uv sync` smoke; existing test suite still green.

---

### T1.2 — Implement `plumb/_prompt_loader.py` `[S]` ✅

**Description:** Implement `load_prompt(metric_name, *, prompts_dir=None) -> (text, sha8)` per plan §3.2.

**Acceptance Criteria:**

- Loads `{prompts_dir}/{metric_name}.md` and returns `(text, sha8)` where `sha8 == hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]`.
- `metric_name` validated against `^[a-z][a-z0-9_]{0,63}$`; mismatch → `ValidationError`.
- Empty `metric_name` → `ValidationError`.
- Path-traversal attempts (`"../foo"`, `"/etc/passwd"`, `"foo/bar"`) → `ValidationError` (regex blocks `/` and `.`).
- Missing file → `FileNotFoundError`; the exception message contains the resolved absolute path.
- `prompts_dir=None` → resolves to `ensure_data_dir(get_settings()) / "judge_prompts"`.
- `prompts_dir=Path(...)` → uses the override (test-friendly).
- `mypy --strict plumb/_prompt_loader.py` clean.

**Files to Create/Modify:**

- `plumb/_prompt_loader.py` — new
- `tests/unit/test_prompt_loader.py` — new (≥ 6 tests)

**Dependencies:** none.
**Tests:** Unit only.

---

### T1.3 — Implement `plumb/adapters/_judge_common.py` `[M]` ✅

**Description:** Define `JudgeTransientError`, `JudgeFatalError`, `RawJudgeReply`, `redact_headers()`, `redact_body()`, `with_judge_retry()`, and `parse_reply()` per plan §3.3 + §6.3.

**Acceptance Criteria:**

- `JudgeTransientError` and `JudgeFatalError` are `Exception` subclasses (not each other's parent).
- `redact_headers({"Authorization": "Bearer x", "Content-Type": "json"})` → `{"Authorization": "<redacted>", "Content-Type": "json"}`.
- Header matching is case-insensitive: `authorization`, `X-API-Key`, `api-key` all redacted.
- `redact_body("error: sk-abcd1234efgh")` → `"error: <redacted>"`.
- `redact_body` does NOT mask `sk-` followed by < 8 chars (low-confidence match).
- `with_judge_retry`-decorated function:
  - retries 3× on `JudgeTransientError`,
  - never retries on `JudgeFatalError`,
  - never retries on `KeyboardInterrupt` / `SystemExit` / `MemoryError`,
  - reraises the last exception after attempt 3,
  - calls `time.sleep` exactly 2 times (between attempts 1→2 and 2→3),
  - sleep durations are monotonically non-decreasing within `[1, 8]` seconds.
- `parse_reply('{"verdict":"pass","rationale":"ok"}')` → `("pass", None, "ok")`.
- `parse_reply('{"verdict":"fail","rationale":"bad"}')` → `("fail", None, "bad")`.
- `parse_reply('{"verdict":0.92,"rationale":"close"}')` → `(None, 0.92, "close")`.
- `parse_reply('```json\n{"verdict":"pass","rationale":""}\n```')` → `("pass", None, "")`.
- `parse_reply("not json")` → `ValueError`.
- `parse_reply('{"verdict":"maybe"}')` → `ValueError`.
- `parse_reply('{"verdict":true}')` → `ValueError` (bool excluded from numeric branch).
- Rationale truncated to 1000 chars.
- `mypy --strict plumb/adapters/_judge_common.py` clean.

**Files to Create/Modify:**

- `plumb/adapters/_judge_common.py` — new
- `tests/unit/adapters/test_judge_common_retry.py` — new
- `tests/unit/adapters/test_judge_common_redact.py` — new
- `tests/unit/adapters/test_judge_parse_reply.py` — new (includes one Hypothesis property test)

**Dependencies:** T1.1.
**Tests:** Unit + property.

---

### T1.4 — Extend `plumb/config.py` with `PLUMB_JUDGE_`* settings `[S]` ✅

**Description:** Add the five new judge-related fields to `Settings` per plan §3.7.

**Acceptance Criteria:**

- `Settings.judge_provider: str | None = None`.
- `Settings.judge_anthropic_api_key: str | None = None`.
- `Settings.judge_api_key: str | None = None`.
- `Settings.judge_base_url: str | None = None`.
- `Settings.judge_model: str = "claude-sonnet-4-6"`.
- `PLUMB_JUDGE_PROVIDER=anthropic` is read into `judge_provider`.
- `PLUMB_JUDGE_BASE_URL=https://openrouter.ai/api/v1` is read into `judge_base_url`.
- Existing `data_dir` / `log_level` / `autocapture` defaults unchanged.
- `mypy --strict plumb/config.py` clean.
- `tests/unit/test_config.py` extended with one test per new field (env-var roundtrip).

**Files to Create/Modify:**

- `plumb/config.py`
- `tests/unit/test_config.py`

**Dependencies:** none.
**Tests:** Unit.

**Phase Deliverables:**

- Prompt loader, common utilities, and config extensions merged.
- Coverage on new code ≥ 95 %.

---

## Phase 2 — `AnthropicJudge` ✅

**Objective:** Ship the Anthropic adapter; verify against mocked SDK.

### T2.1 — Implement `plumb/adapters/judge_anthropic.py` `[L]` ✅

**Description:** Per plan §3.4 — constructor, `score()`, `_invoke()` with retry decorator, exception mapping, fail-open behaviour.

**Acceptance Criteria:**

- `name == "anthropic"`, `version == "1"`.
- `__init__` rejects empty `api_key`, empty `prompt`, or empty `prompt_sha` with `ValidationError`.
- `__init__(client=...)` accepts a pre-built client (test injection).
- **Happy path:** `score()` returns `JudgeResult(metric_name, scorer_version=f"anthropic:{model}:{prompt_sha}", value_label, rationale, tokens_in, tokens_out, latency_ms)`.
- System prompt sent with `cache_control={"type": "ephemeral"}` (verified by inspecting the call args on the mock).
- Request uses `temperature=0.0`, `max_tokens=1024`.
- `prompt` parameter on `score()` is documented as ignored; the adapter uses its constructor-supplied prompt.
- `RateLimitError` raised twice then 200 → SDK invoked 3 times; `JudgeResult.value_label` is `"pass"` or `"fail"` (not `"error"`); `time.sleep` called 2 times.
- `RateLimitError` raised 3× → fail-open: `value_label="error"`, `scorer_version` ends in `":error"`, `tokens_in=0`, `tokens_out=0`, `latency_ms=0.0`, rationale truncated ≤ 500 chars.
- `APIStatusError` 500 raised 3× → fail-open as above.
- `APIStatusError` 400 raised → fail-open immediately, SDK invoked exactly once.
- `AuthenticationError` (HTTP 401) raised → fail-open immediately, SDK invoked exactly once.
- `APIConnectionError` raised once then 200 → retry succeeds.
- Reply not JSON → fail-open with truncated, redacted rationale.
- Reply contains an API-key-shaped substring (`"error: sk-abc12345abcde"`) → log record and `JudgeResult.rationale` both contain `<redacted>` instead of the key (regex assertion).
- `isinstance(AnthropicJudge(...), JudgeAdapter)` → `True`.
- WARNING log emitted exactly once per fail-open (not once per retry).
- No real network: test fixture asserts `socket.socket.connect` was never called.

**Files to Create/Modify:**

- `plumb/adapters/judge_anthropic.py` — new
- `tests/unit/adapters/test_judge_anthropic.py` — new

**Dependencies:** T1.1, T1.2, T1.3.
**Tests:** Unit (mock `anthropic.Anthropic.messages.create` via `monkeypatch`).

**Phase Deliverables:**

- Anthropic adapter passes all unit tests.
- ≥ 90 % coverage on the new module.

---

## Phase 3 — `OpenAICompatibleJudge` ✅

**Objective:** Ship the OpenAI-compatible adapter; verify base-URL passthrough.

### T3.1 — Implement `plumb/adapters/judge_openai_compat.py` `[L]` ✅

**Description:** Per plan §3.5 — same shape as Anthropic with OpenAI SDK exception mapping and configurable `base_url`.

**Acceptance Criteria:**

- `name == "openai_compat"`, `version == "1"`.
- `__init__` rejects empty `api_key`, empty `prompt`, or empty `prompt_sha` with `ValidationError`.
- `__init__(base_url=None)` → SDK uses its default (api.openai.com).
- `__init__(base_url="https://openrouter.ai/api/v1")` → passed verbatim into `openai.OpenAI(base_url=...)`.
- **Happy path:** returns `JudgeResult(scorer_version=f"openai_compat:{model}:{prompt_sha}", ...)`.
- Request uses `temperature=0.0`, `max_tokens=1024`.
- System prompt as `messages[0] {"role":"system"}`; user content as `messages[1] {"role":"user"}`.
- Tokens parsed from `resp.usage.prompt_tokens` (→ `tokens_in`) and `resp.usage.completion_tokens` (→ `tokens_out`).
- `RateLimitError` 3× → fail-open.
- `APIStatusError` 5xx 3× → fail-open.
- `APIStatusError` 4xx (non-429) → fail-open immediately.
- `APIConnectionError` once then 200 → retry succeeds.
- **Base-URL HTTP-level test (AC-INT-2):** using mock on `openai.OpenAI` constructor, verify `base_url` is forwarded.
- Logs redacted: no `sk-…`, no `Authorization:` substrings.
- `isinstance(OpenAICompatibleJudge(...), JudgeAdapter)` → `True`.

**Files to Create/Modify:**

- `plumb/adapters/judge_openai_compat.py` — new
- `tests/unit/adapters/test_judge_openai_compat.py` — new

**Dependencies:** T1.1, T1.2, T1.3.
**Tests:** Unit (mock SDK) + base-URL constructor test.

**Phase Deliverables:**

- OpenAI-compat adapter passes all unit tests.
- TRD AC-INT-2 satisfied via base-URL test.

---

## Phase 4 — Factory + CLI wiring ✅

**Objective:** Replace the `_load_judge_adapter` stub with the real factory; ship the CLI integration test that closes the open T3.1 from the CLI slice.

### T4.1 — Implement `get_judge_adapter()` factory `[M]` ✅

**Description:** Per plan §3.6 — provider switch, prompt-loader call, credential checks, lazy SDK imports.

**Acceptance Criteria:**

- Function signature: `get_judge_adapter(settings: Settings, *, metric_name: str) -> JudgeAdapter`.
- `settings.judge_provider is None` → `ValueError` whose message contains `"PLUMB_JUDGE_PROVIDER"`.
- `settings.judge_provider == "unknown"` → `ValueError("Unsupported PLUMB_JUDGE_PROVIDER: 'unknown'")`.
- `provider="anthropic"` + key set + prompt file present → returns an `AnthropicJudge` instance.
- `provider="anthropic"` + key unset → `ValueError` whose message contains `"PLUMB_JUDGE_ANTHROPIC_API_KEY"`.
- `provider="openai_compat"` + key set → returns `OpenAICompatibleJudge`; `base_url` from settings is forwarded into the constructor.
- `provider="openai_compat"` + `judge_api_key` unset → `ValueError` whose message contains `"PLUMB_JUDGE_API_KEY"`.
- Prompt file missing → `FileNotFoundError` propagates (CLI catches).
- Lazy import: `provider="anthropic"` does NOT import `openai`; `provider="openai_compat"` does NOT import `anthropic` (verified via `sys.modules` snapshot).
- **NFR-Perf-6 regression:** `python -X importtime -c "import plumb"` does NOT load `anthropic` or `openai` (asserted in `tests/perf/test_cold_import.py`).

**Files to Create/Modify:**

- `plumb/adapters/__init__.py`
- `tests/unit/adapters/test_judge_factory.py` — new
- `tests/perf/test_cold_import.py` — extend with SDK-not-loaded assertion (already present)

**Dependencies:** T2.1, T3.1.
**Tests:** Unit + perf regression.

---

### T4.2 — Wire factory into `cli.judge_run` `[S]` ✅

**Description:** Replace `_load_judge_adapter`'s `NotImplementedError`; pass `metric` through as `metric_name`.

**Acceptance Criteria:**

- `cli._load_judge_adapter(provider, model, metric_name=...)` returns `get_judge_adapter(get_settings(), metric_name=metric_name)`.
- `cli.judge_run` forwards `metric` as `metric_name` into `_load_judge_adapter`.
- Factory `ValueError` is caught and routed through `_die()` (exit 1, message preserved).
- `FileNotFoundError` from prompt loading is caught and routed through `_die()` with the absolute path.
- All existing `tests/cli/test_cli_judge_run.py` tests continue to pass — none rely on the stub.
- `ruff check .` clean on `plumb/_cli_judge.py`.

**Files to Create/Modify:**

- `plumb/_cli_judge.py`

**Dependencies:** T4.1.
**Tests:** Existing CLI test suite.

---

### T4.3 — Implement `tests/cli/test_cli_judge_run.py` `[L]` ✅

**Description:** Per CLI plan T3.1 — end-to-end CLI tests with `FakeJudgeAdapter` injected via monkeypatch on `plumb._cli_judge._load_judge_adapter`.

**Acceptance Criteria:**

- `--dry-run` → prints `"Would judge N run(s) for metric=…"`, exits 0, zero `scores` rows written.
- 3 un-scored runs → 3 `scores` rows written with `scorer='judge'`, `scorer_version` matching the fake's value, `value_label` matching the fake's verdict.
- Re-run after success → 0 new rows (idempotency via existing un-scored-runs query).
- Fake adapter raising → `value_label='error'` row written, command exits 0.
- `PLUMB_JUDGE_PROVIDER` unset → exit 1, stderr contains `"PLUMB_JUDGE_PROVIDER"`.
- `--model sk-abc123` → exit 1, stderr contains `"looks like an API key"`.
- `--since 7d` filters runs older than 7 days (one stale run not judged).
- `--task-id foo` filters non-matching task (one row not judged).
- Reusable `FakeJudgeAdapter` lives in `tests/helpers/fake_judge.py` (importable across slices).

**Files to Create/Modify:**

- `tests/cli/test_cli_judge_run.py` — new
- `tests/helpers/fake_judge.py` — new

**Dependencies:** T4.1, T4.2.
**Tests:** CLI integration.

**Phase Deliverables:**

- `plumb judge run` end-to-end, no `NotImplementedError`.
- CLI plan T3.1 closed.
- All TRD INT-JUDGE-* and AC-INT-* tests passing.

---

## Phase 5 — Documentation + verify

**Objective:** Update user-facing docs; record deferred entries; run quality gates.

### T5.1 — Update docs and seed an example prompt `[M]` ✅

**Description:** Document `PLUMB_JUDGE_`* env vars, the prompt-file convention, the JSON-verdict contract, and the fail-open behaviour. Provide a starter `routing_top1.md` prompt file as a documentation example (not shipped in the wheel).

**Acceptance Criteria:**

- `docs/3_guides/getting_started.md` adds a "Running a judge" section with a copy-paste example for both providers.
- `docs/2_architecture/deferred-features.md` adds entries: "Per-metric model env overrides", "Concurrent judge calls", "File-backed prompt edit UX", "Streaming verdicts", "Tool-use judges (CLI-style)", "Multi-judge consensus / ensembling".
- `docs/3_guides/judge_prompts/routing_top1.md` — example prompt, explicitly NOT loaded by code.
- `interrogate --fail-under 95 plumb/api.py plumb/cli.py plumb/http.py` still passes (this slice does not touch those files' public surface).
- Each new public function has a Google-style docstring with at least one usage example.

**Files to Create/Modify:**

- `docs/3_guides/getting_started.md`
- `docs/2_architecture/deferred-features.md`
- `docs/3_guides/judge_prompts/routing_top1.md`

**Dependencies:** T4.3.
**Tests:** Doc-link smoke (existing).

---

### T5.2 — Code review + verify suite `[S]` ✅

**Description:** Run `/DEV-ESSENTIALS:code-review` and `/DEV-ESSENTIALS:verify` on the slice diff; resolve findings.

**Acceptance Criteria:**

- `ruff check .` clean.
- `ruff format --check .` clean.
- `mypy --strict plumb/core/` clean (regression check).
- `pytest --cov=plumb --cov-fail-under=75` passes.
- No real network calls in CI (`socket.connect` monkeypatch fixture honored).
- No new ruff `S` (security) warnings.
- All new files ≤ 400 LOC, all functions ≤ 50 LOC (per CLAUDE.md style guide).

**Files to Create/Modify:** none — verification-only.
**Dependencies:** all prior tasks.
**Tests:** Full suite.

**Phase Deliverables:**

- Docs reflect the new judge-running UX.
- All CLAUDE.md quality gates green.
- Slice mergeable to `main`.

---

## Phase 6 — Code-review remediation (2026-05-04) ✅

**Objective:** Address all P1 and P2 findings from the v1-judge-adapters code review; close stated test gaps; split oversized test files.

### T6.1 — Fix `plumb judge run` content selection `[S]` ✅

**Description:** `_load_run_content` was reading `input_hash` (the provider request) instead of `output_hash` (the model response). Fix the selection logic to prefer successful LLM spans with `output_hash`.

**Acceptance Criteria:**

- `_load_run_content` prefers `SpanStatus.SUCCESS` LLM spans with `output_hash`, falls back to any LLM span with `output_hash`, returns `""` if none found. Never falls back to `input_hash`.
- `test_judge_run_reads_output_blob_not_input` passes: a run with both `input_hash` and `output_hash` blobs results in the judge receiving the output blob content.

**Files Modified:** `plumb/_cli_judge.py`, `tests/cli/test_cli_judge_run.py`.

---

### T6.2 — Make `:error` score rows retryable `[S]` ✅

**Description:** The unscored-query `NOT EXISTS` clause was blocking re-judging of runs that had a prior fail-open error score. Fix the SQL and normalise the CLI outer-except scorer_version format.

**Acceptance Criteria:**

- `list_runs_unscored_for_metric` SQL: `NOT EXISTS` now requires `s.scorer_version NOT LIKE '%:error'`, so only non-error scores block re-judging.
- CLI outer-except path writes `scorer_version=f"{provider}:{model}:unknown:error"` (consistent `:error` suffix with adapter `_fail_open` shape).
- `test_judge_run_retries_after_error_score` passes: a run with a prior `*:error` score is re-judged on the next invocation.

**Files Modified:** `plumb/adapters/storage_sqlite.py`, `plumb/_cli_judge.py`, `tests/cli/test_cli_judge_run.py`.

---

### T6.3 — Tighten `get_judge_adapter` factory contract `[S]` ✅

**Description:** The factory was loading the prompt before validating provider/credentials (wrong error order), and used the global `get_settings()` inside `load_prompt` instead of the supplied `Settings` object.

**Acceptance Criteria:**

- Provider validation → credential validation → prompt loading (this order).
- `load_prompt` called with `prompts_dir=ensure_data_dir(settings) / "judge_prompts"` so the supplied `settings.data_dir` is honored.
- `test_factory_resolves_prompt_from_settings_data_dir` passes without mocking `load_prompt`.
- `test_factory_validation_order_*` tests confirm `ValueError` is raised before `FileNotFoundError` for unsupported provider and missing key.

**Files Modified:** `plumb/adapters/__init__.py`, `tests/unit/adapters/test_judge_factory.py`.

---

### T6.4 — Switch retry to `tenacity.wait_exponential_jitter` `[S]` ✅

**Description:** `with_judge_retry` was a hand-rolled deterministic backoff instead of the `tenacity` library specified in the plan (INT-JUDGE-5). Switch to `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=1, max=8), retry=retry_if_exception_type(JudgeTransientError), reraise=True)`.

**Acceptance Criteria:**

- `_judge_common.py` imports and uses `tenacity`; the hand-rolled loop is removed.
- `test_sleep_durations_within_bounds` updated to lower bound `2.0` (jitter formula: `initial*2^n + uniform(0, jitter)`, minimum at attempt 1 is 2.0).
- All existing retry tests still pass.

**Note:** Requires `uv sync` to install `tenacity>=9.0` into the project venv (T1.1 listed it in `pyproject.toml`).

**Files Modified:** `plumb/adapters/_judge_common.py`, `tests/unit/adapters/test_judge_common_retry.py`.

---

### T6.5 — Test-file splits and remaining gap tests `[S]` ✅

**Description:** Split `test_judge_anthropic.py` (456 lines) and `test_judge_openai_compat.py` (513 lines) into `_construction` + `_scoring` pairs to approach the 400-line target. Add the three test gaps called out in the review.

**Acceptance Criteria:**

- `test_judge_anthropic.py` → `test_judge_anthropic_construction.py` + `test_judge_anthropic_scoring.py` (≤ 420 lines each).
- `test_judge_openai_compat.py` → `test_judge_openai_compat_construction.py` + `test_judge_openai_compat_scoring.py` (≤ 460 lines each; residual overage noted — no single function exceeds 50 LOC).
- `test_judge_run_reads_output_blob_not_input` (CLI integration, real blobstore).
- `test_judge_run_retries_after_error_score` (CLI integration, rerun after `:error` row).
- `test_factory_resolves_prompt_from_settings_data_dir` + `test_factory_validation_order_*` (non-mocked factory contract).
- Fixed `tests/cli/conftest.py::make_run` baseline: `datetime.now(UTC) - timedelta(days=start_offset_days)` replaces hardcoded `2026-04-28` to keep since-filter tests correct over time.

**Files Modified/Created:** `tests/unit/adapters/test_judge_anthropic_construction.py` (new), `tests/unit/adapters/test_judge_anthropic_scoring.py` (new), `tests/unit/adapters/test_judge_openai_compat_construction.py` (new), `tests/unit/adapters/test_judge_openai_compat_scoring.py` (new), `tests/cli/conftest.py`, `tests/cli/test_cli_judge_run.py`, `tests/unit/adapters/test_judge_factory.py`.

**Phase Deliverables:**

- All P1 and P2 review findings addressed.
- Two previously failing CLI tests (`test_list_runs_with_counts_since_filter`, `test_run_stats_since_filter`) fixed.
- New test coverage: output-blob selection, error-score retry, non-mocked factory, validation order.
- All test files ≤ 800 LOC (hard max); scoring test files ≤ 460 LOC (approaching 400 target).
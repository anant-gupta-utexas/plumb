# Tasks — v1 Judge Adapters

**Plan:** [`v1-judge-adapters-plan.md`](./v1-judge-adapters-plan.md)
**Context:** [`v1-judge-adapters-context.md`](./v1-judge-adapters-context.md)

Effort: **S** ≤ 1 h · **M** ≤ 4 h · **L** ≤ 1 day · **XL** > 1 day.

---

## Phase 1 — Shared scaffolding ✅

**Objective:** Land the prompt loader, common utilities, and config extensions so the adapters have a stable foundation.

### T1.1 — Add `tenacity` dependency `[S]` ✅

**Description:** Add `tenacity>=9.0` to `pyproject.toml [project.dependencies]`; regenerate lock file; run `uv sync`.

**Acceptance Criteria:**
- [x] `pyproject.toml` lists `tenacity>=9.0` under `[project.dependencies]`.
- [x] `uv lock` regenerated and committed.
- [x] `uv sync` succeeds locally and in CI.
- [x] `python -c "from tenacity import retry"` succeeds.

**Files to Create/Modify:**
- `pyproject.toml`
- `uv.lock`

**Dependencies:** none.
**Tests:** `uv sync` smoke; existing test suite still green.

---

### T1.2 — Implement `plumb/_prompt_loader.py` `[S]` ✅

**Description:** Implement `load_prompt(metric_name, *, prompts_dir=None) -> (text, sha8)` per plan §3.2.

**Acceptance Criteria:**
- [x] Loads `{prompts_dir}/{metric_name}.md` and returns `(text, sha8)` where `sha8 == hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]`.
- [x] `metric_name` validated against `^[a-z][a-z0-9_]{0,63}$`; mismatch → `ValidationError`.
- [x] Empty `metric_name` → `ValidationError`.
- [x] Path-traversal attempts (`"../foo"`, `"/etc/passwd"`, `"foo/bar"`) → `ValidationError` (regex blocks `/` and `.`).
- [x] Missing file → `FileNotFoundError`; the exception message contains the resolved absolute path.
- [x] `prompts_dir=None` → resolves to `ensure_data_dir(get_settings()) / "judge_prompts"`.
- [x] `prompts_dir=Path(...)` → uses the override (test-friendly).
- [x] `mypy --strict plumb/_prompt_loader.py` clean.

**Files to Create/Modify:**
- `plumb/_prompt_loader.py` — new
- `tests/unit/test_prompt_loader.py` — new (≥ 6 tests)

**Dependencies:** none.
**Tests:** Unit only.

---

### T1.3 — Implement `plumb/adapters/_judge_common.py` `[M]` ✅

**Description:** Define `JudgeTransientError`, `JudgeFatalError`, `RawJudgeReply`, `redact_headers()`, `redact_body()`, `with_judge_retry()`, and `parse_reply()` per plan §3.3 + §6.3.

**Acceptance Criteria:**
- [x] `JudgeTransientError` and `JudgeFatalError` are `Exception` subclasses (not each other's parent).
- [x] `redact_headers({"Authorization": "Bearer x", "Content-Type": "json"})` → `{"Authorization": "<redacted>", "Content-Type": "json"}`.
- [x] Header matching is case-insensitive: `authorization`, `X-API-Key`, `api-key` all redacted.
- [x] `redact_body("error: sk-abcd1234efgh")` → `"error: <redacted>"`.
- [x] `redact_body` does NOT mask `sk-` followed by < 8 chars (low-confidence match).
- [x] `with_judge_retry`-decorated function:
  - retries 3× on `JudgeTransientError`,
  - never retries on `JudgeFatalError`,
  - never retries on `KeyboardInterrupt` / `SystemExit` / `MemoryError`,
  - reraises the last exception after attempt 3,
  - calls `time.sleep` exactly 2 times (between attempts 1→2 and 2→3),
  - sleep durations are monotonically non-decreasing within `[1, 8]` seconds.
- [x] `parse_reply('{"verdict":"pass","rationale":"ok"}')` → `("pass", None, "ok")`.
- [x] `parse_reply('{"verdict":"fail","rationale":"bad"}')` → `("fail", None, "bad")`.
- [x] `parse_reply('{"verdict":0.92,"rationale":"close"}')` → `(None, 0.92, "close")`.
- [x] `parse_reply('```json\n{"verdict":"pass","rationale":""}\n```')` → `("pass", None, "")`.
- [x] `parse_reply("not json")` → `ValueError`.
- [x] `parse_reply('{"verdict":"maybe"}')` → `ValueError`.
- [x] `parse_reply('{"verdict":true}')` → `ValueError` (bool excluded from numeric branch).
- [x] Rationale truncated to 1000 chars.
- [x] `mypy --strict plumb/adapters/_judge_common.py` clean.

**Files to Create/Modify:**
- `plumb/adapters/_judge_common.py` — new
- `tests/unit/adapters/test_judge_common_retry.py` — new
- `tests/unit/adapters/test_judge_common_redact.py` — new
- `tests/unit/adapters/test_judge_parse_reply.py` — new (includes one Hypothesis property test)

**Dependencies:** T1.1.
**Tests:** Unit + property.

---

### T1.4 — Extend `plumb/config.py` with `PLUMB_JUDGE_*` settings `[S]` ✅

**Description:** Add the five new judge-related fields to `Settings` per plan §3.7.

**Acceptance Criteria:**
- [x] `Settings.judge_provider: str | None = None`.
- [x] `Settings.judge_anthropic_api_key: str | None = None`.
- [x] `Settings.judge_api_key: str | None = None`.
- [x] `Settings.judge_base_url: str | None = None`.
- [x] `Settings.judge_model: str = "claude-sonnet-4-6"`.
- [x] `PLUMB_JUDGE_PROVIDER=anthropic` is read into `judge_provider`.
- [x] `PLUMB_JUDGE_BASE_URL=https://openrouter.ai/api/v1` is read into `judge_base_url`.
- [x] Existing `data_dir` / `log_level` / `autocapture` defaults unchanged.
- [x] `mypy --strict plumb/config.py` clean.
- [x] `tests/unit/test_config.py` extended with one test per new field (env-var roundtrip).

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
- [x] `name == "anthropic"`, `version == "1"`.
- [x] `__init__` rejects empty `api_key`, empty `prompt`, or empty `prompt_sha` with `ValidationError`.
- [x] `__init__(client=...)` accepts a pre-built client (test injection).
- [x] **Happy path:** `score()` returns `JudgeResult(metric_name, scorer_version=f"anthropic:{model}:{prompt_sha}", value_label, rationale, tokens_in, tokens_out, latency_ms)`.
- [x] System prompt sent with `cache_control={"type": "ephemeral"}` (verified by inspecting the call args on the mock).
- [x] Request uses `temperature=0.0`, `max_tokens=1024`.
- [x] `prompt` parameter on `score()` is documented as ignored; the adapter uses its constructor-supplied prompt.
- [x] `RateLimitError` raised twice then 200 → SDK invoked 3 times; `JudgeResult.value_label` is `"pass"` or `"fail"` (not `"error"`); `time.sleep` called 2 times.
- [x] `RateLimitError` raised 3× → fail-open: `value_label="error"`, `scorer_version` ends in `":error"`, `tokens_in=0`, `tokens_out=0`, `latency_ms=0.0`, rationale truncated ≤ 500 chars.
- [x] `APIStatusError` 500 raised 3× → fail-open as above.
- [x] `APIStatusError` 400 raised → fail-open immediately, SDK invoked exactly once.
- [x] `AuthenticationError` (HTTP 401) raised → fail-open immediately, SDK invoked exactly once.
- [x] `APIConnectionError` raised once then 200 → retry succeeds.
- [x] Reply not JSON → fail-open with truncated, redacted rationale.
- [x] Reply contains an API-key-shaped substring (`"error: sk-abc12345abcde"`) → log record and `JudgeResult.rationale` both contain `<redacted>` instead of the key (regex assertion).
- [x] `isinstance(AnthropicJudge(...), JudgeAdapter)` → `True`.
- [x] WARNING log emitted exactly once per fail-open (not once per retry).
- [x] No real network: test fixture asserts `socket.socket.connect` was never called.

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
- [x] `name == "openai_compat"`, `version == "1"`.
- [x] `__init__` rejects empty `api_key`, empty `prompt`, or empty `prompt_sha` with `ValidationError`.
- [x] `__init__(base_url=None)` → SDK uses its default (api.openai.com).
- [x] `__init__(base_url="https://openrouter.ai/api/v1")` → passed verbatim into `openai.OpenAI(base_url=...)`.
- [x] **Happy path:** returns `JudgeResult(scorer_version=f"openai_compat:{model}:{prompt_sha}", ...)`.
- [x] Request uses `temperature=0.0`, `max_tokens=1024`.
- [x] System prompt as `messages[0] {"role":"system"}`; user content as `messages[1] {"role":"user"}`.
- [x] Tokens parsed from `resp.usage.prompt_tokens` (→ `tokens_in`) and `resp.usage.completion_tokens` (→ `tokens_out`).
- [x] `RateLimitError` 3× → fail-open.
- [x] `APIStatusError` 5xx 3× → fail-open.
- [x] `APIStatusError` 4xx (non-429) → fail-open immediately.
- [x] `APIConnectionError` once then 200 → retry succeeds.
- [x] **Base-URL HTTP-level test (AC-INT-2):** using mock on `openai.OpenAI` constructor, verify `base_url` is forwarded.
- [x] Logs redacted: no `sk-…`, no `Authorization:` substrings.
- [x] `isinstance(OpenAICompatibleJudge(...), JudgeAdapter)` → `True`.

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
- [x] Function signature: `get_judge_adapter(settings: Settings, *, metric_name: str) -> JudgeAdapter`.
- [x] `settings.judge_provider is None` → `ValueError` whose message contains `"PLUMB_JUDGE_PROVIDER"`.
- [x] `settings.judge_provider == "unknown"` → `ValueError("Unsupported PLUMB_JUDGE_PROVIDER: 'unknown'")`.
- [x] `provider="anthropic"` + key set + prompt file present → returns an `AnthropicJudge` instance.
- [x] `provider="anthropic"` + key unset → `ValueError` whose message contains `"PLUMB_JUDGE_ANTHROPIC_API_KEY"`.
- [x] `provider="openai_compat"` + key set → returns `OpenAICompatibleJudge`; `base_url` from settings is forwarded into the constructor.
- [x] `provider="openai_compat"` + `judge_api_key` unset → `ValueError` whose message contains `"PLUMB_JUDGE_API_KEY"`.
- [x] Prompt file missing → `FileNotFoundError` propagates (CLI catches).
- [x] Lazy import: `provider="anthropic"` does NOT import `openai`; `provider="openai_compat"` does NOT import `anthropic` (verified via `sys.modules` snapshot).
- [x] **NFR-Perf-6 regression:** `python -X importtime -c "import plumb"` does NOT load `anthropic` or `openai` (asserted in `tests/perf/test_cold_import.py`).

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
- [x] `cli._load_judge_adapter(provider, model, metric_name=...)` returns `get_judge_adapter(get_settings(), metric_name=metric_name)`.
- [x] `cli.judge_run` forwards `metric` as `metric_name` into `_load_judge_adapter`.
- [x] Factory `ValueError` is caught and routed through `_die()` (exit 1, message preserved).
- [x] `FileNotFoundError` from prompt loading is caught and routed through `_die()` with the absolute path.
- [x] All existing `tests/cli/test_cli_judge_run.py` tests continue to pass — none rely on the stub.
- [x] `ruff check .` clean on `plumb/_cli_judge.py`.

**Files to Create/Modify:**
- `plumb/_cli_judge.py`

**Dependencies:** T4.1.
**Tests:** Existing CLI test suite.

---

### T4.3 — Implement `tests/cli/test_cli_judge_run.py` `[L]` ✅

**Description:** Per CLI plan T3.1 — end-to-end CLI tests with `FakeJudgeAdapter` injected via monkeypatch on `plumb._cli_judge._load_judge_adapter`.

**Acceptance Criteria:**
- [x] `--dry-run` → prints `"Would judge N run(s) for metric=…"`, exits 0, zero `scores` rows written.
- [x] 3 un-scored runs → 3 `scores` rows written with `scorer='judge'`, `scorer_version` matching the fake's value, `value_label` matching the fake's verdict.
- [x] Re-run after success → 0 new rows (idempotency via existing un-scored-runs query).
- [x] Fake adapter raising → `value_label='error'` row written, command exits 0.
- [x] `PLUMB_JUDGE_PROVIDER` unset → exit 1, stderr contains `"PLUMB_JUDGE_PROVIDER"`.
- [x] `--model sk-abc123` → exit 1, stderr contains `"looks like an API key"`.
- [x] `--since 7d` filters runs older than 7 days (one stale run not judged).
- [x] `--task-id foo` filters non-matching task (one row not judged).
- [x] Reusable `FakeJudgeAdapter` lives in `tests/helpers/fake_judge.py` (importable across slices).

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

### T5.1 — Update docs and seed an example prompt `[M]`

**Description:** Document `PLUMB_JUDGE_*` env vars, the prompt-file convention, the JSON-verdict contract, and the fail-open behaviour. Provide a starter `routing_top1.md` prompt file as a documentation example (not shipped in the wheel).

**Acceptance Criteria:**
- [ ] `docs/3_guides/getting_started.md` adds a "Running a judge" section with a copy-paste example for both providers.
- [ ] `docs/2_architecture/deferred-features.md` adds entries: "Per-metric model env overrides", "Concurrent judge calls", "File-backed prompt edit UX", "Streaming verdicts", "Tool-use judges (CLI-style)", "Multi-judge consensus / ensembling".
- [ ] `docs/3_guides/judge_prompts/routing_top1.md` — example prompt, explicitly NOT loaded by code.
- [ ] `interrogate --fail-under 95 plumb/api.py plumb/cli.py plumb/http.py` still passes (this slice does not touch those files' public surface).
- [ ] Each new public function has a Google-style docstring with at least one usage example.

**Files to Create/Modify:**
- `docs/3_guides/getting_started.md`
- `docs/2_architecture/deferred-features.md`
- `docs/3_guides/judge_prompts/routing_top1.md`

**Dependencies:** T4.3.
**Tests:** Doc-link smoke (existing).

---

### T5.2 — Code review + verify suite `[S]`

**Description:** Run `/DEV-ESSENTIALS:code-review` and `/DEV-ESSENTIALS:verify` on the slice diff; resolve findings.

**Acceptance Criteria:**
- [ ] `ruff check .` clean.
- [ ] `ruff format --check .` clean.
- [ ] `mypy --strict plumb/core/` clean (regression check).
- [ ] `pytest --cov=plumb --cov-fail-under=75` passes.
- [ ] No real network calls in CI (`socket.connect` monkeypatch fixture honored).
- [ ] No new ruff `S` (security) warnings.
- [ ] All new files ≤ 400 LOC, all functions ≤ 50 LOC (per CLAUDE.md style guide).

**Files to Create/Modify:** none — verification-only.
**Dependencies:** all prior tasks.
**Tests:** Full suite.

**Phase Deliverables:**
- Docs reflect the new judge-running UX.
- All CLAUDE.md quality gates green.
- Slice mergeable to `main`.

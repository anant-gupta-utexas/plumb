# TRS — v1 Judge Adapters

**Status:** Draft v1 — derived from [TRD §6.1](../../../docs/2_architecture/TRD.md), follows [v1 CLI TRS](../v1-cli/v1-cli-plan.md), [v1 Storage Adapter TRS](../../archive/v1-storage-adapter/v1-storage-adapter-plan.md)
**Owner:** anant
**Last updated:** 2026-04-30
**Scope:** Fifth component slice of plumb v1 — the two `JudgeAdapter` implementations (`AnthropicJudge`, `OpenAICompatibleJudge`), the prompt-loading helper, the adapter factory, and the wiring into `plumb judge run`.

> Implementation phases and per-task ACs are in [`v1-judge-adapters-tasks.md`](./v1-judge-adapters-tasks.md). Decisions and dependencies are in [`v1-judge-adapters-context.md`](./v1-judge-adapters-context.md).

---

## 1. Overview & Scope

### 1.1 What this slice delivers

Two concrete `JudgeAdapter` implementations satisfying [`plumb.core.ports.JudgeAdapter`](../../../plumb/core/ports.py), plus the supporting wiring needed to make `plumb judge run` actually call a model:

```
plumb/
├── adapters/
│   ├── __init__.py                  # adds get_judge_adapter() factory
│   ├── judge_anthropic.py           # NEW — native Anthropic SDK adapter
│   ├── judge_openai_compat.py       # NEW — OpenAI-compatible adapter (covers OpenAI / OpenRouter / Ollama / vLLM / LM Studio / LiteLLM)
│   └── _judge_common.py             # NEW — shared retry, redaction, error mapping, reply parser
├── _prompt_loader.py                # NEW — load + SHA judge prompts from $PLUMB_DATA_DIR/judge_prompts/
├── config.py                        # extended with PLUMB_JUDGE_* settings
└── cli.py                           # _load_judge_adapter() now delegates to factory
tests/
├── unit/adapters/
│   ├── test_judge_anthropic.py
│   ├── test_judge_openai_compat.py
│   ├── test_judge_common_retry.py
│   ├── test_judge_common_redact.py
│   ├── test_judge_factory.py
│   └── test_judge_parse_reply.py
├── unit/test_prompt_loader.py
└── cli/test_cli_judge_run.py        # closes the open T3.1 from the CLI slice
```

LOC target: ≤ 800 production + ≤ 600 test across new files.

### 1.2 What this slice does NOT deliver

- **No real network calls in CI.** All tests mock the SDK clients.
- **No streaming responses.** Judges are batch (one prompt → one verdict).
- **No tool-use blocks.** Judges are stateless `(prompt, content) → score`.
- **No agentic CLI judges** (Claude Code / Codex CLI / Cursor agent — TRD §6.3 deferred).
- **No multi-judge consensus / ensembling.**
- **No file-backed prompt edit UX.** The user manages `$PLUMB_DATA_DIR/judge_prompts/*.md` files manually.

### 1.3 Why this slice now

1. **Unblocks the offline eval loop.** `plumb judge run` currently raises `NotImplementedError`.
2. **Anchors `scorer_version` drift detection.** Until adapters stamp `{provider}:{model}:{prompt_sha}`, the schema's drift-guard column is unused (PRD §5).
3. **Cost / coverage tradeoff.** Two adapters cover six concrete endpoints (Anthropic, OpenAI, OpenRouter, Ollama, vLLM, LM Studio, LiteLLM proxy) for the price of one HTTP shape × two SDKs.
4. **Prerequisite for the regression gate** (PRD §8 Tier-1 + TRD §10.4).

---

## 2. Requirements Summary

| TRD ref | Requirement | How this slice satisfies it |
|---|---|---|
| INT-JUDGE-1 | `AnthropicJudge` uses native Anthropic SDK; preserves prompt caching | `plumb/adapters/judge_anthropic.py` — `anthropic.Anthropic().messages.create(...)` with `cache_control` on the system prompt |
| INT-JUDGE-2 | `OpenAICompatibleJudge` uses OpenAI SDK with configurable `base_url` | `plumb/adapters/judge_openai_compat.py` — `openai.OpenAI(base_url=..., api_key=...)` |
| INT-JUDGE-3 | Adapter selection driven by `PLUMB_JUDGE_PROVIDER` | `plumb.adapters.get_judge_adapter(settings)` factory |
| INT-JUDGE-4 | JSON chat-completions request, temperature 0, max_tokens 1024 | Hard-coded in both adapters |
| INT-JUDGE-5 | Exponential backoff + jitter, max 3 retries on 429/5xx, fail-open after | `tenacity` on a shared `_invoke()` helper in `_judge_common.py` |
| INT-JUDGE-6 | `scorer_version = "{provider}:{model}:{prompt_sha}"` | Adapter computes from constructor args |
| FR-SCORE-2 | `scorer_version` NOT NULL on every score | Fail-open path uses `"{provider}:{model}:{prompt_sha}:error"` |
| NFR-Sec-1 | API keys via env, never CLI args, never logged | `pydantic-settings` reads `PLUMB_JUDGE_*` vars; redaction in `_judge_common.redact_*` |
| NFR-Sec-2 | Secrets MUST NOT appear in logs | Centralized log helper redacts `Authorization`, `x-api-key`, `api-key`, `sk-…` patterns |
| NFR-Perf-5 | Zero synchronous network I/O on hot path | Adapters live in `plumb/adapters/`; `plumb.api` does not import them; lazy import inside the factory |

---

## 3. Detailed Component Design

### 3.1 Module map

```
plumb/adapters/_judge_common.py         # private — shared retry + redaction + error type + reply parser
plumb/adapters/judge_anthropic.py       # AnthropicJudge
plumb/adapters/judge_openai_compat.py   # OpenAICompatibleJudge
plumb/adapters/__init__.py              # get_judge_adapter() factory (added)
plumb/_prompt_loader.py                 # load_prompt(metric_name) -> (prompt_text, prompt_sha)
plumb/config.py                         # extended Settings
plumb/cli.py                            # _load_judge_adapter() delegates to factory
```

### 3.2 `plumb/_prompt_loader.py`

```python
def load_prompt(metric_name: str, *, prompts_dir: Path | None = None) -> tuple[str, str]:
    """Load a judge prompt file and return (prompt_text, prompt_sha8).

    Resolution: $PLUMB_DATA_DIR/judge_prompts/{metric_name}.md.
    prompt_sha is the first 8 hex chars of sha256(text).
    """
```

- `metric_name` validated against `^[a-z][a-z0-9_]{0,63}$` (rejects path traversal, empty, uppercase).
- 8-char SHA prefix: collision risk negligible at ≤ 20 prompts per user; keeps `scorer_version` short.
- No internal cache — caller decides when to re-read after edits.

### 3.3 `plumb/adapters/_judge_common.py`

Public surface:

```python
class JudgeTransientError(Exception): ...   # 429 / 5xx / connection — retryable
class JudgeFatalError(Exception): ...       # 4xx (non-429) / parse / auth — not retryable

@dataclass(frozen=True)
class RawJudgeReply:
    text: str
    tokens_in: int
    tokens_out: int
    latency_ms: float

def redact_headers(headers: Mapping[str, str]) -> dict[str, str]: ...
def redact_body(text: str) -> str: ...

def with_judge_retry(fn):
    """tenacity: 3 attempts, wait_exponential_jitter(initial=1, max=8),
    retry_if_exception_type(JudgeTransientError), reraise=True."""

def parse_reply(text: str) -> tuple[str | None, float | None, str]:
    """Parse {"verdict": "pass"|"fail"|<float>, "rationale": str}. Strips
    code-fenced JSON. Returns (label, numeric, rationale). Raises ValueError
    on malformed reply."""
```

Redaction rules:

- Header names matched case-insensitively against `^(authorization|x-api-key|api-key)$` → value replaced with `<redacted>`.
- Body strings matched against `sk-[a-zA-Z0-9]{8,}` → matched substring replaced with `<redacted>`.

### 3.4 `plumb/adapters/judge_anthropic.py`

```python
class AnthropicJudge:
    name = "anthropic"
    version = "1"

    def __init__(self, *, api_key: str, prompt: str, prompt_sha: str,
                 client: anthropic.Anthropic | None = None) -> None: ...

    def score(self, *, metric_name: str, prompt: str, content: str,
              model: str, timeout_s: float = 60.0) -> JudgeResult: ...

    @with_judge_retry
    def _invoke(self, *, content: str, model: str, timeout_s: float) -> RawJudgeReply: ...
```

Key behaviours:

- **Constructor validation** — empty `api_key` / `prompt` / `prompt_sha` → `ValidationError`.
- **System prompt** sent with `cache_control={"type": "ephemeral"}` for prompt caching.
- **Request shape** — `temperature=0.0`, `max_tokens=1024`, `system=[{type:text, ...}]`, `messages=[{role:user, content}]`.
- **Exception mapping**:
  - `anthropic.RateLimitError` → `JudgeTransientError`
  - `anthropic.APIStatusError` 5xx → `JudgeTransientError`; 4xx (non-429) → `JudgeFatalError`
  - `anthropic.APIConnectionError` → `JudgeTransientError`
  - `anthropic.AnthropicError` → `JudgeFatalError`
- **`prompt` parameter on `score()`** is *ignored* — the adapter holds the canonical prompt loaded at construction time. Documented in the docstring; `pytest.warns` is *not* raised (the parameter exists only because the Protocol mandates it).
- **`scorer_version`** = `f"anthropic:{model}:{prompt_sha}"`; on fail-open, `+ ":error"`.
- **Token counts** via `resp.usage.input_tokens` / `resp.usage.output_tokens`.
- **Reply parsing** delegates to `_judge_common.parse_reply()`.

### 3.5 `plumb/adapters/judge_openai_compat.py`

Same shape as `judge_anthropic.py`, with these differences:

- Imports `openai` instead of `anthropic`.
- Constructor accepts `base_url: str | None`, `api_key: str` — passed through to `openai.OpenAI(...)`.
- Uses `chat.completions.create(messages=[{"role":"system", ...}, {"role":"user", ...}], temperature=0, max_tokens=1024, timeout=timeout_s)`.
- Maps exceptions:
  - `openai.RateLimitError` → `JudgeTransientError`
  - `openai.APIStatusError` 5xx → `JudgeTransientError`; 4xx (non-429) → `JudgeFatalError`
  - `openai.APIConnectionError` → `JudgeTransientError`
  - `openai.OpenAIError` → `JudgeFatalError`
- Token counts via `resp.usage.prompt_tokens` / `resp.usage.completion_tokens`.
- `name = "openai_compat"`; `_PROVIDER = "openai_compat"`.
- `scorer_version` = `f"openai_compat:{model}:{prompt_sha}"`.

### 3.6 `plumb/adapters/__init__.py` factory

```python
def get_judge_adapter(settings: "Settings", *, metric_name: str) -> "JudgeAdapter":
    """Instantiate the configured judge adapter.

    Reads settings.judge_provider ∈ {"anthropic", "openai_compat"}; loads the
    metric prompt from $PLUMB_DATA_DIR/judge_prompts/{metric}.md; instantiates
    the matching adapter with provider-specific credentials.

    Raises ValueError on missing provider/credentials; FileNotFoundError on
    missing prompt file.
    """
```

Lazy imports: `anthropic` and `openai` are only imported inside the matching branch, preserving NFR-Perf-6.

### 3.7 `plumb/config.py` extensions

```python
class Settings(BaseSettings):
    # existing
    data_dir: Path = Path.home() / ".plumb"
    log_level: str = "WARNING"
    autocapture: bool = True

    # new
    judge_provider: str | None = None              # "anthropic" | "openai_compat"
    judge_anthropic_api_key: str | None = None
    judge_api_key: str | None = None               # generic OpenAI-compatible key
    judge_base_url: str | None = None              # e.g. https://openrouter.ai/api/v1
    judge_model: str = "claude-sonnet-4-6"

    model_config = {"env_prefix": "PLUMB_", "case_sensitive": False}
```

Per-metric model env overrides (e.g. `PLUMB_JUDGE_MODEL_ROUTING_TOP1`) are deferred — the CLI `--model` flag covers v1.

### 3.8 `plumb/cli.py` wiring

Replace the existing stub:

```python
def _load_judge_adapter(provider: str, model: str, *, metric_name: str):
    from plumb.adapters import get_judge_adapter
    from plumb.config import get_settings
    return get_judge_adapter(get_settings(), metric_name=metric_name)
```

The `judge_run()` body forwards `metric` as `metric_name`. The `model` argument is retained because the Protocol mandates it on `score()`.

---

## 4. API Specifications

This slice exposes **no new HTTP endpoints**. It consumes:

- **Anthropic Messages API** — `POST https://api.anthropic.com/v1/messages` via `anthropic.Anthropic().messages.create(...)`.
- **OpenAI-compatible Chat Completions** — `POST {base_url}/chat/completions` via `openai.OpenAI(base_url=...).chat.completions.create(...)`.

### 4.1 Outbound request shape (both adapters)

| Field | Value |
|---|---|
| Method | POST |
| Auth | `x-api-key: <key>` (Anthropic, set by SDK) or `Authorization: Bearer <key>` (OpenAI-compat) |
| `model` | from CLI `--model` |
| `temperature` | `0.0` |
| `max_tokens` | `1024` |
| `system` / first message | judge prompt (from `judge_prompts/{metric}.md`) |
| `messages[user]` | candidate content (UTF-8 string from blob store) |
| `timeout` | 60.0 s |

### 4.2 Expected reply shape (judge prompt contract)

The judge prompt MUST instruct the model to reply with strict JSON:

```json
{"verdict": "pass" | "fail" | <float>, "rationale": "<≤ 1000 chars>"}
```

`parse_reply()` is tolerant of code-fenced JSON (`` ```json ... ``` ``) but rejects anything else with `ValueError`, which the adapter converts to fail-open.

### 4.3 Error mapping table

| Underlying SDK error | `_judge_common` exception | Adapter behaviour |
|---|---|---|
| `RateLimitError` (HTTP 429) | `JudgeTransientError` | retry up to 3× |
| `APIStatusError` 5xx | `JudgeTransientError` | retry up to 3× |
| `APIConnectionError` | `JudgeTransientError` | retry up to 3× |
| `APIStatusError` 4xx (non-429) | `JudgeFatalError` | no retry, fail-open |
| `AuthenticationError` (HTTP 401) | `JudgeFatalError` | no retry, fail-open |
| Reply not JSON / verdict invalid | `ValueError` | no retry, fail-open |

Fail-open = return `JudgeResult(value_label="error", scorer_version=f"{provider}:{model}:{prompt_sha}:error", ...)`. The CLI persists this row; operators re-run after fixing the issue.

### 4.4 Rate limiting

Outbound only — judge providers enforce their own. No inbound rate limiting (plumb has no inbound endpoint that calls judges synchronously).

---

## 5. Database Design

**No schema changes.** This slice writes to the existing `scores` table only via `SQLiteStorageAdapter.write_score()`. TRD §7.1 schema unchanged; PRD §8 Tier-1 "zero migrations" preserved.

### 5.1 Rows produced per `plumb judge run`

For each `(run, metric)` pair where no `scores` row exists with that `(run_id, metric_name)`:

```sql
INSERT INTO scores (
    score_id,            -- uuid4().hex
    run_id,              -- from runs query
    span_id,             -- NULL in v1 (run-level scores only)
    metric_name,         -- CLI --metric arg
    scorer,              -- 'judge'
    scorer_version,      -- {provider}:{model}:{prompt_sha} or :error
    value_numeric,       -- XOR with value_label
    value_label,         -- XOR with value_numeric, or 'error'
    scored_at            -- now(UTC) ISO-8601
);
```

### 5.2 Existing query reused

`plumb/cli.py` already implements the un-scored-runs query (`NOT EXISTS (SELECT 1 FROM scores ...)`). No changes here.

---

## 6. Algorithm & Logic Design

### 6.1 `plumb judge run` end-to-end (after this slice)

```
1. parse args (--model, --metric, --since, --task-id, --dry-run)
2. settings = get_settings()
3. if not settings.judge_provider: exit 1
4. fetch un-scored runs (parameterised SQL — already implemented)
5. if --dry-run: print count; exit 0
6. adapter = get_judge_adapter(settings, metric_name=metric)
   ├─ load_prompt(metric) → (text, sha8)
   ├─ instantiate AnthropicJudge | OpenAICompatibleJudge
   └─ raise on missing creds / unsupported provider
7. for each run:
     content = _load_run_content(storage, run.run_id)   # already implemented
     result = adapter.score(metric_name, prompt="", content, model)
     storage.write_score(Score(...))
8. exit 0
```

### 6.2 Retry decision (pseudocode)

```
attempt = 1
while attempt ≤ 3:
    try:
        return invoke_sdk()
    except RateLimitError, 5xx, ConnectionError as exc:
        wrap as JudgeTransientError
        if attempt == 3: raise        # exhausted; caller fails open
        wait = uniform(1, min(8, 2**attempt))
        sleep(wait)
        attempt += 1
    except 4xx, AuthError, OpenAIError, AnthropicError as exc:
        raise JudgeFatalError(exc)    # no retry; caller fails open
```

`tenacity` provides this exact behaviour: `wait_exponential_jitter(initial=1, max=8) + stop_after_attempt(3) + retry_if_exception_type(JudgeTransientError) + reraise=True`.

### 6.3 Reply parsing (pseudocode)

```
strip whitespace
if starts_with("```"):
    extract content between fences
    strip leading "json\n" if present
parse as JSON
if not dict: error
verdict = payload["verdict"]
rationale = str(payload.get("rationale", ""))[:1000]
if isinstance(verdict, float|int) and not bool: → numeric
if verdict in ("pass", "fail"):                  → label
else: error
```

---

## 7. Error Handling & Edge Cases

| Scenario | Behaviour |
|---|---|
| `PLUMB_JUDGE_PROVIDER` unset | CLI exits 1, message names env var (already implemented) |
| `PLUMB_JUDGE_ANTHROPIC_API_KEY` unset when provider=anthropic | Factory raises `ValueError`; CLI → exit 1 |
| `judge_prompts/{metric}.md` missing | Factory raises `FileNotFoundError`; CLI → exit 1 with absolute path |
| `metric_name` malformed | Factory raises `ValidationError`; CLI → exit 1 |
| HTTP 429 once, then 200 | Retry once with backoff; final result returned normally |
| HTTP 429 three times | Retries exhausted → fail-open with `value_label='error'` |
| HTTP 500 three times | Same as above |
| HTTP 401 (bad key) | No retry; fail-open with sanitized error in rationale |
| HTTP 400 (bad request) | No retry; fail-open |
| Connection reset mid-stream | `APIConnectionError` → retry-eligible |
| Reply is not JSON | Fail-open with truncated reply in rationale (key-redacted) |
| Reply has `verdict: "maybe"` | Fail-open ("verdict invalid") |
| `content` empty | Allowed; sent to judge as-is — judge prompt MUST handle |
| `content` very large (> 100k chars) | Sent as-is; SDK enforces context limit; OOC → `JudgeFatalError` → fail-open |
| Network completely down | Retried 3× → fail-open |
| Process killed during retry sleep | Tenacity unwinds; CLI persists prior scores; idempotent re-run |
| `--model sk-abc...` | Rejected up-front by regex (already implemented) |

### 7.1 What is NEVER swallowed

- `KeyboardInterrupt` — propagates so Ctrl-C exits cleanly.
- `SystemExit` — Typer's exit signalling.
- `MemoryError` — propagates.

`tenacity.retry` only retries `JudgeTransientError`, so the above propagate untouched.

---

## 8. Dependencies & Interfaces

### 8.1 New dependencies

| Package | Floor | Purpose |
|---|---|---|
| `tenacity` | ≥ 9.0 | Retry decorator with exponential jitter |

### 8.2 Existing dependencies used

- `anthropic` ≥ 0.40 — already in `pyproject.toml`.
- `openai` ≥ 1.50 — already in `pyproject.toml`.
- `pydantic-settings` — extended Settings.

### 8.3 Internal interfaces

- **Implements:** `plumb.core.ports.JudgeAdapter` (both new classes).
- **Consumed by:** `plumb.cli.judge_run()` via `plumb.adapters.get_judge_adapter()`.
- **Consumes:** `plumb._prompt_loader.load_prompt()`, `plumb.config.Settings`.

### 8.4 No coupling to

- `plumb.api` — adapters live below the public API boundary; lazy import inside the factory.
- `plumb.http` — read service does not invoke judges.
- `plumb.adapters.storage_sqlite` — score writes go through the CLI, not the storage adapter directly.

---

## 9. Security Considerations

| Concern | Mitigation | Verified by |
|---|---|---|
| API keys in logs | `_judge_common.redact_headers()` + `redact_body()` | `test_judge_common_redact.py` |
| API keys in CLI args | Existing `cli.judge_run` regex rejects `sk-` / `anthropic_` prefixes | `test_cli_judge_run.py::test_rejects_api_key_in_model` |
| API keys in error messages | Adapter wraps exceptions; rationale passed through `redact_body()` before write | Unit test asserts no `sk-…` / `Authorization:` substring in `JudgeResult.rationale` |
| Secrets read from filesystem | `pydantic-settings` env-var only; no file-backed secret loader added | Existing `test_config.py` pattern |
| Path traversal via `metric_name` | `_METRIC_NAME` regex restricts to `[a-z0-9_]{1,64}` | `test_prompt_loader.py::test_rejects_path_traversal` |
| Network egress on import | Lazy import inside `get_judge_adapter()`; `import plumb` does not import `anthropic` / `openai` | `tests/perf/test_cold_import.py` extended (assert SDK names absent from `sys.modules`) |
| Prompt injection via run content | Out of scope — judge prompts are the user's responsibility | n/a |

---

## 10. Testing Strategy

### 10.1 Test layout

```
tests/
├── unit/adapters/
│   ├── test_judge_anthropic.py        # ~150 LOC
│   ├── test_judge_openai_compat.py    # ~150 LOC
│   ├── test_judge_common_retry.py     # ~80  LOC
│   ├── test_judge_common_redact.py    # ~60  LOC
│   ├── test_judge_factory.py          # ~80  LOC
│   └── test_judge_parse_reply.py      # ~100 LOC
├── unit/test_prompt_loader.py         # ~80  LOC
└── cli/test_cli_judge_run.py          # ~150 LOC — closes CLI plan T3.1
```

### 10.2 Mocking strategy

- **SDK-level mocks** (preferred): `monkeypatch` `anthropic.Anthropic.messages.create` / `openai.OpenAI.chat.completions.create` to return canned response objects. Avoids `pytest-httpx` for the SDK paths because the SDKs do their own retry / pagination above httpx.
- **HTTP-level mocks** (for the OpenAI-compat base-URL test only): `pytest-httpx` to verify the request URL matches `PLUMB_JUDGE_BASE_URL` (TRD AC-INT-2).
- **Time mocks**: `freezegun` for `latency_ms`; `monkeypatch` `time.sleep` to zero out tenacity backoff during tests.
- **No real network**: session-scoped fixture monkeypatches `socket.socket.connect` to raise (already used in `tests/integration/autocapture/test_no_network_io.py`).

### 10.3 Coverage targets

- `plumb/adapters/judge_anthropic.py` — ≥ 90 %.
- `plumb/adapters/judge_openai_compat.py` — ≥ 90 %.
- `plumb/adapters/_judge_common.py` — 100 %.
- `plumb/_prompt_loader.py` — 100 %.

### 10.4 Property tests

- Hypothesis on `parse_reply()`: random strings → either valid `(label, numeric, rationale)` tuple or `ValueError`; never mixed state.

### 10.5 Reference acceptance criteria

1. **AC-JUDGE-1 (INT-JUDGE-1)** — Given `AnthropicJudge` with prompt SHA `"a1b2c3d4"`, when `score()` returns happy path, then `JudgeResult.scorer_version == "anthropic:claude-sonnet-4-6:a1b2c3d4"`.
2. **AC-JUDGE-2 (INT-JUDGE-2)** — Given `OpenAICompatibleJudge(base_url="https://openrouter.ai/api/v1")`, when `score()` is invoked, then the captured `httpx` request URL starts with that base URL and `Authorization: Bearer <token>` is present.
3. **AC-JUDGE-3 (INT-JUDGE-5)** — Given the SDK raises `RateLimitError` twice then succeeds, when `score()` is invoked, then the SDK is called 3 times, `time.sleep` is called twice with monotonically-increasing waits, and the result is a normal `JudgeResult`.
4. **AC-JUDGE-4 (INT-JUDGE-5 fail-open)** — Given the SDK raises `RateLimitError` 3 times, when `score()` is invoked, then the result is `JudgeResult(value_label="error", scorer_version=".../error", ...)` and a single WARNING is logged with no key prefix.
5. **AC-JUDGE-5 (NFR-Sec-2)** — Given the SDK raises `APIStatusError` whose body contains `sk-abc12345abcde`, when the warning log is emitted, then the formatted record does NOT contain `sk-abc12345abcde`.
6. **AC-JUDGE-6 (FR-SCORE-2)** — Every `JudgeResult` produced has non-empty `scorer_version`.
7. **AC-JUDGE-7 (Factory)** — Given `PLUMB_JUDGE_PROVIDER=anthropic` and `PLUMB_JUDGE_ANTHROPIC_API_KEY=test`, when `get_judge_adapter(settings, metric_name="routing_top1")` is called and `judge_prompts/routing_top1.md` exists, then an `AnthropicJudge` instance is returned.
8. **AC-JUDGE-8 (NFR-Perf-6)** — `python -X importtime -c "import plumb"` does NOT load `anthropic` or `openai`.
9. **AC-JUDGE-9 (CLI integration)** — Per CLI plan T3.1, `tests/cli/test_cli_judge_run.py` exercises 3 un-scored runs end-to-end with a fake adapter installed via factory monkeypatch; asserts 3 `scores` rows.

---

## 11. Performance Considerations

### 11.1 Expected load

- `plumb judge run` is batch-mode and user-invoked. Typical run: 30–500 runs per invocation; one HTTP call per run; sequential.
- No hot-path impact — adapters are not imported by `plumb.api` (NFR-Perf-5).

### 11.2 Optimizations applied

1. **Anthropic prompt caching** via `cache_control` on the system prompt — repeat runs are 90 %+ cheaper after first call.
2. **Lazy SDK import** inside `get_judge_adapter()` so they don't slow `import plumb`.
3. **No retry on fatal errors** — bad-key / bad-prompt requests aren't quadrupled.
4. **Sequential, not concurrent** — concurrency adds rate-limit complexity for marginal benefit at N≤500. Tracked v1.1.

### 11.3 Cost discipline

- `temperature=0` and `max_tokens=1024` cap per-call cost.
- `PLUMB_JUDGE_MODEL` default is Sonnet (cheaper) per TRD §6.1; Opus is opt-in via `--model`.
- `--dry-run` flag available before any spend (already wired).

### 11.4 No caching of judge replies in v1

Re-running `plumb judge run` against the same `(run, metric)` is a no-op via the un-scored-runs query. There is no in-memory result cache (would conflict with the user's expectation that re-running re-judges if they delete the prior score).

---

## 12. Implementation Phases

Phases summarized below; per-task ACs and file lists live in [`v1-judge-adapters-tasks.md`](./v1-judge-adapters-tasks.md).

| Phase | Objective | Key tasks | Deliverable |
|---|---|---|---|
| **1 — Scaffolding** | Land the prompt loader, common utilities, and config extensions | T1.1 add `tenacity`; T1.2 prompt loader; T1.3 `_judge_common`; T1.4 config extensions | All shared utilities merged, ≥ 95 % coverage |
| **2 — `AnthropicJudge`** | Ship the Anthropic adapter | T2.1 `judge_anthropic.py` + tests | Adapter passes mocked-SDK unit tests, ≥ 90 % coverage |
| **3 — `OpenAICompatibleJudge`** | Ship the OpenAI-compatible adapter | T3.1 `judge_openai_compat.py` + tests | Adapter passes mocked-SDK + base-URL HTTP-level test (AC-INT-2) |
| **4 — Factory + CLI wiring** | Replace the `_load_judge_adapter` stub; close CLI plan T3.1 | T4.1 factory; T4.2 CLI wiring; T4.3 `test_cli_judge_run.py` | `plumb judge run` end-to-end works; CLI integration test green |
| **5 — Docs + verify** | Update docs, log deferred entries, run quality gates | T5.1 docs + `deferred-features.md`; T5.2 `verify` + `code-review` | All quality gates green; slice mergeable to `main` |

---

## 13. Pending Decisions & Clarifications

All design-time decisions resolved during clarification round (2026-04-30):

| Decision | Picked | Rationale |
|---|---|---|
| Prompt loading | **CLI/factory-owned** | Adapters stay thin HTTP wrappers; `scorer_version` composed in one place. |
| `scorer_version` ownership | **Adapter computes** | Matches INT-JUDGE-6 contract at the adapter boundary. |
| Retry library | **`tenacity`** | User-confirmed; less custom code. |
| `_load_judge_adapter` location | **Factory in `plumb/adapters/__init__.py`** | Keeps CLI thin; adapter package self-contained. |

No open decisions remain blocking Phase 1.

### 13.1 Items deliberately deferred (recorded in `deferred-features.md` by T5.1)

- **Per-metric model env overrides** (`PLUMB_JUDGE_MODEL_ROUTING_TOP1`) — CLI `--model` covers v1.
- **Concurrent judge calls** — sequential is fine at N≤500.
- **File-backed prompt edit UX** — user manages files manually in v1.
- **Streaming verdicts** — irrelevant for batch metrics.
- **Tool-use judges** — TRD §6.3 out of scope.
- **Agentic-CLI judges** — TRD §6.3 out of scope.
- **Multi-judge consensus / ensembling** — v2.

---

*End of TRS v1.*

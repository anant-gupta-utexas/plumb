# Tasks — `v1-autocapture/` (Autocapture Slice)

**Companion to:** [`v1-autocapture-plan.md`](./v1-autocapture-plan.md) and [`v1-autocapture-context.md`](./v1-autocapture-context.md)
**Owner:** anant
**Last updated:** 2026-04-30 (Phase 5 + 6 complete)

This is the implementation checklist. Each task carries effort (S = ≤ 1 hr, M = 1–4 hr, L = 4–8 hr, XL = > 8 hr), the files it touches, acceptance criteria, dependencies on other tasks, and testing requirements. Phases are sequential top-to-bottom; within a phase, tasks run in declared order unless flagged parallel.

---

## Pre-flight

- [x] **v1-storage-adapter slice MERGED.** (archived at `dev/archive/v1-storage-adapter/`) — BlobStore + StorageWriter singletons and `_init_storage_singletons()` are available.
- [x] **anthropic + openai SDKs added to `[dependency-groups].dev` in `pyproject.toml`.** Required for integration tests; runtime soft-deps already declared.
- [ ] **Working branch created:** `feat/v1-autocapture` from `main`.

---

## Phase 1 — Package skeleton + state registry [Effort: S+M+S]

**Objective:** Establish the autocapture package with no eager SDK imports, a thread-safe install/uninstall registry, and a public surface that no-ops cleanly when no SDKs are installed.

### Task 1.1 — Create autocapture package skeleton [Effort: S]

- **Description:** New empty package `plumb/autocapture/` with `__init__.py` declaring (but not yet implementing) `install()`, `uninstall()`, `is_installed()`. Package marker MUST NOT import anything from `_anthropic.py` / `_openai.py`.
- **Acceptance Criteria:**
    - [x] `plumb/autocapture/__init__.py` exists with three function stubs returning `None` / `False`.
    - [x] `python -c "import plumb.autocapture; print(plumb.autocapture.is_installed())"` prints `False`.
    - [x] `tests/perf/test_cold_import.py` (re-run with `PLUMB_AUTOCAPTURE=1`) still passes.
- **Files to Create/Modify:**
    - `plumb/autocapture/__init__.py` — new
    - `plumb/autocapture/_state.py` — new (empty placeholder)
- **Dependencies:** None (within this slice; storage slice is a pre-flight prereq).
- **Testing Requirements:** Unit (import smoke).

### Task 1.2 — Implement `_state.py` install registry [Effort: M]

- **Description:** `_Patch` dataclass + `_INSTALL_LOCK` (threading.Lock) + `_INSTALLED: dict[str, _Patch]`. Provide internal helpers `_register(patch)` / `_unregister(key)` / `_is_registered(key)` for use by per-provider modules.
- **Acceptance Criteria:**
    - [x] `_Patch` is a frozen dataclass with `target_module: str`, `target_qualname: str`, `original: Callable`.
    - [x] `_INSTALL_LOCK` is a module-level `threading.Lock`.
    - [x] `_register` / `_unregister` mutate `_INSTALLED` under the lock.
    - [x] Unit test: concurrent `_register` calls from 4 threads on distinct keys produce a 4-entry registry; same-key registration is idempotent.
- **Files to Create/Modify:**
    - `plumb/autocapture/_state.py` — implement
    - `tests/unit/autocapture/test_state.py` — new
- **Dependencies:** Task 1.1
- **Testing Requirements:** Unit.

### Task 1.3 — Wire public `install` / `uninstall` / `is_installed` [Effort: S]

- **Description:** `__init__.py` `install()` iterates over an internal `_PROVIDERS` tuple of `(name, try_install_callable)` pairs. Each `try_install` is imported lazily inside the function. `uninstall()` walks `_INSTALLED` and restores. `is_installed()` returns `bool(_INSTALLED)`.
- **Acceptance Criteria:**
    - [x] `install()` is idempotent — second call is a no-op.
    - [x] `uninstall()` is idempotent — leaves `_INSTALLED` empty.
    - [x] `install()` then `uninstall()` then `is_installed()` returns `False`.
    - [x] With neither anthropic nor openai installed, `install()` does nothing and `is_installed()` returns `False` without error.
- **Files to Create/Modify:**
    - `plumb/autocapture/__init__.py` — implement
    - `tests/unit/autocapture/test_install.py` — new
- **Dependencies:** Task 1.2
- **Testing Requirements:** Unit.

**Phase 1 Deliverables:**
- Working autocapture package with no-op install/uninstall (no SDKs patched yet).
- Thread-safe registry with unit tests.
- Cold-import budget intact.

---

## Phase 2 — Canonicalization + redaction [Effort: M+M+S]

**Objective:** Provider-agnostic JSON canonicalization with recursive secret redaction, ready for use by `_emit.py` in Phase 3.

### Task 2.1 — Implement `_payloads.py` canonical serializer [Effort: M]

- **Description:** Pure-function `_canonical_json(obj: Any) -> bytes` returning `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`. Plus the four provider-specific `canonicalize_{provider}_{direction}` shells that call it after extracting the relevant fields from SDK request kwargs / response objects.
- **Acceptance Criteria:**
    - [x] `_canonical_json({"b": 2, "a": 1})` == `_canonical_json({"a": 1, "b": 2})` (key-order insensitive).
    - [x] Result is `bytes` and round-trips: `json.loads(result.decode("utf-8")) == original_dict`.
    - [x] UTF-8 with non-ASCII (e.g., `"こんにちは"`) preserves multi-byte without surrogate pairs.
    - [x] Hypothesis property test: random nested dicts produce identical bytes regardless of input ordering.
- **Files to Create/Modify:**
    - `plumb/autocapture/_payloads.py` — new
    - `tests/unit/autocapture/test_payloads.py` — new
- **Dependencies:** Phase 1 complete
- **Testing Requirements:** Unit + property.

### Task 2.2 — Implement recursive secret redaction [Effort: M]

- **Description:** `_redact(obj: Any) -> Any` walks dicts/lists; for any dict key matching `re.compile(r"(?i)(api[_-]?key|(?<![a-zA-Z])token(?!s)|secret|authorization|x-api-key|bearer)")`, replace value with `"<redacted>"`. Pure function; never mutates input. Compile regex once at module load.
- **Acceptance Criteria:**
    - [x] `_redact({"api_key": "sk-real"})` → `{"api_key": "<redacted>"}`.
    - [x] Case-insensitive: `_redact({"API_KEY": "sk-real"})` redacts.
    - [x] Recursive: `_redact({"outer": {"nested_token": "abc"}})` redacts inside nested dict.
    - [x] List handling: `_redact([{"token": "x"}, {"token": "y"}])` redacts both.
    - [x] Non-secret keys preserved: `_redact({"messages": [...]})` untouched.
    - [x] Original input unchanged (immutability).
    - [x] Regex coverage test: assert positive matches for `api_key`, `apiKey`, `api-key`, `token`, `secret`, `authorization`, `x-api-key`, `bearer_token`. Assert negatives for `messages`, `model`, `temperature`, `max_tokens`.
- **Files to Create/Modify:**
    - `plumb/autocapture/_payloads.py` — extend
    - `tests/unit/autocapture/test_payloads.py` — extend
- **Dependencies:** Task 2.1
- **Testing Requirements:** Unit (incl. regex coverage table).

### Task 2.3 — Provider-specific extraction shells [Effort: S]

- **Description:** Implement four pairs of (request, response) extractors:
    - `canonicalize_anthropic_request(args, kwargs) -> bytes`
    - `canonicalize_anthropic_response(response) -> bytes`
    - `canonicalize_openai_chat_request(args, kwargs) -> bytes`
    - `canonicalize_openai_chat_response(response) -> bytes`
    - `canonicalize_openai_responses_request(args, kwargs) -> bytes`
    - `canonicalize_openai_responses_response(response) -> bytes`

  Each: build a dict from the SDK's input or response, redact, canonical-serialize. Response side uses `response.model_dump()` (pydantic v2) when available, else `dict(response)` fallback for plain dicts.
- **Acceptance Criteria:**
    - [x] Each function returns `bytes`.
    - [x] Anthropic request with `messages=[{"role":"user","content":"hi"}]` and `extra_headers={"Authorization":"Bearer sk-x"}` produces bytes with `<redacted>` and not `sk-x`.
    - [x] OpenAI chat response with `usage={"prompt_tokens":10,"completion_tokens":5}` round-trips token counts.
    - [x] Same input → identical bytes across two calls (determinism).
- **Files to Create/Modify:**
    - `plumb/autocapture/_payloads.py` — extend
    - `tests/unit/autocapture/test_payloads.py` — extend
- **Dependencies:** Task 2.2
- **Testing Requirements:** Unit.

**Phase 2 Deliverables:**
- `_payloads.py` complete with deterministic, redacted canonicalization for both providers.
- Hypothesis + table-driven tests passing.

---

## Phase 3 — Span emission [Effort: M+S]

**Objective:** Single internal `_emit` module that converts a request/response pair into a `Span` via `RunHandle.add_span` + `BlobStore.put`, with bullet-proof error swallowing.

### Task 3.1 — Implement `_emit.emit_success_span` and `emit_failure_span` [Effort: M]

- **Description:** Two functions per the TRS §3.6 contract. Both wrap their entire body in `try/except BaseException`; on internal failure, log structured WARNING and return `None`. Use a local `from plumb.api import _active_run, _blobstore` to avoid circular imports.
- **Acceptance Criteria:**
    - [x] `emit_success_span(provider="anthropic", endpoint="messages", model="claude-sonnet-4-6", request_payload=b'{"messages":[]}', response=<stub>, latency_ms=12.3)` calls `_FakeRunHandle.add_span` exactly once with the expected `Span` field shape.
    - [x] Sets `Span.kind = SpanKind.LLM`, `Span.name = "anthropic/messages/claude-sonnet-4-6"`, `Span.input_hash = sha256(request_payload).hexdigest()`, `Span.output_hash = sha256(canonical_response_bytes).hexdigest()`.
    - [x] Pulls `tokens_in` / `tokens_out` from `response.usage` (anthropic: `input_tokens`/`output_tokens`; openai chat: `prompt_tokens`/`completion_tokens`; openai responses: `input_tokens`/`output_tokens`).
    - [x] If `_active_run.get()` is `None`, emits a single DEBUG log and returns without calling `add_span`.
    - [x] If `_blobstore.put` raises, span is STILL emitted with computed hashes; WARNING logged.
    - [x] If anything else internal raises (e.g., bad response shape), WARNING logged and function returns silently — caller (the patched wrapper) is NOT informed.
    - [x] `emit_failure_span` records `Span.status = SpanStatus.FAILURE`, `Span.error_type = <provided string>`, `output_hash = None`, `tokens = None`.
- **Files to Create/Modify:**
    - `plumb/autocapture/_emit.py` — new
    - `tests/unit/autocapture/test_emit.py` — new (with `_FakeBlobStore` and `_FakeRunHandle` defined in module-local conftest)
- **Dependencies:** Phase 2 complete
- **Testing Requirements:** Unit.

### Task 3.2 — `_FakeBlobStore` and `_FakeRunHandle` test fixtures [Effort: S]

- **Description:** Add to `tests/unit/autocapture/conftest.py`. `_FakeBlobStore` exposes `put`/`get`/`exists` matching the `BlobStore` Protocol; tracks all puts in a `dict[str, bytes]` and a `put_call_count` int. `_FakeRunHandle` exposes `add_span` capturing args into `captured_spans: list[dict]`.
- **Acceptance Criteria:**
    - [x] Both fakes type-check against `plumb.core.ports.BlobStore` and the `RunHandle` interface respectively.
    - [x] Fixture `installed_emit_fakes` monkeypatches `plumb.api._blobstore` and `plumb.api._active_run.set(_FakeRunHandle())`; cleans up in teardown.
- **Files to Create/Modify:**
    - `tests/unit/autocapture/conftest.py` — new
- **Dependencies:** Task 3.1 (uses these in tests)
- **Testing Requirements:** Unit (the fixtures themselves are exercised by test_emit.py).

**Phase 3 Deliverables:**
- `_emit` complete, NFR-Rel-1 verified by unit test.
- Test fixtures ready for Phases 4–5.

---

## Phase 4 — Anthropic patches [Effort: M+M+S]

**Objective:** Sync + async patches for `Messages.create` / `AsyncMessages.create` with full integration coverage.

> **Parallelizable with Phase 5.** Different provider modules; only shared touch points are `_state.py` (already done) and `_emit.py` (already done).

### Task 4.1 — Implement `_anthropic._try_install` + sync wrapper [Effort: M]

- **Description:** Per TRS §3.4. `_try_install()` does `try: import anthropic; except ModuleNotFoundError: return`, resolves the two target classes (`Messages`, `AsyncMessages`), wraps each `.create` method, registers in `_state._INSTALLED`. Sync wrapper per TRS §3.4.2.
- **Acceptance Criteria:**
    - [x] `_try_install()` no-ops if `anthropic` not installed.
    - [x] After `_try_install()`, `_state._INSTALLED` contains keys `"anthropic.resources.messages.Messages.create"` and `"anthropic.resources.messages.AsyncMessages.create"`.
    - [x] Idempotent: second `_try_install()` does not double-wrap.
    - [x] If `anthropic` installed but the qualname has moved, WARNING logged and the missing target is skipped.
- **Files to Create/Modify:**
    - `plumb/autocapture/_anthropic.py` — new
    - `tests/unit/autocapture/test_anthropic_install.py` — new
- **Dependencies:** Phase 3 complete
- **Testing Requirements:** Unit.

### Task 4.2 — Async wrapper + integration tests with stubbed transport [Effort: M]

- **Description:** Async sibling of Task 4.1. Plus integration tests in `tests/integration/autocapture/test_anthropic_capture.py` that:
    - Construct an `Anthropic(transport=<canned_transport>)` client.
    - Inside `with run(task_id="x") as r:`, call `client.messages.create(...)`.
    - After block exits, query the SQLite DB (real adapter via `configured_api_real` fixture from storage slice) and assert exactly one `spans` row with `kind='llm'`, correct `name`, `input_hash`, `output_hash`, tokens.
    - Assert two blob files exist.
    - Async variant: same but `AsyncAnthropic` and `await client.messages.create(...)`.
- **Acceptance Criteria:**
    - [x] Sync integration test passes against real anthropic SDK (>= 0.40) with a custom transport returning a canned `MessageResponse`.
    - [x] Async integration test passes.
    - [x] FR-CAP-3 verified: assert `client.messages.create` return type is unchanged (an `anthropic.types.Message` instance).
    - [x] FR-EDGE-1 verified: a transport that raises `anthropic.RateLimitError` results in (a) the exception propagating to user code unchanged, (b) one `spans` row with `status='failure'`, `error_type='RateLimitError'`.
- **Files to Create/Modify:**
    - `plumb/autocapture/_anthropic.py` — extend (async)
    - `tests/integration/autocapture/test_anthropic_capture.py` — new
- **Dependencies:** Task 4.1
- **Testing Requirements:** Integration (requires anthropic in dev extras).

### Task 4.3 — Concurrent async capture test [Effort: S]

- **Description:** Spawn 3 nested `@run`-wrapped async functions via `asyncio.gather`; each makes 2 anthropic calls. Assert 6 `spans` rows + 3 `runs` rows + correct `parent_run_id` chains.
- **Acceptance Criteria:**
    - [x] `asyncio.gather` of 3 nested runs produces 3 distinct `runs` rows with no `parent_run_id` cross-pollution.
    - [x] Each run has 2 `spans` rows tied to its own `run_id`.
    - [x] Test runs in < 2 seconds.
- **Files to Create/Modify:**
    - `tests/integration/autocapture/test_async_capture.py` — new (covers both anthropic + openai in Phase 5)
- **Dependencies:** Task 4.2
- **Testing Requirements:** Integration (async).

**Phase 4 Deliverables:**
- Anthropic patches working sync + async with integration coverage.
- Concurrent-async test passing.

---

## Phase 5 — OpenAI patches [Effort: M+M+M+S]

**Objective:** Patches for both Chat Completions and Responses APIs (sync + async = 4 targets).

> **Parallelizable with Phase 4.**

### Task 5.1 — `_openai._try_install` + Chat Completions sync wrapper [Effort: M]

- **Description:** Per TRS §3.5. Targets `openai.resources.chat.completions.Completions.create` and `AsyncCompletions.create`. Sync wrapper per the same skeleton as anthropic, calling `canonicalize_openai_chat_*`.
- **Acceptance Criteria:**
    - [x] `_try_install` no-ops without openai.
    - [x] `_state._INSTALLED` contains the four expected keys after install (Chat sync+async + Responses sync+async).
    - [x] Idempotent.
- **Files to Create/Modify:**
    - `plumb/autocapture/_openai.py` — new
    - `tests/unit/autocapture/test_openai_install.py` — new
- **Dependencies:** Phase 3 complete
- **Testing Requirements:** Unit.

### Task 5.2 — OpenAI Chat Completions async wrapper + integration test [Effort: M]

- **Description:** Async sibling of Task 5.1. Integration test mirrors anthropic test: real `OpenAI` / `AsyncOpenAI` client with `http_client=` set to a custom in-process httpx client returning canned chat completions. Assert `Span.name` is `"openai/chat/<model>"`.
- **Acceptance Criteria:**
    - [x] Sync integration: `client.chat.completions.create(...)` inside a run produces one `kind='llm'` span with `name='openai/chat/gpt-4o'` (or whatever stub model).
    - [x] Async integration: same with `AsyncOpenAI`.
    - [x] FR-CAP-3: response object type unchanged.
    - [x] FR-EDGE-1: simulated `openai.RateLimitError` → exception re-raised + failure span recorded.
- **Files to Create/Modify:**
    - `plumb/autocapture/_openai.py` — extend (Chat async)
    - `tests/integration/autocapture/test_openai_capture.py` — new
- **Dependencies:** Task 5.1
- **Testing Requirements:** Integration.

### Task 5.3 — OpenAI Responses API sync + async wrappers + integration test [Effort: M]

- **Description:** Add wrappers for `Responses.create` / `AsyncResponses.create`. Span name `"openai/responses/<model>"`.
- **Acceptance Criteria:**
    - [x] Sync integration test for `client.responses.create(...)`.
    - [x] Async integration test for `await client.responses.create(...)`.
    - [x] Token counts pulled from `response.usage.input_tokens` / `output_tokens` (Responses API uses the same names as Anthropic, NOT chat's `prompt_tokens`).
- **Files to Create/Modify:**
    - `plumb/autocapture/_openai.py` — extend (Responses)
    - `tests/integration/autocapture/test_openai_capture.py` — extend
- **Dependencies:** Task 5.2
- **Testing Requirements:** Integration.

### Task 5.4 — Streaming = unsupported stub coverage [Effort: S]

- **Description:** Add tests that call both providers with `stream=True` and assert (a) the user's stream still works, (b) one span recorded with `error_type='unsupported_stream_capture'`, `status='success'`, `output_hash=None`, `tokens=None`.
- **Acceptance Criteria:**
    - [x] Anthropic `messages.stream(...)` test passes.
    - [x] OpenAI `chat.completions.create(stream=True)` test passes.
    - [x] User receives a working iterator/stream from the SDK.
- **Files to Create/Modify:**
    - `tests/integration/autocapture/test_streaming_unsupported.py` — new
- **Dependencies:** Tasks 4.2 + 5.3
- **Testing Requirements:** Integration.

**Phase 5 Deliverables:**
- OpenAI patches working for both Chat Completions and Responses APIs, sync + async.
- Streaming-stub tests document current behavior.

---

## Phase 6 — `plumb.api` integration + cold-import preservation [Effort: S+S+S]

**Objective:** Wire autocapture install into the storage slice's lazy `_init_storage_singletons()`; verify cold-import budget still passes.

### Task 6.1 — Wire install into lazy singleton init [Effort: S]

- **Description:** In `plumb/api.py`'s `_init_storage_singletons()` (added by storage slice), after `_blobstore` is set, conditionally call `plumb.autocapture.install()` when `Settings.autocapture is True`. Lazy import inside the function body.
- **Acceptance Criteria:**
    - [x] `import plumb` does NOT trigger `import anthropic` / `import openai` (verified by Task 6.3).
    - [x] First `with run(...)` triggers `_init_storage_singletons` which then triggers `autocapture.install()`.
    - [x] With `PLUMB_AUTOCAPTURE=0`, install is skipped; `is_installed()` returns False.
    - [x] Idempotent — multiple runs in the same process call `install()` only once (covered by `is_installed` early-return inside `install`).
- **Files to Create/Modify:**
    - `plumb/api.py` — modify `_init_storage_singletons()`
    - `tests/integration/autocapture/test_lazy_install.py` — new
- **Dependencies:** Phase 5 complete
- **Testing Requirements:** Integration.

### Task 6.2 — Re-export public surface in `plumb/__init__.py` [Effort: S]

- **Description:** Add `autocapture_install`, `autocapture_uninstall`, `autocapture_is_installed` to `plumb/__init__.py` and `__all__`.
- **Acceptance Criteria:**
    - [x] `from plumb import autocapture_install` works.
    - [x] `tests/unit/test_public_surface.py::test_only_run_is_public_entry_point` STILL PASSES (autocapture_* names are configuration utilities, not instrumentation entry points; the test's allowlist is updated accordingly).
- **Files to Create/Modify:**
    - `plumb/__init__.py` — modify
    - `tests/unit/test_public_surface.py` — modify allowlist
- **Dependencies:** Task 6.1
- **Testing Requirements:** Unit.

### Task 6.3 — Cold-import budget re-test with autocapture enabled [Effort: S]

- **Description:** Re-run the storage slice's cold-import test with `PLUMB_AUTOCAPTURE=1` set in the subprocess environment. Assert (a) total `import plumb` ≤ 200 ms, (b) stderr from `python -X importtime` does NOT mention `import anthropic` or `import openai`.
- **Acceptance Criteria:**
    - [x] Cold-import time ≤ 200 ms on CI runner (with 2× headroom locally).
    - [x] Subprocess stderr grep for `^import time:.*\banthropic\b` returns empty.
    - [x] Subprocess stderr grep for `^import time:.*\bopenai\b` returns empty.
- **Files to Create/Modify:**
    - `tests/perf/test_cold_import.py` — extend (parametrize over `PLUMB_AUTOCAPTURE` env)
- **Dependencies:** Task 6.2
- **Testing Requirements:** Performance.

**Phase 6 Deliverables:**
- Autocapture wired in, fully opt-out via env var.
- Cold-import budget intact.

---

## Phase 7 — Performance + security gates [Effort: M+M+S]

**Objective:** Lock in NFR-Perf-1 (≤ 1 ms added overhead per captured span), NFR-Sec-2 (no secrets in logs/blobs), NFR-Perf-5 (no network I/O).

### Task 7.1 — Performance benchmark `test_autocapture_overhead.py` [Effort: M]

- **Description:** Per TRS §10.2 perf section. Stub the original SDK method to `time.sleep(0.001)` (1 ms baseline); measure 10,000 wrapped calls; assert `(observed_p95 - 1ms) <= 1ms`.
- **Acceptance Criteria:**
    - [ ] Test passes on CI runner (ubuntu-24.04, macos-14).
    - [ ] Test prints baseline-vs-wrapped p50/p95/p99 in pytest output for visibility.
    - [ ] Failure mode: if overhead exceeds 1 ms p95, test fails with a clear "NFR-Perf-1 breached" message.
- **Files to Create/Modify:**
    - `tests/perf/test_autocapture_overhead.py` — new
- **Dependencies:** Phase 6 complete
- **Testing Requirements:** Performance.

### Task 7.2 — Secret redaction integration test [Effort: M]

- **Description:** Per TRS §9.1. Test passes nested `api_key="sk-test-real"` in extra_headers / metadata / kwargs to both anthropic and openai calls. After run close: read every blob written and the WARNING log capture; assert `b"sk-test-real"` never appears in any blob bytes nor any log line.
- **Acceptance Criteria:**
    - [ ] Anthropic: `extra_headers={"Authorization": "Bearer sk-test-real"}` → blob bytes contain `<redacted>`, never `sk-test-real`.
    - [ ] OpenAI: `extra_headers={"x-api-key": "sk-test-real"}` → same.
    - [ ] Forced internal failure (monkeypatch `_blobstore.put` to raise an exception whose `__str__` includes the secret) → WARNING log line excludes the secret (covered by `error_type` being class-name-only per TRS §9.1.3).
    - [ ] `caplog` capture inspected for any string matching `r"sk-[a-zA-Z0-9-]{8,}"` — must be empty.
- **Files to Create/Modify:**
    - `tests/integration/autocapture/test_secret_redaction.py` — new
- **Dependencies:** Task 7.1 (uses similar fixture scaffolding)
- **Testing Requirements:** Integration.

### Task 7.3 — No-network-IO test [Effort: S]

- **Description:** Per TRS §9.3. Patch `socket.socket.connect` to raise `RuntimeError("plumb opened a network connection")`. Install autocapture. Run a stubbed SDK call (transport-level mock — does not touch socket). Assert: SDK call completes, span is emitted, NO RuntimeError raised by plumb's own code.
- **Acceptance Criteria:**
    - [ ] Test passes — patched `socket.connect` is never called by plumb's internal code.
    - [ ] Test name + docstring reference NFR-Perf-5.
- **Files to Create/Modify:**
    - `tests/integration/autocapture/test_no_network_io.py` — new
- **Dependencies:** Phase 6 complete
- **Testing Requirements:** Integration.

**Phase 7 Deliverables:**
- All three NFR gates verified by CI-blocking tests.

---

## Phase 8 — Documentation + slice archive [Effort: S+S+S]

**Objective:** Update user-facing + architecture docs; archive the slice folder.

### Task 8.1 — Update `docs/3_guides/getting_started.md` [Effort: S]

- **Description:** Add a section after "Your first run" titled "Autocapture works automatically" — 5–10 lines explaining: with `PLUMB_AUTOCAPTURE=1` (default), any `anthropic` or `openai` call inside a `@run` block is auto-captured as a `kind='llm'` span; opt out with `PLUMB_AUTOCAPTURE=0`; manual override via `plumb.autocapture_install()` / `_uninstall()`.
- **Acceptance Criteria:**
    - [ ] Section added with one runnable code example.
    - [ ] Mentions the two providers covered + the `httpx`/streaming follow-up slices.
- **Files to Create/Modify:**
    - `docs/3_guides/getting_started.md` — modify
- **Dependencies:** Phase 7 complete
- **Testing Requirements:** Doc-only (manual review).

### Task 8.2 — Update `docs/2_architecture/SYSTEM_DESIGN.md` [Effort: S]

- **Description:** In §3 component table (and the component diagram if it lists adapters), mark `plumb/autocapture/` status as IMPLEMENTED. Add a one-line callout under the "Hot-path data flow" subsection that `_emit` writes to `BlobStore` and through `RunHandle.add_span` (no direct `StorageWriter` touch).
- **Acceptance Criteria:**
    - [ ] Component table updated.
    - [ ] Hot-path data flow text reflects autocapture's role.
- **Files to Create/Modify:**
    - `docs/2_architecture/SYSTEM_DESIGN.md` — modify
- **Dependencies:** Task 8.1
- **Testing Requirements:** Doc-only.

### Task 8.3 — Archive slice folder [Effort: S]

- **Description:** After PR merges to main and CI green: move `dev/active/v1-autocapture/` → `dev/archive/v1-autocapture/`. Add a one-line note at the top of the archived plan with the merge commit SHA and date.
- **Acceptance Criteria:**
    - [ ] Folder moved.
    - [ ] Archived plan top-matter notes the archive date + commit.
    - [ ] `dev/active/` no longer contains `v1-autocapture/`.
- **Files to Create/Modify:**
    - `dev/active/v1-autocapture/` → `dev/archive/v1-autocapture/`
- **Dependencies:** Task 8.2 + merge to main
- **Testing Requirements:** None (housekeeping).

**Phase 8 Deliverables:**
- User docs updated.
- Architecture doc reflects implemented state.
- Slice archived per repo workflow.

---

## Definition of Done (slice-level — repeated from context.md §10)

The autocapture slice is "done" when ALL of these are true:

1. [ ] All 8 phases complete and merged.
2. [ ] CI green: ruff + mypy (permissive on adapters) + pytest unit + integration + perf.
3. [ ] Coverage ≥ 90% slice-wide; project ≥ 75% gate still holding.
4. [ ] NFR-Perf-1 (≤ 1 ms p95 added overhead per captured span) verified on CI runner.
5. [ ] NFR-Perf-6 (cold import ≤ 200 ms) re-verified with `PLUMB_AUTOCAPTURE=1`.
6. [ ] NFR-Rel-1 (no caller-visible exceptions from plumb internal failure) covered by integration test.
7. [ ] NFR-Sec-2 (no secrets in logs or blob bytes) covered by `test_secret_redaction.py`.
8. [ ] `docs/3_guides/getting_started.md` updated.
9. [ ] `docs/2_architecture/SYSTEM_DESIGN.md` updated.
10. [ ] `dev/active/v1-autocapture/` archived.

---

*End of tasks for `v1-autocapture/` slice.*

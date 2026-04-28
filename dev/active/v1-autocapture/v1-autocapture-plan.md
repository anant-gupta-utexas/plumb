# TRS — `plumb/autocapture/` (v1 Autocapture Slice)

**Status:** Draft v1 — derived from [TRD](../../../docs/2_architecture/TRD.md) and [SDD](../../../docs/2_architecture/SYSTEM_DESIGN.md), follows [v1 Core+API TRS](../../archive/v1-core-and-api/v1-core-and-api-plan.md) and [v1 Storage Adapter TRS](../../archive/v1-storage-adapter/v1-storage-adapter-plan.md)
**Owner:** anant
**Last updated:** 2026-04-26
**Scope:** The third component slice of plumb v1: import-time monkey-patching of the `anthropic` and `openai` SDKs to auto-emit `kind='llm'` spans into the active `RunHandle`. Replaces manual `r.add_span(...)` calls for the two LLM SDKs FR-CAP-1 names.

> **What this is.** A Technical Requirements Specification (TRS) translating TRD-level FR-CAP and NFR-Rel/Perf IDs into module-level patch installers, span-emission contracts, and acceptance tests for the autocapture layer. Implementation phases (with task-level effort, files, and AC checklists) are in [`v1-autocapture-tasks.md`](./v1-autocapture-tasks.md); design rationale and resolved decisions are in [`v1-autocapture-context.md`](./v1-autocapture-context.md).
>
> **What this is not.** Not the CLI, HTTP, judge, or ATTACH-adapter slices. **Not the `httpx` tool-capture path** — `httpx` is split into a separate follow-up TRS (`v1-tool-autocapture/`) per resolved decision Q2. This slice covers `anthropic` (Messages API, sync + async) and `openai` (Chat Completions + Responses API, sync + async).

---

## 1. Overview & Scope

### 1.1 What this slice delivers

Import-time monkey-patch installers that emit `kind='llm'` spans into the active `RunHandle` whenever the user's code calls a supported SDK from inside an open run:

- `plumb/autocapture/__init__.py` — public `install()` / `uninstall()` and the `is_installed()` predicate. **No eager SDK imports** at package-load time (NFR-Perf-6).
- `plumb/autocapture/_state.py` — module-level install lock + `installed_patches: dict[str, _Patch]` registry (lets `uninstall()` undo cleanly even if SDKs reload).
- `plumb/autocapture/_anthropic.py` — patch for `anthropic.resources.messages.Messages.create` and `anthropic.resources.messages.AsyncMessages.create`. Lazy import; no-op if `anthropic` not installed.
- `plumb/autocapture/_openai.py` — patch for `openai.resources.chat.completions.Completions.create`, the async sibling, and `openai.resources.responses.Responses.create` (+ async). Lazy import; no-op if `openai` not installed.
- `plumb/autocapture/_emit.py` — internal helper that converts an SDK request/response pair into a `Span` and pushes it via `_active_run.get().add_span(...)`. Single source of truth for the span shape across providers.
- `plumb/autocapture/_payloads.py` — request/response → canonical bytes serialization for content-addressed hashing (deterministic JSON; `sort_keys=True`, `separators=(",",":")`, `ensure_ascii=False`).
- `plumb/api.py` — extend the lazy `_init_storage_singletons()` path to call `plumb.autocapture.install()` when `Settings.autocapture is True` (resolved decision Q1: lazy-on-first-`run()`, not at `import plumb`).
- `plumb/config.py` — already declares `autocapture: bool = True` from the storage slice; this slice consumes it.

### 1.2 What this slice does NOT deliver

- **No `httpx` patching.** Deferred to `v1-tool-autocapture/` per Q2 — needs heuristics for "what counts as a tool call" that aren't in scope here.
- **No third-party LLM SDK coverage** beyond `anthropic` + `openai` (e.g. no `cohere`, `google-genai`, `mistralai`). Users patching their own clients use `r.add_span(...)` manually until those land in follow-up slices.
- **No streaming-completion span semantics.** v1 captures the *non-stream* `create(...)` path. Streaming captures (multi-chunk `messages.stream(...)` / `client.chat.completions.create(stream=True)`) deferred to `v1-streaming-autocapture/` — they require span-on-first-token vs span-on-stream-close design work that would balloon this slice.
- **No agent-framework integration** (LangChain, LlamaIndex, AutoGen, CrewAI). Out of v1 entirely — those frameworks call the underlying SDKs, which this slice already covers.
- **No prompt-cache / batching introspection.** Anthropic prompt-cache hit/miss is recorded only if it appears in the response body's `usage` block; no header parsing.

### 1.3 Why this slice next

1. **Unblocks PRD Tier-1 "≥ 30 real instrumented runs" (Week 6).** Manual `add_span(...)` is a research crutch; autocapture is what makes instrumentation cheap enough that real workflows get recorded.
2. **Specifiable end-to-end now.** Storage slice (the prereq) lands the `StorageWriter` + `BlobStore` real adapters; autocapture is the first real *consumer* of both. No further design ambiguity remains downstream of those two slices.
3. **Unblocks downstream metric work.** `routing_top1` and `handoff_roundtrip` (PRD §4 metrics #7 and #8) read `spans.input_hash` / `spans.output_hash`; without autocapture populating them on every LLM call, those metrics have no data to query.
4. **Highest blast radius if wrong.** A misbehaving patch breaks the user's production agent. NFR-Rel-1 (plumb internal failure never raises into caller) is the critical gate and gets first-class testing here.

### 1.4 Anchor TRD/SDD references

| TRD/SDD section | What it constrains here |
|---|---|
| TRD FR-CAP-1 | SDKs to patch: `anthropic` + `openai` here; `httpx` deferred to next slice |
| TRD FR-CAP-2 | Contextvars + monkey-patching at import time; opt-in via `PLUMB_AUTOCAPTURE` env |
| TRD FR-CAP-3 | MUST NOT mutate caller-visible SDK behaviour (return type, exception type, timeout) |
| TRD FR-EDGE-1 | If SDK call raises, span gets `status='failure'`, `error_type=<class name>`; original exception re-raises unchanged |
| TRD NFR-Perf-1 | p95 ≤ 1 ms per captured span (overhead measured against the SDK's own latency, not added to it) |
| TRD NFR-Perf-5 | Zero synchronous network I/O on the hot path — autocapture itself MUST NOT make network calls |
| TRD NFR-Perf-6 | Cold-import budget — `import plumb` MUST NOT eager-import `anthropic` or `openai` |
| TRD NFR-Rel-1 | Internal failure NEVER raises into caller; degrade to WARNING log + best-effort span |
| TRD NFR-Sec-2 | No secrets in log output (Authorization headers, `api_key`, body fields named like `*_key`) |
| SDD §3.2 | `plumb/autocapture/` lives outside `plumb/core/`; depends on `plumb.api._active_run` and `RunHandle` |
| SDD §4.2 | Hot-path data flow: SDK call → patched method → buffer span → return user's value |

---

## 2. Requirements Summary

### 2.1 Functional requirements in scope

- **FR-CAP-1 (partial; MUST).** Auto-capture `anthropic` (sync + async Messages API) and `openai` (sync + async Chat Completions + Responses API) as `spans` rows of `kind='llm'`. (`httpx` deferred per §1.2.)
- **FR-CAP-2 (MUST).** Monkey-patching at import time, opt-in via `PLUMB_AUTOCAPTURE` (default `1`). Install lazily on first `run(...)` invocation, not at `import plumb` (resolved decision Q1).
- **FR-CAP-3 (MUST).** No mutation of caller-visible SDK behaviour. Return types, exception types, timeouts, retries, streaming flag, tool-use blocks pass through unchanged.
- **FR-EDGE-1 (MUST, partial).** Exception in SDK call → span recorded with `status='failure'`, `error_type=<exception class name>`, then exception re-raised unchanged.

### 2.2 NFRs in scope

- **NFR-Perf-1 (MUST).** p95 added overhead per captured LLM span ≤ 1 ms over 10,000 stub calls (real SDK latency stripped via mock client).
- **NFR-Perf-5 (MUST).** Patch installers and emission helpers MUST NOT initiate network I/O. Verified by import-graph + mock-failure tests.
- **NFR-Perf-6 (MUST).** `import plumb` does NOT eager-import `anthropic` or `openai` (verified by re-running the cold-import test from the core slice with autocapture enabled in env).
- **NFR-Rel-1 (MUST).** Patch-side failure (entity validation, blob-store write failure, contextvars miss) NEVER raises into caller. WARNING log + skip-the-span; the SDK call's own outcome reaches the caller unchanged.
- **NFR-Sec-2 (MUST).** No secrets logged. Adapter MUST redact `authorization`, `x-api-key`, and any request kwarg key matching `r"(?i)(api[_-]?key|token|secret|authorization)"` before logging. Body content is hashed and stored in the blob store; the bytes themselves do NOT appear in WARNING logs.

### 2.3 Out-of-scope NFRs

- NFR-Perf-2 (run close ≤ 50 ms) — covered by storage slice.
- NFR-Sec-1, NFR-Sec-4, NFR-Sec-5, NFR-Sec-6 — secrets config, HTTP loopback, file modes, telemetry — covered by config / HTTP / blob-store slices.
- NFR-Rel-2..4 — durability + idempotency — storage slice / ATTACH slice.
- NFR-Use-3 — `mypy --strict plumb/core/` — autocapture is in `plumb/autocapture/`, permissive mypy per TRD §4.4.

---

## 3. Detailed Component Design

### 3.1 Module layout

```
plumb/
├── autocapture/
│   ├── __init__.py            # public install() / uninstall() / is_installed()
│   ├── _state.py              # module-level install lock + patch registry
│   ├── _anthropic.py          # anthropic SDK patches (sync + async Messages)
│   ├── _openai.py             # openai SDK patches (Chat Completions + Responses, sync + async)
│   ├── _emit.py               # canonical request/response → Span emission
│   └── _payloads.py           # canonical-JSON serialization for hashing
├── api.py                     # MODIFIED: invoke autocapture.install() in lazy init
└── config.py                  # already declares `autocapture: bool` (no change)

tests/
├── unit/autocapture/          # patch install/uninstall, state registry, payload canonicalization, secret redaction, FR-CAP-3 surface preservation
├── integration/autocapture/   # full @run cycle with stubbed SDK clients (real anthropic + openai packages installed in test extras)
└── perf/test_autocapture_overhead.py   # NFR-Perf-1 gate
```

### 3.2 `_state.py` — install registry

```python
@dataclass
class _Patch:
    target_module: str             # e.g., "anthropic.resources.messages"
    target_qualname: str           # e.g., "Messages.create"
    original: Callable[..., Any]   # to restore on uninstall()

_INSTALL_LOCK: threading.Lock = threading.Lock()
_INSTALLED: dict[str, _Patch] = {}     # key = f"{target_module}.{target_qualname}"
```

- `_INSTALL_LOCK` makes install/uninstall thread-safe (multi-thread test fixtures depend on this).
- Single registry covers anthropic + openai; key collision = bug.

### 3.3 `__init__.py` — public surface

```python
def install() -> None:
    """Install all available SDK patches. Idempotent. Thread-safe.

    Patches that fail to import their target SDK are silently skipped.
    Patches whose target is already in _INSTALLED are no-ops.
    """

def uninstall() -> None:
    """Restore all originals. Idempotent. Thread-safe. For tests + opt-out.
    """

def is_installed() -> bool:
    """True if at least one patch is currently in _INSTALLED."""
```

`install()` calls `_anthropic._try_install()` and `_openai._try_install()` in declared order. Each `_try_install()` does its own `try: import …` and returns silently if the SDK is missing.

### 3.4 `_anthropic.py` — Anthropic patches

#### 3.4.1 Targets

| Target (post-`anthropic >= 0.40`) | Sync/async | Span kind |
|---|---|---|
| `anthropic.resources.messages.Messages.create` | sync | `llm` |
| `anthropic.resources.messages.AsyncMessages.create` | async | `llm` |

#### 3.4.2 Wrapper shape (sync)

```python
def _wrap_messages_create(original: Callable[..., Any]) -> Callable[..., Any]:
    @functools.wraps(original)
    def wrapper(self, *args, **kwargs):
        active = _active_run.get()
        if active is None:
            return original(self, *args, **kwargs)         # no run open → SDK call only

        start = time.perf_counter()
        request_payload = _payloads.canonicalize_anthropic_request(args, kwargs)
        try:
            response = original(self, *args, **kwargs)
        except BaseException as exc:                        # FR-EDGE-1 + FR-CAP-3
            _emit.emit_failure_span(
                provider="anthropic",
                model=kwargs.get("model"),
                request_payload=request_payload,
                latency_ms=(time.perf_counter() - start) * 1000,
                error_type=type(exc).__name__,
            )
            raise                                            # NEVER swallow user-visible exception

        _emit.emit_success_span(
            provider="anthropic",
            model=getattr(response, "model", None) or kwargs.get("model"),
            request_payload=request_payload,
            response=response,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return response
    return wrapper
```

#### 3.4.3 Async wrapper

Identical shape but `async def`, `await original(...)`, `await`-aware `try`/`except`. Both wrappers share `_emit.emit_success_span` / `_emit.emit_failure_span`.

#### 3.4.4 SDK-version compatibility note

`anthropic >= 0.40` is the TRD floor (§5.4). The class path `anthropic.resources.messages.{Messages,AsyncMessages}` is stable from 0.40 onward. If a future SDK rev moves the class, the install attempt raises `AttributeError`, which is caught + logged as a single WARNING (`autocapture.skip: anthropic patch target moved`) and the patch is skipped — never raised into the user.

### 3.5 `_openai.py` — OpenAI patches

#### 3.5.1 Targets

| Target (post-`openai >= 1.50`) | Sync/async | Span kind |
|---|---|---|
| `openai.resources.chat.completions.Completions.create` | sync | `llm` |
| `openai.resources.chat.completions.AsyncCompletions.create` | async | `llm` |
| `openai.resources.responses.Responses.create` | sync | `llm` |
| `openai.resources.responses.AsyncResponses.create` | async | `llm` |

#### 3.5.2 Wrapper shape

Same skeleton as `_anthropic._wrap_messages_create` (above), with:
- `_payloads.canonicalize_openai_chat_request` for chat-completions args
- `_payloads.canonicalize_openai_responses_request` for the Responses API
- `_emit.emit_success_span(provider="openai", ...)` consumes the SDK response

#### 3.5.3 Both endpoints, one provider tag

`provider="openai"` for both Chat Completions and Responses spans. The endpoint distinction is captured in `Span.name` per Q6 — `"openai/chat/{model}"` vs `"openai/responses/{model}"`. This keeps single-provider queries simple while preserving the endpoint signal.

### 3.6 `_emit.py` — span construction

Single internal function used by both providers:

```python
def emit_success_span(
    *,
    provider: str,                   # "anthropic" | "openai"
    endpoint: str | None,            # "messages" | "chat" | "responses"
    model: str | None,
    request_payload: bytes,          # canonical JSON
    response: Any,                   # SDK-native response object
    latency_ms: float,
) -> None: ...

def emit_failure_span(
    *,
    provider: str,
    endpoint: str | None,
    model: str | None,
    request_payload: bytes,
    latency_ms: float,
    error_type: str,
) -> None: ...
```

Both functions:
1. Resolve `_active_run.get()` — if `None`, log a single DEBUG line and return (defensive; the wrappers already short-circuit, but this is belt-and-suspenders).
2. Compute `input_hash = sha256(request_payload).hexdigest()`.
3. For success: serialize the response to canonical JSON via `_payloads.canonicalize_{provider}_response(response)`; compute `output_hash`; extract `tokens_in`/`tokens_out` from the response's `usage` block (Q5 — body only, never headers).
4. Compose `Span.name` as `f"{provider}/{endpoint}/{model or 'unknown'}"` (Q6, with the endpoint qualifier where relevant).
5. Push request and response payloads to the blob store via `_blobstore.put(request_payload)` / `_blobstore.put(response_payload)`. **Errors here are caught + logged WARNING + the span is still emitted with hashes set to the computed digests** (digests are the source of truth; the blob store is a content cache).
6. Call `active.add_span(kind=SpanKind.LLM, name=…, input_hash=…, output_hash=…, tokens=(in, out), latency_ms=…, status=…, error_type=…)`. `RunHandle.add_span` already buffers in-memory; no flush here.
7. The whole emit sequence is wrapped in a top-level `try/except BaseException` — internal failure WARNING + return (NFR-Rel-1).

Important: **`_emit` does NOT touch storage directly** — it goes through `RunHandle.add_span()` (which buffers, gets flushed on run close by the storage slice's `StorageWriter.write_run`). It DOES touch the blob store directly because span content needs to be addressable before the run closes.

### 3.7 `_payloads.py` — canonical serialization

Two pure helpers per provider × direction (4 total per provider):

```python
def canonicalize_anthropic_request(args: tuple, kwargs: dict) -> bytes:
    """Return canonical JSON bytes: sort_keys, no whitespace, UTF-8.

    Strips: any `*_key`, `authorization`, `x-api-key` keys at any nesting depth.
    Preserves: messages, model, system, tools, tool_choice, temperature, top_p,
               top_k, max_tokens, stop_sequences, metadata, extra_headers (redacted).
    """

def canonicalize_anthropic_response(response: Any) -> bytes:
    """Return canonical JSON bytes of the response.

    Reads from response.model_dump() (pydantic v2). Preserves usage,
    content blocks, stop_reason, model, id. Redacts nothing (responses
    don't contain secrets).
    """
```

Equivalent pair for `openai_chat_request/response` and `openai_responses_request/response`.

**Canonical JSON shape:** `json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")`. Fixed across all callers — same content always hashes to the same digest (deterministic across processes and Python versions).

**Redaction set (for log lines + canonical request bytes):** keys matching `re.compile(r"(?i)(api[_-]?key|token|secret|authorization|x-api-key|bearer)")` are replaced with the literal string `"<redacted>"`. Applied recursively at every dict level. Hashes computed AFTER redaction so the same prompt with two different API keys produces the same `input_hash` (the desired behavior — content addressing is about content, not credentials).

### 3.8 `api.py` integration

Single addition to the existing lazy `_init_storage_singletons()` (added in storage slice):

```python
def _init_storage_singletons() -> None:
    global _storage, _blobstore
    if _storage is not None:
        return
    settings = get_settings()
    data_dir = ensure_data_dir(settings)
    _storage = SQLiteStorageAdapter(data_dir / "plumb.db", clock=_clock)
    _blobstore = FilesystemBlobStore(data_dir / "blobs")
    _storage_writer = _storage              # satisfy existing module-level singleton

    # NEW: opt-in autocapture install
    if settings.autocapture:
        from plumb import autocapture       # lazy — preserves NFR-Perf-6
        autocapture.install()
```

`autocapture` module exposes `_active_run` indirectly via importing `plumb.api._active_run` lazily inside `_emit.emit_*`. To avoid a circular import at module-load time, `_emit.py` does:

```python
def _get_active_run() -> "RunHandle | None":
    from plumb.api import _active_run        # local import; resolved at first call
    return _active_run.get()
```

The local import has zero hot-path cost after the first call (Python caches module lookups in `sys.modules`).

---

## 4. API Specifications

### 4.1 Public Python surface added by this slice

```python
# plumb/__init__.py — re-export added
from plumb.autocapture import install as autocapture_install
from plumb.autocapture import uninstall as autocapture_uninstall
from plumb.autocapture import is_installed as autocapture_is_installed

__all__ += ["autocapture_install", "autocapture_uninstall", "autocapture_is_installed"]
```

Three NEW public callables, all under the `autocapture_*` namespace prefix to keep the top-level `plumb.run` instrumentation surface untouched (AC-API-1 still passes — only `run` is the public *instrumentation* entry point; install/uninstall are *configuration* utilities).

Also addable as `plumb.autocapture.install()` etc. for users who prefer the qualified form.

### 4.2 No new HTTP / CLI surface

CLI surface (e.g., `plumb autocapture status`) deferred to CLI slice. HTTP service has no autocapture endpoints.

### 4.3 Error surface

Autocapture NEVER raises into the caller. The only exceptions in scope are:

| Raised | Cause |
|---|---|
| (none) | — |

Internal `_emit` and patch wrappers catch `BaseException` (yes, including `SystemExit` and `KeyboardInterrupt` — autocapture's own bugs must never abort the user's process; the SDK call's own re-raise is what propagates control flow per FR-EDGE-1).

WARNING log lines emitted on internal failure follow this structured shape:

```python
logger.warning(
    "plumb autocapture failure",
    extra={
        "plumb_internal_error": True,
        "subsystem": "autocapture",
        "provider": "anthropic" | "openai",
        "endpoint": "messages" | "chat" | "responses",
        "error_class": type(err).__name__,
    },
)
```

Body content NEVER appears in `extra` (NFR-Sec-2). Provider + endpoint + error class are the diagnosable triple.

---

## 5. Database Design

**Out of scope.** This slice writes through `RunHandle.add_span` (already in core+API slice) and `BlobStore.put` (storage slice). It introduces no new tables, indexes, or constraints.

Effect on existing schema: every captured LLM span produces one `spans` row (`kind='llm'`) and zero or two new blob files (one for request, one for response — deduped if either content was already stored).

---

## 6. Algorithm & Logic Design

### 6.1 Patch install (idempotent)

```
with _INSTALL_LOCK:
    for try_install in (_anthropic._try_install, _openai._try_install):
        try:
            try_install()                    # adds entries to _INSTALLED
        except BaseException as exc:
            logger.warning("autocapture.install failed", ...)
            continue                         # one provider's failure must not block another
```

Each `_try_install`:

```
try:
    import <sdk>
except ModuleNotFoundError:
    return                                   # SDK not installed in user's env; skip silently
for (module_path, qualname) in TARGETS:
    key = f"{module_path}.{qualname}"
    if key in _INSTALLED:
        continue                             # idempotent
    cls = _resolve_qualname(module_path, qualname)
    original = getattr(cls, qualname.split(".")[-1])
    wrapped = _wrap(original)
    setattr(cls, qualname.split(".")[-1], wrapped)
    _INSTALLED[key] = _Patch(module_path, qualname, original)
```

### 6.2 Uninstall (idempotent, restores originals)

```
with _INSTALL_LOCK:
    for key, patch in list(_INSTALLED.items()):
        cls = _resolve_qualname(patch.target_module, patch.target_qualname)
        setattr(cls, patch.target_qualname.split(".")[-1], patch.original)
        del _INSTALLED[key]
```

### 6.3 Active-run resolution + dedup

The wrappers MUST NOT capture if there is no open run. Pseudocode (sync wrapper):

```
active = _active_run.get()
if active is None:
    return original(self, *args, **kwargs)   # transparent passthrough
```

This is the normal path when the user calls a patched SDK *outside* a `@run` / `with run(...)` block — plumb is invisible.

### 6.4 Token extraction

| Provider | Endpoint | Source field |
|---|---|---|
| `anthropic` | Messages | `response.usage.input_tokens`, `response.usage.output_tokens` |
| `openai` | Chat Completions | `response.usage.prompt_tokens`, `response.usage.completion_tokens` |
| `openai` | Responses | `response.usage.input_tokens`, `response.usage.output_tokens` |

If the response object doesn't have a `usage` block (rare; some test stubs omit it), `tokens=None` is passed to `add_span` (already nullable). NEVER read from headers (Q5 resolution).

### 6.5 Cold-import preservation

Verified by re-running the storage slice's `tests/perf/test_cold_import.py` with `PLUMB_AUTOCAPTURE=1` set in env. The `import plumb` path:

1. `plumb/__init__.py` imports `plumb.api.run` and `plumb.autocapture.install` (the latter is just a function reference; importing the module only executes `_state.py`'s `_INSTALLED = {}` plus a few `from … import …` lines).
2. `plumb.autocapture._anthropic` and `_openai` are NOT imported at this stage — they are loaded only when `_try_install()` runs, which itself only runs from inside the lazy `_init_storage_singletons()` path on first `run(...)` call.
3. `import anthropic` / `import openai` happen ONLY if (a) the user calls `run(...)` AND (b) the SDK is installed AND (c) `Settings.autocapture is True`.

---

## 7. Error Handling & Edge Cases

| Scenario | Behavior |
|---|---|
| `import plumb` with neither anthropic nor openai installed | `install()` no-ops both; `is_installed()` returns False; user code unaffected |
| User calls patched SDK outside any open run | Passthrough — original SDK behavior, no span emitted |
| SDK raises `RateLimitError` mid-call | Span recorded with `status='failure'`, `error_type='RateLimitError'`; original exception re-raised unchanged (FR-EDGE-1) |
| User calls SDK inside a run, then `r.abort()` then more SDK calls | After abort, `RunHandle.add_span` is a no-op (per core slice spec); patched wrapper still runs the SDK call normally — only span buffering is suppressed |
| SDK call returns a streaming response (`stream=True`) | Span emitted with `output_hash` of the *request*, `tokens=None`, `error_type='unsupported_stream_capture'`, `status='success'`; user's stream still works because we returned the response unchanged. (Streaming spans deferred per §1.2.) |
| Blob store `put` fails (disk full) | Span still buffered with computed `input_hash`/`output_hash`; WARNING logged; on run close the storage writer persists the span row; the blob content is missing — `BlobStore.get` later raises `BlobNotFoundError` for that hash, which downstream metric code handles |
| `_active_run.get()` returns a handle whose run was closed in another thread | Possible only via misuse; `add_span` on a closed handle no-ops in the core slice; defensive — emit attempts the call, swallows on `PlumbError` |
| User installs `anthropic` mid-process via `pip install` then re-imports | `install()` not re-invoked automatically; user must call `plumb.autocapture_install()` to pick it up. Documented behavior |
| User passes `extra_headers={"Authorization": "Bearer sk-…"}` to anthropic | Redacted in canonical request bytes BEFORE hashing AND in any WARNING log line; `input_hash` is therefore stable across credential rotations |
| Two threads call `install()` concurrently | `_INSTALL_LOCK` serializes; second call sees populated `_INSTALLED` and no-ops |
| `uninstall()` called when nothing installed | No-op (idempotent) |
| User monkey-patches the same target after plumb does | Plumb's wrapper is overwritten; `uninstall()` then restores the *original* (not the user's patch) — documented gotcha |
| Async function uses `asyncio.to_thread(sync_anthropic_client.messages.create, ...)` | Contextvars copy via `asyncio.to_thread` (Python 3.13 behavior); `_active_run` reads correctly; span captured |

**Retry strategy:** None at this layer. Patches don't retry; they record what happened.
**Fallbacks:** If patching fails for one target, others still install (per-target try/except in `_try_install`).

---

## 8. Dependencies & Interfaces

### 8.1 Runtime dependencies (this slice adds nothing required at install time)

The TRD already declares `anthropic >= 0.40` and `openai >= 1.50` as runtime deps for the judge slice (§5.4). Autocapture treats them as **soft** dependencies — present at runtime if the user has them, no-ops if not. No `extras_require` block needed; the package marker imports stay lazy.

### 8.2 Stdlib

`functools`, `inspect`, `time`, `threading`, `hashlib`, `json`, `re`, `logging`, `typing`.

### 8.3 Internal interfaces

- **Provides:** `plumb.autocapture.install/uninstall/is_installed` for the API layer's lazy init + for explicit user opt-in/opt-out.
- **Consumes:** `plumb.api._active_run` (contextvar), `plumb.api._blobstore` (for blob writes), `plumb.core.entities.SpanKind/SpanStatus`, `plumb.core.errors.PlumbError`.

### 8.4 Test-only

`pytest`, `pytest-asyncio`. Tests install the real `anthropic` and `openai` packages in a `dev` extras group and use SDK-native client objects with `respx` / a custom in-process transport so no actual network calls happen. **No `pytest-httpx` required for autocapture tests** — we patch at the SDK method, above the HTTP layer.

---

## 9. Security Considerations

### 9.1 Secret redaction (NFR-Sec-2)

Three places where secrets could leak:

1. **Request canonicalization for hashing.** Redact recursively before serialization. Test: pass `api_key="sk-real"` in nested request; assert the canonical bytes contain `"<redacted>"` and not `"sk-real"`.
2. **WARNING log on patch failure.** Log structure NEVER includes request kwargs or response body — only provider, endpoint, error class.
3. **`_emit.emit_failure_span`'s `error_type` field.** SDK exceptions can include the URL (which sometimes contains query-string auth on misconfigured endpoints). We use `type(exc).__name__` only, not `str(exc)`. Test: stub an SDK exception whose `__str__` includes a fake API key; assert `error_type` is just the class name.

Redaction regex compiled once at module load: `re.compile(r"(?i)(api[_-]?key|token|secret|authorization|x-api-key|bearer)")`.

### 9.2 Blob store contents

LLM request and response payloads land in the blob store under `$PLUMB_DATA_DIR/blobs/`. After redaction, these still contain user prompts and model outputs — both potentially sensitive. The blob-store slice's mode-bit guarantees (`0700` dir, `0600` files) protect against other-user reads on the same machine. No additional encryption in v1 (deferred — see `docs/2_architecture/deferred-features.md`).

### 9.3 No hot-path network I/O

Verified by `tests/integration/autocapture/test_no_network_io.py`: install autocapture, monkeypatch `socket.socket.connect` to raise; run a stubbed SDK call; assert the call completes and span is emitted (i.e., autocapture itself opened no socket). Belt-and-suspenders for NFR-Perf-5.

### 9.4 Deferred to other slices

Secret env reads (NFR-Sec-1) → judge slice. HTTP auth (NFR-Sec-4) → HTTP slice. SQL injection (NFR-Sec-3) → storage slice (already done).

---

## 10. Testing Strategy

### 10.1 Coverage targets

| Module | Target |
|---|---|
| `plumb/autocapture/__init__.py` | ≥ 95% |
| `plumb/autocapture/_state.py` | ≥ 95% |
| `plumb/autocapture/_anthropic.py` | ≥ 90% |
| `plumb/autocapture/_openai.py` | ≥ 90% |
| `plumb/autocapture/_emit.py` | ≥ 90% |
| `plumb/autocapture/_payloads.py` | ≥ 95% |

Slice-wide: **≥ 90%** (project gate is 75%; autocapture is testable end-to-end with stubs).

### 10.2 Test categories

- **Unit (`tests/unit/autocapture/`):**
  - Install/uninstall idempotency, registry shape after each call.
  - Payload canonicalization: same input always produces same bytes; ordering invariance; UTF-8 correctness; redaction regex hits all expected cases.
  - `_emit.emit_*` with a `_FakeBlobStore` and `_FakeRunHandle` — assert correct `Span` field shape.
  - Cold-import: `python -X importtime -c 'import plumb'` does NOT emit `import anthropic` or `import openai` lines.

- **Integration (`tests/integration/autocapture/`):**
  - Real anthropic SDK + custom transport that returns canned responses → full `with run(...)` block → assert `spans` row + 2 blobs persisted.
  - Same for openai (chat) + openai (responses).
  - Async variants (`AsyncAnthropic`, `AsyncOpenAI`).
  - Concurrent `asyncio.gather` of three nested runs each calling SDKs → contextvars correctness.
  - SDK raises → exception re-raises, span still recorded with `status='failure'`.
  - SDK call OUTSIDE a run → no span, no error.
  - `r.abort()` then SDK call → no span buffered; SDK still runs.
  - `PLUMB_AUTOCAPTURE=0` → `is_installed()` False; SDK calls passthrough.
  - **No-network test** (NFR-Perf-5): patch `socket.socket.connect` to raise; install + run stubbed SDK; assert no socket opened by plumb itself.
  - **Secret-redaction test** (NFR-Sec-2): pass nested `api_key`; assert blob bytes contain `<redacted>`, never the secret value.

- **Performance (`tests/perf/test_autocapture_overhead.py`):**
  - 10,000 stubbed SDK calls inside an open run with `_FakeBlobStore`; assert `(observed_p95 - baseline_sdk_call_p95) <= 1ms` per NFR-Perf-1.
  - Subprocess `python -X importtime` re-confirms cold-import budget with autocapture enabled.

### 10.3 Fakes / fixtures

- `_FakeBlobStore`: in-memory `dict[str, bytes]`; satisfies the `BlobStore` Protocol; tracks `put`/`get` call counts.
- `_FakeRunHandle`: minimal stand-in exposing `add_span` capturing args; not real `RunHandle` (which requires a `_RunBuilder`). Tests use real `RunHandle` via the API layer for integration tests; fake for unit tests of `_emit` only.
- `installed_autocapture` (autouse=False): pytest fixture that installs autocapture in setup, uninstalls in teardown, and asserts `_INSTALLED` is empty post-test. Prevents test pollution.
- `stubbed_anthropic_client` / `stubbed_openai_client`: real SDK client classes with the HTTP transport replaced by an in-process callable returning canned responses.

### 10.4 Acceptance criteria coverage

| TRD AC | Test |
|---|---|
| AC-API-1 (no third instrumentation entry point) | `tests/unit/test_public_surface.py::test_only_run_is_public_entry_point` — ensure `autocapture_install` is not classed as instrumentation entry (regex/list excluded) |
| AC-PERF-1 (p95 ≤ 1 ms per span; here per CAPTURED span) | `tests/perf/test_autocapture_overhead.py` |
| AC-REL-1 (storage failure does not raise into caller) — extended | `tests/integration/autocapture/test_emit_failure_does_not_raise.py` |

(AC-PERF-2 + storage AC + judge ACs out of this slice's scope.)

### 10.5 Mocking policy

- **Network:** stub at the SDK transport layer (custom `httpx.MockTransport` or equivalent for the OpenAI client; `respx` for additional safety). NEVER hit a real Anthropic / OpenAI endpoint in CI.
- **Time:** `time.perf_counter` replaced via `monkeypatch.setattr` for deterministic latency assertions.
- **Filesystem:** real `tmp_path` blob store for integration tests; fake in-memory dict for unit tests.

---

## 11. Performance Considerations

### 11.1 Hot-path budgets

| Operation | Budget | Strategy |
|---|---|---|
| Patched wrapper overhead (no run open) | ≤ 5 µs | Single contextvar read + bool check, no allocations |
| Patched wrapper overhead (run open, success path) | ≤ 1 ms | Two `canonicalize_*` calls + sha256 (small payloads) + 1–2 `BlobStore.put` + `add_span` |
| `canonicalize_*` for typical 4-message Anthropic request (~2 KB) | ≤ 200 µs | `json.dumps(sort_keys=True)` is C-implemented; no recursion overhead |
| `sha256` for 2 KB | ≤ 50 µs | OpenSSL-backed; trivial |
| `BlobStore.put` for 2 KB | ≤ 500 µs | One `O_CREAT|O_EXCL` + write + fsync; storage slice's measured budget |

The 1 ms NFR-Perf-1 budget is per-span overhead ON TOP OF the SDK call. Real SDK calls are 100 ms – 30 s, so 1 ms is invisible.

### 11.2 Memory

- `canonicalize_*` produces a single `bytes` object per call (transient).
- No request/response held in `RunHandle` beyond the hashes (already true in core slice).
- Patch registry is bounded — at most ~6 entries (2 anthropic + 4 openai targets).

### 11.3 Caching

- Redaction regex compiled at module load.
- `_resolve_qualname` results NOT cached — called twice per process lifetime (install + uninstall).
- `from plumb.api import _active_run` inside `_emit._get_active_run` is cached by `sys.modules` after first call (Python's normal import semantics).

### 11.4 Concurrency

- `_INSTALL_LOCK` serializes install/uninstall.
- The wrappers themselves are lock-free — contextvars are per-task/thread, blob-store `put` is safe under `O_EXCL`, `RunHandle.add_span` appends to a per-run list (no cross-handle contention because each run has its own `_RunBuilder`).
- Async-safe: contextvars propagate correctly across `asyncio.gather`, `asyncio.to_thread`, and standard task spawning in Python 3.13.

### 11.5 Monitoring

None. The same WARNING log lines (`extra={"plumb_internal_error": True, "subsystem": "autocapture", ...}`) are the only telemetry surface — users grep their logs.

---

## 12. Resolved Decisions & Pending Items

All seven design decisions resolved on 2026-04-26 with the recommended options accepted by the user:

| # | Decision | Resolution |
|---|---|---|
| 1 | Install trigger | **Lazy-on-first-`run()`**, not at `import plumb`. Preserves NFR-Perf-6 unconditionally |
| 2 | SDK scope | **`anthropic` + `openai` only** in this slice; `httpx` deferred to `v1-tool-autocapture/` |
| 3 | Patching strategy | **Wrap the high-level method** (e.g. `Messages.create`), not the SDK's internal HTTP transport |
| 4 | Hash + blob policy for LLM spans | **Hash + write blob** for both request and response; populate `input_hash`/`output_hash` on every captured span |
| 5 | Token-count source | **Response body's `usage` block only**; never headers |
| 6 | `Span.name` shape | **`{provider}/{endpoint}/{model}`** (e.g. `"anthropic/messages/claude-sonnet-4-6"`); fall back to `"unknown"` when model not yet known |
| 7 | Redaction key set | **Regex over keys**: `r"(?i)(api[_-]?key|token|secret|authorization|x-api-key|bearer)"`; recursive at every dict depth; applied BEFORE hashing |

### Pending — only if revisited later:

- **Streaming span semantics.** Out of v1 (deferred to `v1-streaming-autocapture/`). v1 captures `stream=True` calls with `error_type='unsupported_stream_capture'` so we know how often it's used and can prioritize accordingly.
- **Other LLM SDKs** (`google-genai`, `cohere`, `mistralai`). Out of v1; users use manual `r.add_span(...)` until added.
- **Capture middleware ordering.** If the user has their own monkeypatch on the same target, plumb's wrapper might be the inner or outer layer depending on import order. Documented gotcha in §7; no programmatic enforcement in v1.

---

## 13. Implementation Phases

Full task breakdown with effort, files, AC checklists, and dependencies is in [`v1-autocapture-tasks.md`](./v1-autocapture-tasks.md). Summary:

| Phase | Objective | Effort |
|---|---|---|
| **1** | Autocapture package skeleton + state registry + `install`/`uninstall` plumbing | S+M+S |
| **2** | `_payloads.py` canonicalization + redaction (provider-agnostic core) | M+M+S |
| **3** | `_emit.py` span emission + blob writes (against `_FakeBlobStore` first) | M+S |
| **4** | `_anthropic.py` patches (sync + async Messages) + integration tests | M+M+S |
| **5** | `_openai.py` patches (Chat Completions + Responses, sync + async) + integration tests | M+M+M+S |
| **6** | `plumb.api` lazy install integration + cold-import preservation tests | S+S+S |
| **7** | Performance benchmark + secret-redaction + no-network gates | M+M+S |
| **8** | Documentation update + slice archive | S+S+S |

Phases 4 and 5 may run in parallel after Phases 1–3 land (separate provider modules; no shared mutable state outside `_state.py`).

---

## 14. Forward Pointers (Other TRSes)

| Follow-up TRS | Builds on this slice |
|---|---|
| `v1-tool-autocapture/` | Reuses `_emit`, `_payloads` patterns; adds `httpx` patcher (`kind='tool'`); adds heuristics for "what counts as a tool call" |
| `v1-streaming-autocapture/` | Replaces the `stream=True` no-op with real chunked-span emission; introduces span-on-stream-close |
| `v1-judge-adapters/` | Independent — judges run *outside* any `@run` context, so autocapture is inactive there by design |
| `v1-cli/` | May add `plumb autocapture status` subcommand exposing `is_installed()` + counts of installed targets |
| `v1-http/` | None — autocapture has no HTTP surface |

---

*End of TRS v1 — `plumb/autocapture/` autocapture slice.*

# Context — `v1-autocapture/` (Autocapture Slice)

**Companion to:** [`v1-autocapture-plan.md`](./v1-autocapture-plan.md)
**Owner:** anant
**Last updated:** 2026-04-26

This document captures the *why* behind the TRS — design rationale, files touched, dependencies between slices, key decisions (made + open), and integration points that future contributors (or future-me) need to understand without re-reading the full TRS.

---

## 1. Slice Purpose (1-Paragraph)

`plumb/autocapture/` is the import-time monkey-patch layer that turns supported LLM SDK calls (`anthropic.messages.create`, `openai.chat.completions.create`, `openai.responses.create` — sync + async) into `kind='llm'` spans on the active `RunHandle`. It is the difference between manual instrumentation (`r.add_span(SpanKind.LLM, "anthropic", ...)` everywhere) and zero-friction instrumentation. Without this slice, PRD Tier-1 metric "≥ 30 real instrumented runs by Week 6" is at risk because manual instrumentation friction discourages adoption.

---

## 2. Prerequisites & Slice Order

```
v1-core-and-api/         ← MERGED — contextvar `_active_run`, `RunHandle.add_span` exist
        │
        ▼
v1-storage-adapter/      ← MERGED — provides BlobStore + StorageWriter singletons (see dev/archive/v1-storage-adapter/)
        │
        ▼
v1-autocapture/   (this) ← TRS DRAFTED — first slice to actually USE the BlobStore on the hot path
        │
        ├─► v1-tool-autocapture/    (httpx; depends on this slice's _emit + _payloads)
        ├─► v1-streaming-autocapture/   (stream=True semantics; replaces this slice's no-op)
        └─► v1-cli/    (independent; may add `plumb autocapture status`)
```

**Hard prerequisite:** the storage slice must land first because `_emit.py` writes to `plumb.api._blobstore`. Until storage lands, autocapture's integration tests would have no real `BlobStore` to assert against (the `_FakeBlobStore` is only sufficient for unit tests).

---

## 3. Files Touched

### 3.1 New files

| File | Purpose |
|---|---|
| `plumb/autocapture/__init__.py` | Public `install()` / `uninstall()` / `is_installed()`; no eager SDK imports |
| `plumb/autocapture/_state.py` | `_INSTALL_LOCK`, `_INSTALLED: dict[str, _Patch]` registry, `_Patch` dataclass |
| `plumb/autocapture/_anthropic.py` | Sync + async patches for `Messages.create` / `AsyncMessages.create` |
| `plumb/autocapture/_openai.py` | Sync + async patches for Chat Completions + Responses APIs (4 targets total) |
| `plumb/autocapture/_emit.py` | `emit_success_span` / `emit_failure_span` — single source of truth for span shape |
| `plumb/autocapture/_payloads.py` | Canonical-JSON serialization + recursive secret redaction |
| `tests/unit/autocapture/__init__.py` | Package marker |
| `tests/unit/autocapture/test_install.py` | install/uninstall idempotency + registry shape |
| `tests/unit/autocapture/test_payloads.py` | Canonicalization determinism + redaction regex coverage |
| `tests/unit/autocapture/test_emit.py` | Span field shape via `_FakeBlobStore` + `_FakeRunHandle` |
| `tests/integration/autocapture/__init__.py` | Package marker |
| `tests/integration/autocapture/test_anthropic_capture.py` | Real anthropic SDK + canned transport, full `with run(...)` |
| `tests/integration/autocapture/test_openai_capture.py` | Real openai SDK (chat + responses) |
| `tests/integration/autocapture/test_async_capture.py` | `AsyncAnthropic` / `AsyncOpenAI` + `asyncio.gather` |
| `tests/integration/autocapture/test_no_network_io.py` | Patch `socket.socket.connect`; assert plumb itself opens nothing |
| `tests/integration/autocapture/test_secret_redaction.py` | Pass nested `api_key`; assert blob bytes contain `<redacted>` |
| `tests/perf/test_autocapture_overhead.py` | NFR-Perf-1 gate: 10k stub calls, p95 ≤ 1ms ON TOP OF baseline |

### 3.2 Modified files

| File | Change |
|---|---|
| `plumb/__init__.py` | Re-export `autocapture_install`, `autocapture_uninstall`, `autocapture_is_installed` |
| `plumb/api.py` | Inside `_init_storage_singletons()` (added by storage slice), conditionally call `autocapture.install()` when `Settings.autocapture is True` |
| `tests/perf/test_cold_import.py` | Re-run with `PLUMB_AUTOCAPTURE=1` set; budget MUST still pass |
| `pyproject.toml` | Add `anthropic` and `openai` to `[dependency-groups].dev` (test extras) so integration tests can import them; runtime deps already declared per TRD §5.4 |

### 3.3 Untouched (key non-changes)

- `plumb/core/*` — autocapture lives outside core; no entity, port, or stats changes.
- `plumb/api.py`'s `RunHandle.add_span` signature — autocapture calls the existing API; no new method.
- TRD / PRD / SDD source-of-truth docs — this slice does not change requirements.
- `docs/2_architecture/TRD.md` §7.1 schema — no DDL changes (per TRD DATA-MIG-1 zero-migration goal).

---

## 4. Resolved Decisions (with Rationale)

All seven were resolved on 2026-04-26 with the user accepting recommendations. Rationale here for future-me:

### Q1 — Install trigger: Lazy on first `run(...)`, not at `import plumb`

**Rejected:** Auto-install at `import plumb` (when env var is `1`). This is the PRD/TRD's literal phrasing and what most observability libraries do.

**Why rejected:** It forces `import anthropic` / `import openai` at `import plumb` time, which torches the 200 ms cold-import budget (`anthropic` alone takes 60–120 ms cold). And it's wasteful — most processes that import plumb may never actually open a run (test discovery, doc tools, etc.).

**Accepted:** Lazy install in the same code path that lazy-initializes the storage adapter (Q1 of storage TRS). One control point for all "real I/O happens here" effects. Drops cold-import budget to ~30 ms in the no-run case.

### Q2 — SDK scope: anthropic + openai only (httpx deferred)

**Why deferred:** `httpx` is an HTTP client. The semantic question "is this httpx call a tool call worth capturing as `kind='tool'`?" is not answerable without heuristics (URL allowlist? caller-frame inspection? both have failure modes). Bundling that into this TRS would more than double the spec.

**Path forward:** `v1-tool-autocapture/` slice will reuse `_emit` + `_payloads` from this slice and add a heuristic + opt-in URL filter.

### Q3 — Patching strategy: high-level method (not internal transport)

**Rejected:** Wrap `client._client.http_client` (the internal httpx instance). Single patch covers all SDK methods.

**Why rejected:** Couples plumb to the SDK's *private* surface. `_client.http_client` has been renamed twice in the openai SDK's 1.x line. A maintenance trap.

**Accepted:** Wrap `Messages.create` etc. — public, stable. Documented at the SDK class level in both anthropic and openai. Requires explicit per-target patches, but those are the SDK's intentional public surface and change with deprecation cycles.

### Q4 — Hash + blob writes for both request and response

**Why:** Two PRD §4 metrics (`routing_top1` and `handoff_roundtrip`) require comparing input/output content across spans. Without `input_hash`/`output_hash` populated and a blob to dereference, those metrics return null. Skipping this in v1 autocapture would defer the metrics themselves to v2 — unacceptable per Tier-1 success criteria.

### Q5 — Token counts: response body only

**Why:** SDK `response.usage.{input,output}_tokens` is the documented, stable, structured surface. HTTP headers (`x-ratelimit-tokens`) are SDK-internal and disappear when the SDK abstracts them away. Body-only is the no-regret call.

### Q6 — Span name: `{provider}/{endpoint}/{model}`

**Why composite, not just model:** Composite enables three useful queries with one column:
- "All anthropic calls" → `name LIKE 'anthropic/%'`
- "All Responses-API calls" → `name LIKE 'openai/responses/%'`
- "All Sonnet-4-6 calls" → `name LIKE '%/claude-sonnet-4-6'`

**Endpoint qualifier matters** because openai has two distinct endpoints (chat + responses) with different semantics — a user investigating routing should see them split.

### Q7 — Recursive regex-based redaction

**Why regex over allowlist:** SDK kwargs evolve; an allowlist would silently leak any new credential field name added by the SDK. Regex over key names is conservative — false positives (unrelated fields named `*_token`) are visible (`<redacted>`) and easy to debug; false negatives (a real secret named something unexpected) are silent leaks. Choose visibility.

**Applied BEFORE hashing:** Same prompt with two different API keys must produce the same `input_hash`. Otherwise content-addressing is broken (every credential rotation invalidates every blob).

---

## 5. Pending Decisions (open for future revisit)

| # | Item | Default chosen | Trigger to revisit |
|---|---|---|---|
| 1 | Streaming-completion span semantics | v1: emit failure-shaped span with `error_type='unsupported_stream_capture'` | Once we see >5% of captured spans tagged `unsupported_stream_capture`, prioritize `v1-streaming-autocapture/` |
| 2 | Other LLM SDKs (`google-genai`, `cohere`, `mistralai`, `mistral-common`) | v1: not patched; users use manual `r.add_span` | When a user files an issue OR when one of these reaches >10% of judge-adapter usage |
| 3 | Capture middleware ordering vs user monkey-patches | Documented gotcha; no enforcement | If multiple users hit it, add a `plumb autocapture verify` CLI subcommand |
| 4 | `httpx` patching for tool capture | Deferred to `v1-tool-autocapture/` | Whenever the user starts a tool-rich workflow whose tool calls aren't visible |

These are tracked here (not in `docs/2_architecture/deferred-features.md`) because they are autocapture-slice-specific and likely to be revisited in a follow-up TRS rather than a separate spec doc.

---

## 6. Integration Points

### 6.1 With v1-core-and-api/ (already merged)

- **Reads:** `plumb.api._active_run` (contextvar) inside `_emit._get_active_run()`.
- **Calls:** `RunHandle.add_span(kind=SpanKind.LLM, name=..., input_hash=..., output_hash=..., tokens=(in, out), latency_ms=..., status=..., error_type=...)`. **No changes to `add_span` signature** — autocapture is a pure consumer.
- **Respects:** `RunHandle._builder.aborted` semantics — `add_span` after abort no-ops, so autocapture inherits this behavior automatically.

### 6.2 With v1-storage-adapter/ (MERGED — see dev/archive/v1-storage-adapter/)

- **Reads:** `plumb.api._blobstore` inside `_emit.emit_*` to put request/response bytes.
- **Indirect:** `RunHandle.add_span` buffers the span; `StorageWriter.write_run` (run-close path) persists it. Autocapture does NOT touch the storage writer directly.
- **Lazy init:** Both autocapture install AND blob-store init happen inside `_init_storage_singletons()`. Order matters: blob store first, then autocapture install. Otherwise autocapture's first emit would race with `_blobstore is None`.

### 6.3 With v1-judge-adapters/ (future)

- **No interaction.** Judge calls run *outside* any `@run` block by design (judges are batch jobs invoked via CLI). `_active_run.get()` returns `None`, and the patched wrappers fall through to the original SDK call. Autocapture is invisible to the judge layer.

### 6.4 With v1-cli/ (future)

- **Possible:** A `plumb autocapture status` subcommand exposing `is_installed()` + the patched-target list. Not in this slice; the CLI slice will own its own surface.

---

## 7. Key Architectural Constraints

These are non-obvious things that the implementation must respect — recording so they don't get accidentally violated:

1. **Cold-import budget is the binding NFR.** `import plumb` MUST NOT pull in `anthropic` or `openai`. Verified by `tests/perf/test_cold_import.py` re-run with `PLUMB_AUTOCAPTURE=1`. Any future refactor that adds an eager `from anthropic import …` at module top will break the gate.

2. **NFR-Rel-1 covers BaseException, not just Exception.** Autocapture's internal try/except blocks catch `BaseException` because a `KeyboardInterrupt` mid-emit must not leak from the wrapper into the user's code. The user's SDK call's own raise reaches the user via the explicit `raise` in the wrapper — that path preserves user control flow.

3. **Hash-before-blob-write order.** `input_hash` and `output_hash` are computed deterministically from canonical bytes; the blob store is a side-effect cache. If `BlobStore.put` fails, the span is still recorded with correct hashes. This means downstream `BlobStore.get` may raise `BlobNotFoundError` for hashes that *were* observed — by design.

4. **Redaction is a security gate, not a UX nicety.** The redaction regex is tested against a known-bad list of secret-shaped kwargs. Adding a new SDK kwarg that smuggles a secret under an unexpected name (e.g. `client_credential`) requires updating the regex first; else credentials hit the blob store on disk.

5. **Two endpoints under one provider.** `provider="openai"` covers both Chat Completions and Responses; the endpoint distinction lives in `Span.name`. Don't introduce `provider="openai-responses"` — it would explode the provider taxonomy and break `name LIKE 'openai/%'` queries.

6. **Streaming is intentionally a stub.** v1 captures `stream=True` calls with `error_type='unsupported_stream_capture'` and `tokens=None`. This is signal, not failure — the field tells `v1-streaming-autocapture/` how often it's used. Don't try to "make it work" in v1.

---

## 8. Non-Obvious Test Considerations

- **Integration tests need real anthropic + openai installed.** Add to `[dependency-groups].dev` in pyproject. CI installs dev group via `uv sync --all-groups`.
- **Use SDK-native client + custom transport, not pytest-httpx.** Patching at the SDK method means we never reach the HTTP layer in tests; pytest-httpx wouldn't even fire. Use the SDK's documented `transport=` constructor parameter (anthropic) or `http_client=` (openai) with an in-process callable returning canned responses.
- **`test_no_network_io.py` is the NFR-Perf-5 gate.** Patching `socket.socket.connect` to raise is the cleanest way to assert nothing in plumb's emit path opens a connection — a future refactor that adds an HTTP fallback (e.g. for telemetry) would be caught by this test.
- **Cold-import test must be a SUBPROCESS.** Running it in-process pollutes `sys.modules`; use `subprocess.run(["python", "-X", "importtime", "-c", "import plumb"])` and grep stderr.
- **Performance test isolates the OVERHEAD, not the SDK call.** Stub the original SDK method to `time.sleep(0.001)` (1 ms baseline), then measure the wrapped call's latency; the difference is plumb's overhead. NFR-Perf-1 ≤ 1 ms is on this difference, not the total.

---

## 9. Risks & Mitigations

| Risk | Mitigation |
|---|---|
| anthropic / openai SDK changes patch target qualname | Per-target try/except in `_try_install`; WARNING log on miss; other targets still install. Pinning floor (`>=0.40` / `>=1.50`) per TRD limits drift. |
| Patching is invisible to user; debugging is hard | Public `is_installed()` returns bool; future CLI surface (`plumb autocapture status`) lists patched targets. Documented in user-facing guide as part of slice deliverable. |
| Redaction regex misses a secret-shaped kwarg | Conservative regex (broad match); test corpus of known SDK secret kwargs; CI grep for sketchy patterns in committed test fixtures. |
| Hot-path overhead breaches 1 ms | `tests/perf/test_autocapture_overhead.py` is CI-blocking; canonicalization implemented as `json.dumps(sort_keys=True)` (C-fast); blob writes are the only fsync; storage slice already gates that at ≤ 5 ms. |
| Cold-import breach from a future refactor | `tests/perf/test_cold_import.py` re-runs with `PLUMB_AUTOCAPTURE=1`; CI fails the budget. |
| User's own monkey-patch overlaps | Documented gotcha; uninstall restores plumb's saved original (which may be the user's patch or the SDK original depending on order). No programmatic enforcement in v1. |

---

## 10. Definition of Done (slice-level)

The autocapture slice is "done" when ALL of these are true:

1. All eight implementation phases (per `v1-autocapture-tasks.md`) complete and merged.
2. CI green: ruff + mypy (permissive on adapters) + pytest unit + integration + perf.
3. Coverage ≥ 90% slice-wide; project ≥ 75% gate still holding.
4. NFR-Perf-1 (≤ 1 ms p95 added overhead per captured span) verified on CI runner.
5. NFR-Perf-6 (cold import ≤ 200 ms) re-verified with `PLUMB_AUTOCAPTURE=1`.
6. NFR-Rel-1 (no caller-visible exceptions from plumb internal failure) covered by integration test.
7. NFR-Sec-2 (no secrets in logs or blob bytes) covered by `test_secret_redaction.py`.
8. `docs/3_guides/getting_started.md` updated with the "autocapture works automatically" paragraph.
9. `docs/2_architecture/SYSTEM_DESIGN.md` §3 component table updated to mark `plumb/autocapture/` as IMPLEMENTED.
10. `dev/active/v1-autocapture/` moved to `dev/archive/v1-autocapture/`.

---

*End of context for `v1-autocapture/` slice.*

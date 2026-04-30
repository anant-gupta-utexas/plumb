# Code Review — `v1-autocapture`

**Reviewer:** Code Reviewer persona via `/consult-experts`  
**Date:** 2026-04-30  
**Scope reviewed:** `dev/active/v1-autocapture/`, `plumb/autocapture/`, lazy API integration, autocapture unit/integration/perf tests, and related docs.

## Executive Summary

The autocapture slice is broadly well structured and matches the intended ports-and-adapters boundary: provider patching lives outside `plumb/core/`, emission goes through `RunHandle.add_span`, and provider imports remain lazy. The focused test suite is also substantial: unit, integration, async, streaming marker, secret-redaction, cold-import, and performance coverage all ran green locally.

However, there are two important correctness gaps before this should be treated as merge-ready. First, request canonicalization happens before the wrapper's protected SDK-call block, so a plumb-side serialization bug can prevent the user's SDK call entirely, violating FR-CAP-3 / NFR-Rel-1. Second, the performance gate excludes the real filesystem blob writes even though the TRS budget explicitly includes them, so NFR-Perf-1 is not actually proven for real captured spans.

**Verification run:** `pytest tests/unit/autocapture tests/integration/autocapture tests/perf/test_autocapture_overhead.py tests/perf/test_cold_import.py -q` → `145 passed in 33.11s`.

## Critical Issues (must fix)

### 1. Request canonicalization failures can raise into user code and skip the SDK call

**Severity:** Critical  
**Files:** `plumb/autocapture/_anthropic.py`, `plumb/autocapture/_openai.py`, `plumb/autocapture/_payloads.py`  
**Requirement impact:** Violates FR-CAP-3 and NFR-Rel-1: autocapture internals must not mutate caller-visible SDK behavior or raise into the caller.

The wrappers check for an active run, then canonicalize request kwargs before entering the `try` block that preserves SDK exceptions. If `_payloads.canonicalize_*_request()` raises, the original SDK method is never called. This can happen for non-JSON-serializable user kwargs or SDK helper objects, for example `httpx.Headers`, custom metadata objects, Pydantic objects, datetimes, file-like inputs, or future SDK sentinels.

Anthropic sync/stream/async have the issue:

```python
request_payload = _payloads.canonicalize_anthropic_request(args, kwargs)
try:
    response = original(self, *args, **kwargs)
```

OpenAI sync/async have the same shape:

```python
request_payload = getattr(_payloads, req_canon)(args, kwargs)
try:
    response = original(self, *args, **kwargs)
```

This is especially risky because the error would be a plumb `TypeError`/serialization failure, not the provider's normal exception type, and the user workload would not run.

**Recommended fix:** Move request canonicalization into a safe helper that catches `BaseException`, logs the structured autocapture warning without request/body content, and returns either a conservative fallback payload or a sentinel that disables span capture for that SDK call. The wrapper should always call `original(...)` unless the user's SDK call itself raises. Add regression tests where request canonicalization raises and assert:

- the original SDK method is still called,
- its return value or exception is preserved unchanged,
- plumb logs a warning or cleanly skips capture,
- no plumb exception reaches the caller.

## Important Improvements (should fix)

### 2. NFR-Perf-1 benchmark does not include real blob-store writes

**Severity:** Important  
**Files:** `tests/perf/test_autocapture_overhead.py`, `plumb/autocapture/_emit.py`, `plumb/adapters/blobstore_fs.py`  
**Requirement impact:** NFR-Perf-1 is not fully validated for the actual hot path.

The TRS defines captured-span overhead as canonicalization + hashing + one or two `BlobStore.put` calls + `RunHandle.add_span`. The current perf test disables the blob store:

```python
monkeypatch.setattr(_api, "_storage", object())
monkeypatch.setattr(_api, "_blobstore", None)
monkeypatch.setattr(_api, "_storage_writer", _NullWriter())
```

That means `emit_success_span()` only hashes locally and skips the real `FilesystemBlobStore.put()` path. The real implementation performs `os.open`, `os.write`, and `os.fsync` per new blob, so this is likely the dominant cost. The test can pass while real first-time prompt/response blobs exceed the 1 ms p95 budget.

**Recommended fix:** Add a second CI-blocking perf case that uses `FilesystemBlobStore(tmp_path / "blobs")` with unique request/response payloads, or explicitly redefine the NFR to exclude blob persistence. If the real fsync cost is too high, consider changing the design rather than letting the benchmark measure a cheaper path.

### 3. Response serialization failures silently produce the hash of `{}` and mark the span successful

**Severity:** Important  
**File:** `plumb/autocapture/_emit.py`  
**Requirement impact:** Can corrupt `output_hash`/blob data without any warning, undermining metrics that depend on dereferencing response blobs.

`emit_success_span()` catches any response canonicalization failure, substitutes `b"{}"`, computes a normal `output_hash`, writes that blob, and records a success span:

```python
try:
    ...
except BaseException:
    response_payload = b"{}"

output_hash = hashlib.sha256(response_payload).hexdigest()
```

This preserves caller behavior, which is good, but it silently records incorrect content. Downstream metrics will see a valid-looking `output_hash` that points to `{}`, not the actual model output.

**Recommended fix:** Log the structured autocapture warning on serialization failure and either set `output_hash=None` or use an explicit error marker such as `error_type="response_serialization_failed"` while preserving `status='success'`. Add a unit test that forces response canonicalization to raise and asserts no bogus `{}` hash is recorded silently.

### 4. Thread-safety guarantees are weaker than the task contract says

**Severity:** Important  
**Files:** `plumb/autocapture/_state.py`, `plumb/autocapture/_anthropic.py`, `plumb/autocapture/_openai.py`  
**Requirement impact:** The public `install()` path is serialized, but internal registry helpers and provider installers do not enforce their own locking.

The task file says `_register` / `_unregister` mutate `_INSTALLED` under the lock. In implementation, the helpers do not lock, and provider installers bypass `_register` entirely by assigning `_INSTALLED[key] = _Patch(...)`. The concurrent test also wraps `_register()` in `_INSTALL_LOCK`, so it verifies the caller's locking discipline rather than the helper contract.

This is not a current public API bug because `plumb.autocapture.install()` holds `_INSTALL_LOCK`, but the internal contract is easy to misuse and direct provider tests already call `_try_install()` without the public lock.

**Recommended fix:** Either make `_register`, `_unregister`, and provider `_try_install()` enforce locking themselves, or explicitly document that callers must hold `_INSTALL_LOCK` and rename helpers to make that precondition obvious.

## Minor Suggestions (nice to have)

### 5. Spec/docs still disagree on streaming and blob-write timing

**Severity:** Minor  
**Files:** `dev/active/v1-autocapture/v1-autocapture-plan.md`, `docs/2_architecture/SYSTEM_DESIGN.md`, `tests/integration/autocapture/test_streaming_unsupported.py`

The tasks/tests use `output_hash=None` for unsupported streaming marker spans, while the plan's edge-case table says streaming emits an `output_hash` of the request. The SDD data-flow diagram also routes blob writes from run close, but implementation writes request/response blobs during `_emit` on the SDK-call path.

**Recommended fix:** Update the plan edge-case row and SDD diagram/text so future contributors do not implement the older behavior in the streaming follow-up slice.

### 6. `resp_canon` is passed into OpenAI wrappers but never used

**Severity:** Minor  
**File:** `plumb/autocapture/_openai.py`

`_wrap_sync()` and `_wrap_async()` accept `resp_canon`, but `emit_success_span()` reselects the response canonicalizer from `provider`/`endpoint`. This is harmless, but it makes the wrapper API look more configurable than it is.

**Recommended fix:** Remove the unused parameter or pass it through to emission if provider-specific canonicalization is meant to be selected by the installer.

## Architecture Considerations

The layering is mostly sound. Autocapture depends on the public API layer and blob-store singleton, but `plumb/core/` remains pure and provider-agnostic. The lazy-install design preserves the cold-import budget and avoids importing provider SDKs at `import plumb` time.

The main architectural tension is that the hot path currently writes two durable blobs per successful LLM call, including `fsync`. That may be the right product trade-off because hashes and blobs power downstream metrics, but then the performance budget and SDD should acknowledge it directly. If 1 ms p95 is a hard gate, this design needs measured proof with the actual filesystem path.

## Next Steps

1. Fix the wrapper safety boundary so request canonicalization cannot prevent or alter user SDK calls.
2. Make response serialization failures visible and avoid valid-looking hashes for bogus `{}` output.
3. Update the perf benchmark to include real `FilesystemBlobStore.put()` or revise the NFR explicitly.
4. Align `_state.py` locking behavior with the documented contract.
5. Clean up the small doc/spec drift before archiving the slice.

Please review the findings and approve which changes to implement before I proceed with any fixes.

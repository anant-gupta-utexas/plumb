# Code Review — `v1-core-and-api`

**Reviewer:** Code Reviewer (Expert Persona)
**Date:** 2026-04-25
**Scope:** `plumb/core/`, `plumb/api.py`, `plumb/config.py`, `plumb/__init__.py` + all associated tests
**Test result:** 174 passed, 0 failed | Overall coverage: **98%**

---

## Executive Summary

The implementation is in excellent shape. All 174 tests pass, 98% coverage is well above the TRS ≥90% gate, and all stated AC/FR/NFR references are correctly mapped to tests. The code is clean, idiomatic Python 3.13, and the ports-and-adapters boundary is properly enforced.

Two issues warrant attention before follow-up TRSes consume this API: one **important** correctness gap in the `__exit__` exception-swallowing logic, and one **important** security gap (`_require_hex32`/`_require_hex64` expose raw user input in error messages violating §9.2). Everything else is minor.

---

## Critical Issues

*None.*

---

## Important Improvements

### 1. `__exit__` catches `PlumbError` only — any non-`PlumbError` exception from `builder.freeze()` or the writer is silently re-raised into the caller, violating NFR-Rel-1

**File:** [`plumb/api.py:412-428`](../../plumb/api.py)

```python
try:
    run_obj = builder.freeze()
    ...
    _storage_writer.write_run(run_obj, spans)
    ...
except PlumbError as plumb_err:
    logger.warning(...)
```

`builder.freeze()` calls `Run(...)` which can raise plumb's own `ValidationError` (a `PlumbError` subclass) — that is caught correctly. However, the `_storage_writer` is a Protocol with no exception contract: a misbehaving adapter could raise `OSError`, `sqlite3.OperationalError`, or any arbitrary exception. Those would escape `__exit__` and raise into the caller, breaking NFR-Rel-1.

The TRS §7 error table explicitly states: *"StorageWriter raises during close → Catch, log WARNING, swallow; user code's return/raise unaffected."* The current catch is too narrow.

**Fix:** broaden the catch to `Exception` (or at minimum `Exception` for non-`PlumbError` paths):

```python
except Exception as err:   # NFR-Rel-1: never let plumb-internal failure reach caller
    logger.warning(
        "plumb storage failure",
        extra={
            "plumb_internal_error": True,
            "run_id": builder.run_id,
            "error_class": type(err).__name__,
        },
    )
```

**Why it matters:** The existing test `test_storage_error_does_not_raise_into_caller` only injects a `StorageError`, so the gap is invisible in the current suite. An adapter that wraps a real database will throw `sqlite3.OperationalError` directly.

---

### 2. `_require_hex32` / `_require_hex64` embed raw user input in `ValidationError` messages — violates §9.2 (no log injection)

**File:** [`plumb/core/entities.py:66-71`](../../plumb/core/entities.py)

```python
def _require_hex32(value: str, field: str) -> None:
    if not _HEX32.match(value):
        raise ValidationError(
            f"{field} must be a 32-char lowercase hex string, got: {value!r}"
        )
```

The TRS §9.2 states: *"PlumbError subclasses MUST NOT include user content in exception messages."* and cites the specific threat of `task_id` or other user-supplied fields containing `\n`, `\r`, `\x1b`. The `value!r` repr does escape most control characters but `\t` and multi-line strings still pass through. More importantly, the test mandated by §9.2 is absent from the test suite.

**Fix options (choose one):**
- Strip the raw value entirely: `f"{field} must be a 32-char lowercase hex string"` — simplest, fully compliant.
- Keep a safe truncated hint: `f"{field} must be 32-char lowercase hex (got {len(value)}-char string)"` — useful without leaking content.

Either way, add the missing test from §9.2:
```python
def test_no_user_content_in_validation_error_message():
    with pytest.raises(ValidationError) as exc_info:
        Run(run_id="foo\x1bbar", ...)
    assert "\x1b" not in str(exc_info.value)
    assert "\n" not in str(exc_info.value)
```

---

## Minor Suggestions

### 3. `_DefaultIdGenerator` re-imports `uuid` on every call

**File:** [`plumb/api.py:41-60`](../../plumb/api.py)

Each of the four `new_*_id` methods does `import uuid` inline. This was presumably done to keep the cold-import budget clean, but `uuid` is a stdlib module cached in `sys.modules` after the first import — subsequent `import uuid` calls are a dict lookup (~50 ns), not a real import. The comment value is low and the pattern adds visual noise without meaningful benefit.

**Suggestion:** Move `import uuid` to the top of the file alongside the other stdlib imports. It won't affect cold-import time (uuid is pure stdlib with no heavy dependencies).

---

### 4. `_RunFactory.__slots__` contains a typo: `_dedupd` should be `_deduped`

**File:** [`plumb/api.py:316`](../../plumb/api.py)

```python
"_dedupd",   # ← typo
```

The attribute is used consistently as `_dedupd` throughout the class, so it doesn't break anything. But it's a misleading name that will confuse readers of the dedup logic.

---

### 5. `add_span` returns `""` (empty string) on no-op after abort — inconsistent with documented return type

**File:** [`plumb/api.py:217-218`](../../plumb/api.py)

```python
if self._builder.aborted:
    return ""
```

The TRS §3.6.2 documents `add_span` as returning `span_id: str`. Returning `""` is technically a `str`, but an empty string is not a valid 32-hex span ID and will silently fail if a caller stores and later references it (e.g. passes it as `parent_span_id` to another `add_span`). The same applies to `add_score`.

**Option A:** Return a sentinel constant (e.g. `NOOP_ID = ""`) with a module-level docstring explaining the contract.
**Option B:** Return `None` and change the return type to `str | None` — callers are forced to check, which is safer.

The test correctly asserts `result == ""` but doesn't test the downstream case of using the returned ID as a `parent_span_id`.

---

### 6. `_NullWriter` in `test_span_overhead.py` is missing `write_example`

**File:** [`tests/perf/test_span_overhead.py:19-27`](../../tests/perf/test_span_overhead.py)

```python
class _NullWriter:
    def write_run(...): pass
    def write_score(...): pass
    # write_example is missing
```

This doesn't currently break anything because `write_example` is not called on the hot path, but the class doesn't satisfy the `StorageWriter` Protocol. If `mypy --strict` is run against the test files it will fail here. Consistent with the project's own Protocol definition.

---

### 7. `test_base_exception_propagates` doesn't verify the run row is still written

**File:** [`tests/unit/api/test_edge_cases.py:28-37`](../../tests/unit/api/test_edge_cases.py)

The test confirms `KeyboardInterrupt` propagates, but doesn't assert that the run was persisted with `status='failure'`. For `BaseException` subclasses (like `KeyboardInterrupt`), `__exit__` currently receives `exc_type=KeyboardInterrupt` and would write a failure row — but this is unverified. Worth adding an assertion to protect against future regressions where `BaseException` handling might be split out.

---

### 8. `perf/test_span_overhead.py` directly mutates module-level singletons instead of using `monkeypatch`

**File:** [`tests/perf/test_span_overhead.py:35-49`](../../tests/perf/test_span_overhead.py)

```python
_api._storage_writer = _NullWriter()
...
finally:
    _api._storage_writer = original_writer
```

Using `try/finally` for teardown is correct but fragile — if the test is interrupted between assignment and `finally`, state leaks. The `configured_api` fixture in `conftest.py` exists precisely to handle this via `monkeypatch`. The perf test also runs with the default `_DefaultClock` (real `datetime.now()`) rather than the fake, which means the span objects contain real timestamps — minor overhead that doesn't affect the benchmark but is inconsistent.

---

## Architecture Considerations

**Dependency rule is clean.** `plumb/core/` has zero imports from `plumb/api.py` or `plumb/adapters/`. The ports-and-adapters boundary holds.

**`__init__.py` public surface matches TRS §4.1 exactly.** All 20 exported names are present and in the right categories.

**Config is not wired to anything in this slice.** `Settings` is defined and tested in isolation but no code in `plumb/api.py` reads `get_settings()`. This is correct and expected per TRS §1.2 — the storage adapter slice will wire it. Just confirm this remains intentional.

**`_RunFactory` is single-use by design** but this is nowhere documented or enforced. A user who calls `__enter__` twice on the same factory would get two runs with the same `_frame_id`, causing dedup to misfire. Since `run(...)` creates a new factory each time, this isn't a real-world risk, but the invariant is worth a brief comment.

---

## Next Steps

Issues are prioritized as follows:

| # | Severity | Action |
|---|---|---|
| 1 | **Important** | Broaden `except PlumbError` to `except Exception` in `__exit__` and `__aexit__` |
| 2 | **Important** | Remove raw user content from `ValidationError` messages + add §9.2 test |
| 3 | Minor | Move `import uuid` to module top |
| 4 | Minor | Rename `_dedupd` → `_deduped` throughout |
| 5 | Minor | Document/decide `add_span`/`add_score` no-op return value contract |
| 6 | Minor | Add `write_example` to `_NullWriter` in perf test |
| 7 | Minor | Assert run persistence in `test_base_exception_propagates` |
| 8 | Minor | Use `monkeypatch` fixture in perf test instead of manual teardown |

**Please review the findings and approve which changes to implement before I proceed with any fixes.**

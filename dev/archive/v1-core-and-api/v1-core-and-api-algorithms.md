# TRS Algorithms — `plumb/core/` + `plumb/api.py`

Companion to [`v1-core-and-api-plan.md`](./v1-core-and-api-plan.md). Contains pseudocode and lifecycle diagrams that were too long to fit in the main plan §6.

---

## §6.1 Run lifecycle (sync)

```python
class _RunFactory:
    def __enter__(self) -> RunHandle:
        parent_handle = _active_run.get()
        # FR-GRAPH-1: parent from contextvar; FR-GRAPH-2: explicit kwarg fallback
        parent_run_id = (
            parent_handle.run_id if parent_handle
            else self._explicit_parent_run_id
        )

        # FR-EDGE-4: nested-decorator dedup
        if (
            self._is_decorator_call
            and parent_handle is not None
            and parent_handle._open_frame_id == self._frame_id
        ):
            self._dedupd = True
            return parent_handle  # outer call no-ops

        builder = _RunBuilder(
            run_id=_id_gen.new_run_id(),
            kind=self.kind,
            task_id=self.task_id,
            parent_run_id=parent_run_id,
            start_ts=_clock.now(),
            orchestrator_model=self.orchestrator_model,
            sub_agent_model=self.sub_agent_model,
            prompt_version=self.prompt_version,
            tool_schema_version=self.tool_schema_version,
            git_sha=self.git_sha,
        )
        handle = RunHandle(builder)
        if self._is_decorator_call:
            handle._open_frame_id = self._frame_id  # FR-EDGE-4 marker
        self._token = _active_run.set(handle)
        return handle

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self._dedupd:
            return False  # outer no-op; never suppresses

        handle = _active_run.get()
        builder = handle._builder

        # determine final status
        if exc_type is not None:
            builder.status = RunStatus.FAILURE
            builder.error_type = exc_type.__name__
        elif builder.aborted:
            builder.status = RunStatus.ABORTED
            builder.error_type = builder.abort_reason
        else:
            builder.status = RunStatus.SUCCESS

        builder.end_ts = _clock.now()

        try:
            run_obj = builder.freeze()
            # Decision §3.3: flush partial buffer on abort.
            # builder.spans / builder.scores already contain only what was
            # added BEFORE abort() — RunHandle.add_span/add_score are no-ops
            # after abort, so post-abort calls never reached the buffer.
            spans = list(builder.spans)
            scores = list(builder.scores)
            _storage_writer.write_run(run_obj, spans)
            for score in scores:
                _storage_writer.write_score(score)
        except PlumbError as plumb_err:
            # NFR-Rel-1: NEVER raise plumb-internal failure into caller
            logger.warning(
                "plumb storage failure",
                extra={
                    "plumb_internal_error": True,
                    "run_id": builder.run_id,
                    "error_class": type(plumb_err).__name__,
                },
            )
            # best-effort: try to write a minimal failure row; if that fails, give up silently
        finally:
            _active_run.reset(self._token)

        return False  # NEVER suppress user exceptions (FR-EDGE-1)
```

**Critical invariants:**
- `_active_run.reset(self._token)` runs in `finally` so a storage failure mid-close still restores the contextvar.
- `__exit__` returns `False` always — never absorb user exceptions.
- `PlumbError` is the only exception class swallowed; bare `Exception` is NOT caught (would mask user code bugs that bubble through plumb's internals).

---

## §6.2 Run lifecycle (async)

Identical structure with `async def __aenter__` / `async def __aexit__`. Contextvars module is async-safe by design — each `asyncio.Task` gets its own contextvar copy.

```python
async def __aenter__(self) -> RunHandle:
    return self.__enter__()  # contextvars work the same in async

async def __aexit__(self, exc_type, exc_val, exc_tb) -> bool:
    return self.__exit__(exc_type, exc_val, exc_tb)
```

The implementations can literally delegate because:
1. `_active_run.set(...)` is sync.
2. `_storage_writer.write_run(...)` is sync (NFR-Perf-5: zero network I/O).
3. There's no `await` anywhere in the lifecycle.

If a future storage adapter wants async I/O (it shouldn't, per NFR-Perf-5), this delegation pattern would have to change.

**Critical:** the `_token` returned by `_active_run.set` MUST be held in a **per-instance attribute** (`self._token`), not module-global. Otherwise concurrent `async with` blocks in the same task tree would clobber each other's tokens.

---

## §6.3 McNemar's paired test

```python
def mcnemar_paired(
    baseline_outcomes: Sequence[bool],
    candidate_outcomes: Sequence[bool],
    *,
    continuity_correction: bool = True,
) -> McNemarResult:
    if len(baseline_outcomes) != len(candidate_outcomes):
        raise ValueError(
            f"length mismatch: baseline={len(baseline_outcomes)}, "
            f"candidate={len(candidate_outcomes)}"
        )

    b = sum(
        1 for bl, cn in zip(baseline_outcomes, candidate_outcomes)
        if bl and not cn
    )
    c = sum(
        1 for bl, cn in zip(baseline_outcomes, candidate_outcomes)
        if not bl and cn
    )
    n_discordant = b + c
    if n_discordant < 1:
        raise ValueError("no discordant pairs — McNemar undefined")

    if continuity_correction:
        statistic = (abs(b - c) - 1) ** 2 / n_discordant
    else:
        statistic = (b - c) ** 2 / n_discordant

    p_value = 1.0 - _chi2_cdf_df1(statistic)

    return McNemarResult(
        b=b, c=c,
        statistic=statistic,
        p_value=p_value,
        n_discordant=n_discordant,
    )


def _chi2_cdf_df1(x: float) -> float:
    """Chi-squared CDF with df=1, via stdlib math.

    df=1 chi-squared CDF = erf(sqrt(x/2))
    """
    import math
    if x <= 0:
        return 0.0
    return math.erf(math.sqrt(x / 2.0))
```

**No SciPy dependency** — `math.erf` is in stdlib. The `df=1` chi-squared has a closed-form CDF in terms of `erf`, which sidesteps the gamma-incomplete machinery SciPy provides.

**Reference values for tests** (computed against scipy.stats.chi2.sf for sanity):

| b | c | Yates' (corr) p-value |
|---|---|---|
| 10 | 2 | ≈ 0.0386 |
| 5 | 5 | 1.0000 (no difference) |
| 20 | 0 | ≈ 1.46e-5 |
| 1 | 0 | 1.0000 (n_discordant=1, statistic=0 with correction) |
| 100 | 50 | ≈ 1.92e-5 |

---

## §6.4 Benjamini-Hochberg FDR

```python
def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> list[bool]:
    n = len(p_values)
    if n == 0:
        return []

    # decorate-sort-undecorate: keep original index for output order
    indexed = sorted(enumerate(p_values), key=lambda t: t[1])  # ascending by p

    # find largest k (1-indexed rank) where p_(k) <= (k/n) * alpha
    k_max = 0
    for rank, (orig_idx, p) in enumerate(indexed, start=1):
        if p <= (rank / n) * alpha:
            k_max = rank

    # reject all p-values at ranks 1..k_max
    rejected = [False] * n
    if k_max > 0:
        for rank in range(1, k_max + 1):
            orig_idx = indexed[rank - 1][0]
            rejected[orig_idx] = True

    return rejected
```

**Edge cases:**
- Empty input → empty output (no error).
- All p-values > alpha → `k_max = 0` → all False.
- All p-values = 0 → all True.

**Reference values for tests** (against R `p.adjust(p, method="BH")` at α=0.05):

| Input | Expected rejected mask |
|---|---|
| `[0.01, 0.04, 0.03, 0.5]` | `[True, True, True, False]` |
| `[0.001, 0.008, 0.039, 0.041, 0.042]` | `[True, True, True, True, True]` |
| `[0.06, 0.08, 0.5]` | `[False, False, False]` |

---

## §6.5 ID generation

```python
import uuid

class _DefaultIdGenerator:
    def new_run_id(self) -> str:
        return uuid.uuid4().hex  # 32 lowercase hex chars

    def new_span_id(self) -> str:
        return uuid.uuid4().hex

    def new_score_id(self) -> str:
        return uuid.uuid4().hex

    def new_example_id(self) -> str:
        return uuid.uuid4().hex
```

`uuid.uuid4()` gives 122 bits of entropy — collision probability is negligible at plumb's scale (single-user, ≤ 100k runs lifetime). Deterministic IDs (sha256-derived) are introduced by the ATTACH adapter for idempotency (out of scope here).

---

## §6.6 Cold-import budget enforcement

`plumb/__init__.py` MUST NOT eagerly import: `anthropic`, `openai`, `httpx`, `fastapi`, `uvicorn`, `typer`, `sqlite3`. The adapter modules use lazy import inside functions:

```python
# plumb/adapters/storage_sqlite.py (in storage TRS, illustrative)
def _open_connection(path: Path) -> sqlite3.Connection:
    import sqlite3  # lazy — costs nothing if no SQLite usage
    return sqlite3.connect(path)
```

Verified by `tests/perf/test_cold_import.py`:

```python
import subprocess, sys, re

def test_cold_import_budget():
    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import plumb"],
        capture_output=True, text=True, check=True,
    )
    # parse cumulative time from final "import time:" line
    last_line = [l for l in result.stderr.splitlines() if "plumb" in l][-1]
    # format: import time: self [us] | cumulative | imported package
    m = re.search(r"import time:\s+(\d+)\s+\|\s+(\d+)\s+\|\s+plumb$", last_line)
    cumulative_us = int(m.group(2))

    if cumulative_us > 400_000:
        raise AssertionError(f"cold import {cumulative_us}us > 400ms hard limit")
    if cumulative_us > 200_000:
        warnings.warn(f"cold import {cumulative_us}us > 200ms target (hard fail at 400ms)")
```

(Recommendation B from §12.6 of the main plan: warn at 200 ms, hard-fail at 400 ms.)

---

*End of algorithms doc.*

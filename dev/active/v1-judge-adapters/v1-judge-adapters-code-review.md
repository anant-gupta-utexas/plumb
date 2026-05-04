# Code Review — v1 Judge Adapters

**Reviewer persona:** Code Reviewer  
**Review date:** 2026-05-04  
**Scope reviewed:** `dev/active/v1-judge-adapters` plan/context/tasks, judge adapter implementation, factory wiring, CLI judge-run path, and related unit/CLI tests.

## Findings

### P1 — `plumb judge run` judges captured inputs instead of model outputs

`plumb._cli_judge._load_run_content()` selects `Span.input_hash` for LLM spans and reads that blob as the candidate content:

```python
llm_spans = [s for s in spans if s.kind == SpanKind.LLM and s.input_hash]
if llm_spans:
    primary = max(llm_spans, key=lambda s: s.tokens_in or 0)
    target_hash = primary.input_hash
```

Autocapture writes the provider request to `input_hash` and the provider response to `output_hash` (`plumb/autocapture/_emit.py`). That means real captured runs will often send the prompt/request JSON to the judge instead of the model response being evaluated. This breaks the main user-facing behavior of the slice: judge scores can look valid while scoring the wrong artifact.

**Recommendation:** Prefer successful LLM spans with `output_hash`, read that blob, and only fall back deliberately when no output exists. Add an integration test that writes distinct input/output blobs and asserts the fake judge receives the output content.

### P1 — Fail-open score rows block re-judging after the transient issue is fixed

Fail-open adapter results append `:error` to `scorer_version`, and the context says this is so error rows can be filtered out and re-run later. The storage query currently excludes a run if *any* score exists for `(run_id, metric_name)`:

```sql
AND NOT EXISTS (
    SELECT 1 FROM scores s
    WHERE s.run_id = r.run_id AND s.metric_name = ?
)
```

After a provider outage, bad key, parse failure, or unexpected adapter exception, `plumb judge run` writes `value_label='error'`; subsequent runs skip that row forever unless the user manually deletes scores. The CLI exception path also writes `scorer_version="error"` rather than the provider/model/prompt `:error` shape, making future filtering less consistent.

**Recommendation:** Define error-score retry semantics explicitly. If fail-open means "retry after fix," change the unscored query to ignore prior error rows (for example no existing non-error score for the metric) and add CLI coverage for rerun-after-error.

### P2 — `get_judge_adapter(settings, ...)` does not consistently use the supplied settings

The factory accepts a `Settings` object, but prompt loading goes through `load_prompt(metric_name)` with no directory override. `load_prompt()` then calls global `get_settings()` internally. A caller can pass `Settings(data_dir=...)` and still have the prompt resolved from the cached global settings instead of the object passed to the factory.

The same ordering also causes misleading configuration failures: unsupported providers or missing credentials may be masked by `FileNotFoundError` because the prompt is loaded before provider-specific validation. The unit tests avoid this by mocking `load_prompt`, so they do not exercise the real factory contract.

**Recommendation:** In `get_judge_adapter`, validate provider and credentials before loading the prompt, and pass `ensure_data_dir(settings) / "judge_prompts"` into `load_prompt(..., prompts_dir=...)`. Add a non-mocked test that creates a prompt under `settings.data_dir`.

### P2 — Retry behavior misses the stated jitter / tenacity requirement

The plan and requirement summary call for `tenacity` with exponential backoff plus jitter. The implementation added the dependency but uses a custom deterministic sleep sequence:

```python
wait = min(_WAIT_MAX, float(2**attempt))
time.sleep(wait)
```

The current tests only assert call count, monotonicity, and bounds, so they pass while not verifying jitter or use of the chosen retry library. This is lower risk than the CLI content issues, but it is an acceptance-criteria mismatch and makes herd behavior under provider rate limits more likely.

**Recommendation:** Either switch to the planned `tenacity.wait_exponential_jitter(initial=1, max=8)` wrapper or update the TRS/tasks to state that deterministic backoff is intentional. Strengthen tests to check the selected contract.

## Test Gaps

- No end-to-end CLI test covers real blobstore content selection with both `input_hash` and `output_hash` present.
- No test covers rerunning `plumb judge run` after an error score already exists.
- Factory tests mock `load_prompt`, so they miss real `settings.data_dir` resolution and the validation-order behavior.
- New adapter test files exceed the task's stated 400-line file target (`test_judge_anthropic.py`, `test_judge_openai_compat.py`), though this is a maintainability issue rather than a behavioral blocker.

## Summary

The adapter implementations largely match the protocol shape, fail-open behavior, request parameters, lazy imports, and basic redaction expectations. The main risks are in the CLI/factory integration: real runs can be judged against the wrong blob, error rows are not actually retryable, and the factory contract is weaker than the signature suggests.

I recommend addressing the two P1 findings before treating the slice as merge-ready.

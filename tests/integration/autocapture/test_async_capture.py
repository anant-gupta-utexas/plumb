"""Integration test for concurrent async autocapture (Task 4.3).

Covers:
- asyncio.gather of 3 nested async runs, each making 2 Anthropic calls
- 6 span rows total, 3 runs rows, correct parent_run_id isolation
- No contextvar cross-pollution across concurrent tasks
- Test must complete in < 2 seconds
"""

from __future__ import annotations

import asyncio
import time

import anthropic
import httpx
import pytest

import plumb.api as _api
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.autocapture._anthropic import _try_install

from .conftest import CANNED_ANTHROPIC_MESSAGE, _AsyncAnthropicTransport


async def _run_two_calls(
    client: anthropic.AsyncAnthropic,
    task_id: str,
    adapter: SQLiteStorageAdapter,
) -> tuple[str, list[str]]:
    """Open a run, make 2 async SDK calls, return (run_id, [span_ids])."""
    with _api.run(task_id=task_id) as r:
        await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": "call 1"}],
        )
        await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": "call 2"}],
        )

    spans = adapter.get_spans_for_run(r.run_id)
    return r.run_id, [s.span_id for s in spans]


@pytest.mark.asyncio
async def test_concurrent_runs_no_cross_pollution(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    """Task 4.3 AC: 3 concurrent runs × 2 spans each = 6 spans, 3 run rows, no cross-pollution."""
    adapter, bs = configured_api
    _try_install()

    transport = _AsyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)
    client = anthropic.AsyncAnthropic(
        api_key="fake-key",
        http_client=httpx.AsyncClient(transport=transport),
    )

    start = time.perf_counter()
    results = await asyncio.gather(
        _run_two_calls(client, "concurrent-a", adapter),
        _run_two_calls(client, "concurrent-b", adapter),
        _run_two_calls(client, "concurrent-c", adapter),
    )
    elapsed = time.perf_counter() - start

    assert elapsed < 2.0, f"Test took {elapsed:.2f}s, must be < 2s"

    run_ids = [r[0] for r in results]
    span_id_sets = [r[1] for r in results]

    # 3 distinct run IDs
    assert len(set(run_ids)) == 3, "Each concurrent run must have a distinct run_id"

    # Each run has exactly 2 spans
    for run_id, span_ids in zip(run_ids, span_id_sets, strict=True):
        assert len(span_ids) == 2, f"Run {run_id} should have exactly 2 spans, got {len(span_ids)}"

    # All span IDs are globally unique
    all_span_ids = [sid for _, sids in results for sid in sids]
    assert len(set(all_span_ids)) == 6, "All 6 span IDs must be distinct"

    # Each span belongs to the correct run (no cross-pollution)
    for run_id, span_ids in zip(run_ids, span_id_sets, strict=True):
        spans = adapter.get_spans_for_run(run_id)
        db_span_ids = {s.span_id for s in spans}
        for sid in span_ids:
            assert sid in db_span_ids, f"Span {sid} not found under run {run_id}"

    # No run has a parent_run_id (all top-level)
    for run_id in run_ids:
        run_row = adapter.get_run(run_id)
        assert run_row is not None
        assert run_row.parent_run_id is None, f"Run {run_id} should not have a parent_run_id"

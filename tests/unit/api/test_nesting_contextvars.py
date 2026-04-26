"""Concurrent-task contextvar isolation test (Task 6.3)."""

from __future__ import annotations

import asyncio

from plumb.api import run
from plumb.core.entities import RunStatus


async def _run_nested_pair(task_label: str, storage: object) -> tuple[str, str]:
    """Open 2 nested runs; return (outer_id, inner_parent_id)."""
    outer_id: str = ""
    inner_parent_id: str = ""

    async with run(task_id=f"{task_label}-outer") as outer:
        outer_id = outer.run_id
        async with run(task_id=f"{task_label}-inner") as inner:
            inner_parent_id = inner.parent_run_id or ""

    return outer_id, inner_parent_id


async def test_concurrent_async_tasks(configured_api: object) -> None:
    """Three concurrent tasks; each opens 2 nested runs (6 total).

    Verifies:
    - All 6 runs persisted.
    - Per-task parent_run_id chains are correct.
    - No cross-task pollution (inner parent must equal its own outer, not another task's).
    """
    from tests.conftest import FakeStorageWriter

    storage = configured_api  # type: ignore[assignment]
    assert isinstance(storage, FakeStorageWriter)

    results = await asyncio.gather(
        _run_nested_pair("task-a", storage),
        _run_nested_pair("task-b", storage),
        _run_nested_pair("task-c", storage),
    )

    assert len(storage.runs) == 6

    all_outer_ids = {outer_id for outer_id, _ in results}
    assert len(all_outer_ids) == 3, "Each task must produce a distinct outer run_id"

    for outer_id, inner_parent_id in results:
        assert inner_parent_id == outer_id, (
            f"inner's parent ({inner_parent_id!r}) must equal its own outer ({outer_id!r})"
        )

    all_statuses = {run_obj.status for run_obj, _ in storage.runs}
    assert all_statuses == {RunStatus.SUCCESS}

"""Integration tests for RunHandle.add_example against real SQLite (Task 7).

Covers AC-ADDEX-1 (row shape) and FR-ADDEX-4 (structural parity with the
existing `plumb example promote` CLI write path).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import plumb.api as _api
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.core.entities import Example, ExampleSource
from plumb.core.errors import ValidationError


class _FakeClock:
    def __init__(self) -> None:
        self._step = 0

    def now(self) -> datetime:
        from datetime import timedelta

        ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=self._step)
        self._step += 1
        return ts


@pytest.fixture()
def real_adapter(tmp_path: Path) -> SQLiteStorageAdapter:
    adapter = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_FakeClock())
    yield adapter
    adapter.close()


@pytest.fixture()
def configured_real_api(
    monkeypatch: pytest.MonkeyPatch,
    real_adapter: SQLiteStorageAdapter,
) -> SQLiteStorageAdapter:
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    yield real_adapter


def test_add_example_writes_row_with_expected_fields(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    with _api.run(task_id="my-task") as r:
        example_id = r.add_example(
            "a" * 64, source="production_promotion", expected_output_hash="b" * 64, rubric="be good"
        )

    examples = configured_real_api.list_examples()
    assert len(examples) == 1
    ex = examples[0]
    assert ex.example_id == example_id
    assert ex.task_id == "my-task"
    assert ex.active is True
    assert ex.source == ExampleSource.PRODUCTION_PROMOTION
    assert ex.expected_output_hash == "b" * 64
    assert ex.rubric == "be good"


def test_add_example_malformed_hash_raises_before_write(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    with _api.run(task_id="t") as r, pytest.raises(ValidationError):
        r.add_example("not-hex", source="synthetic")
    assert configured_real_api.list_examples() == []


def test_add_example_noop_after_abort(configured_real_api: SQLiteStorageAdapter) -> None:
    with _api.run(task_id="t") as r:
        r.abort("stop")
        example_id = r.add_example("a" * 64, source="synthetic")
    assert example_id == ""
    assert configured_real_api.list_examples() == []


def test_add_example_parity_with_example_promote_cli_path(
    configured_real_api: SQLiteStorageAdapter,
) -> None:
    """FR-ADDEX-4: add_example-written rows are structurally identical to
    plumb example promote-written rows for equivalent inputs — same columns
    populated the same way."""
    # add_example path
    with _api.run(task_id="task-a") as r:
        add_example_id = r.add_example(
            "a" * 64, source="production_promotion", expected_output_hash=None, rubric=None
        )
    origin_run_id = r.run_id

    # example promote (CLI) path — same shape, direct adapter call mirroring
    # plumb/cli.py::example_promote's Example construction.
    import uuid

    cli_example_id = uuid.uuid4().hex
    cli_example = Example(
        example_id=cli_example_id,
        task_id="task-a",
        inputs_hash="a" * 64,
        source=ExampleSource.PRODUCTION_PROMOTION,
        created_at=datetime.now(UTC),
        active=True,
        rubric=None,
        origin_run_id=origin_run_id,
    )
    configured_real_api.write_example(cli_example)

    examples = {ex.example_id: ex for ex in configured_real_api.list_examples()}
    add_ex = examples[add_example_id]
    cli_ex = examples[cli_example_id]

    assert add_ex.task_id == cli_ex.task_id
    assert add_ex.inputs_hash == cli_ex.inputs_hash
    assert add_ex.source == cli_ex.source
    assert add_ex.origin_run_id == cli_ex.origin_run_id
    assert add_ex.active == cli_ex.active
    assert add_ex.expected_output_hash == cli_ex.expected_output_hash
    assert add_ex.rubric == cli_ex.rubric

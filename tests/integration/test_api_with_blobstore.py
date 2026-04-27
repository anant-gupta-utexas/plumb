"""Integration tests: @run + FilesystemBlobStore round-trip (Task 6.3).

Covers:
- r.add_span(..., input_hash=h1, output_hash=h2) where h1/h2 come from
  FilesystemBlobStore.put() — hashes round-trip through the DB and are
  retrievable from the blob store.
- Both blobs readable after the run is committed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

import plumb.api as _api
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter

# ---------------------------------------------------------------------------
# Fixture: real adapter + blob store bound to tmp_path
# ---------------------------------------------------------------------------


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
def real_blobstore(tmp_path: Path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.fixture()
def configured_real_api(
    monkeypatch: pytest.MonkeyPatch,
    real_adapter: SQLiteStorageAdapter,
    real_blobstore: FilesystemBlobStore,
) -> tuple[SQLiteStorageAdapter, FilesystemBlobStore]:
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", real_blobstore)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    return real_adapter, real_blobstore


# ---------------------------------------------------------------------------
# Blob hashes round-trip through spans table
# ---------------------------------------------------------------------------


def test_span_blob_hashes_round_trip(
    configured_real_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    """input_hash and output_hash stored in span row are retrievable from blobstore."""
    adapter, blobstore = configured_real_api

    input_payload = b"the model input"
    output_payload = b"the model output"
    input_hash = blobstore.put(input_payload)
    output_hash = blobstore.put(output_payload)

    with _api.run(task_id="blob_task") as r:
        r.add_span(
            "llm",
            "generate",
            input_hash=input_hash,
            output_hash=output_hash,
        )

    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    span = spans[0]

    assert span.input_hash == input_hash
    assert span.output_hash == output_hash

    assert blobstore.get(span.input_hash) == input_payload
    assert blobstore.get(span.output_hash) == output_payload


def test_multiple_spans_with_blobs(
    configured_real_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    adapter, blobstore = configured_real_api

    payloads = [f"payload_{i}".encode() for i in range(5)]
    hashes = [blobstore.put(p) for p in payloads]

    with _api.run(task_id="multi_blob") as r:
        for i, h in enumerate(hashes):
            r.add_span("tool", f"tool_{i}", input_hash=h)

    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 5

    for span in spans:
        assert span.input_hash in hashes
        stored = blobstore.get(span.input_hash)
        idx = hashes.index(span.input_hash)
        assert stored == payloads[idx]


def test_empty_blob_round_trips(
    configured_real_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    """put(b'') works — empty blob sha256 round-trips through span row."""
    adapter, blobstore = configured_real_api

    empty_hash = blobstore.put(b"")
    assert len(empty_hash) == 64

    with _api.run(task_id="empty_blob") as r:
        r.add_span("llm", "empty_span", input_hash=empty_hash)

    spans = adapter.get_spans_for_run(r.run_id)
    assert spans[0].input_hash == empty_hash
    assert blobstore.get(empty_hash) == b""


def test_blob_store_exists_after_run(
    configured_real_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    """Blobs written before the run are still present after the run commits."""
    adapter, blobstore = configured_real_api

    payload = b"persistent blob"
    h = blobstore.put(payload)

    with _api.run(task_id="persistence_check") as r:
        r.add_span("llm", "span_with_blob", output_hash=h)

    assert blobstore.exists(h)
    assert blobstore.get(h) == payload


def test_run_without_blobs_coexists_with_blobstore(
    configured_real_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    """A run with no blob references works fine even when blobstore is wired."""
    adapter, _blobstore = configured_real_api

    with _api.run(task_id="no_blobs") as r:
        r.add_span("tool", "plain_span")

    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    assert spans[0].input_hash is None
    assert spans[0].output_hash is None

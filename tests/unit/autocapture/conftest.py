"""Shared fakes and fixtures for autocapture unit tests (Task 3.2)."""

from __future__ import annotations

import hashlib
from typing import Any

import pytest


class FakeBlobStore:
    """In-memory BlobStore fake. Satisfies the BlobStore Protocol."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}
        self.put_call_count = 0

    def put(self, content: bytes) -> str:
        digest = hashlib.sha256(content).hexdigest()
        self.blobs[digest] = content
        self.put_call_count += 1
        return digest

    def get(self, sha256_hex: str) -> bytes:
        return self.blobs[sha256_hex]

    def exists(self, sha256_hex: str) -> bool:
        return sha256_hex in self.blobs


class FakeRunHandle:
    """Minimal RunHandle fake that captures add_span calls."""

    def __init__(self) -> None:
        self.captured_spans: list[dict[str, Any]] = []

    def add_span(self, kind: Any, name: str, **kwargs: Any) -> str:
        self.captured_spans.append({"kind": kind, "name": name, **kwargs})
        return "0" * 32


@pytest.fixture()
def fake_blobstore() -> FakeBlobStore:
    return FakeBlobStore()


@pytest.fixture()
def fake_run_handle() -> FakeRunHandle:
    return FakeRunHandle()


@pytest.fixture()
def installed_emit_fakes(
    monkeypatch: pytest.MonkeyPatch,
    fake_blobstore: FakeBlobStore,
    fake_run_handle: FakeRunHandle,
) -> tuple[FakeBlobStore, FakeRunHandle]:
    """Patch plumb.api._blobstore and _active_run to use fakes."""
    import plumb.api as api

    monkeypatch.setattr(api, "_blobstore", fake_blobstore)

    token = api._active_run.set(fake_run_handle)  # type: ignore[arg-type]
    yield fake_blobstore, fake_run_handle
    api._active_run.reset(token)

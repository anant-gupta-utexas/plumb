"""Shared fixtures for autocapture integration tests."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Generator

import httpx
import pytest

import plumb.api as _api
import plumb.autocapture as _autocapture
import plumb.autocapture._state as _state
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter


class _FakeClock:
    def __init__(self) -> None:
        self._step = 0

    def now(self) -> datetime:
        from datetime import timedelta

        ts = datetime(2024, 1, 1, tzinfo=UTC) + timedelta(seconds=self._step)
        self._step += 1
        return ts


class _SyncAnthropicTransport(httpx.BaseTransport):
    """Returns a canned Anthropic Messages response."""

    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = body
        self._status = status

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status, json=self._body)


class _AsyncAnthropicTransport(httpx.AsyncBaseTransport):
    """Returns a canned Anthropic Messages response (async)."""

    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = body
        self._status = status

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(self._status, json=self._body)


CANNED_ANTHROPIC_MESSAGE = {
    "id": "msg_test123",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [{"type": "text", "text": "Hello from stub!"}],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {"input_tokens": 10, "output_tokens": 5},
}

CANNED_ANTHROPIC_RATE_LIMIT = {
    "type": "error",
    "error": {"type": "rate_limit_error", "message": "Rate limited"},
}


@pytest.fixture()
def real_adapter(tmp_path: Path) -> Generator[SQLiteStorageAdapter, None, None]:
    adapter = SQLiteStorageAdapter(tmp_path / "plumb.db", clock=_FakeClock())
    yield adapter
    adapter.close()


@pytest.fixture()
def real_blobstore(tmp_path: Path) -> FilesystemBlobStore:
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.fixture()
def configured_api(
    monkeypatch: pytest.MonkeyPatch,
    real_adapter: SQLiteStorageAdapter,
    real_blobstore: FilesystemBlobStore,
) -> tuple[SQLiteStorageAdapter, FilesystemBlobStore]:
    """Wire plumb.api to use real SQLite + FilesystemBlobStore against tmp_path."""
    monkeypatch.setattr(_api, "_storage", real_adapter)
    monkeypatch.setattr(_api, "_blobstore", real_blobstore)
    monkeypatch.setattr(_api, "_storage_writer", real_adapter)
    return real_adapter, real_blobstore


@pytest.fixture(autouse=True)
def clean_install_registry() -> Generator[None, None, None]:
    """Uninstall all patches before and after each test to prevent wrapper stacking."""
    _autocapture.uninstall()
    yield
    _autocapture.uninstall()

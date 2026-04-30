"""NFR-Perf-5: autocapture performs no network I/O on the hot path."""

from __future__ import annotations

import socket

import httpx
import openai
import pytest

import plumb.api as _api
import plumb.autocapture as _autocapture
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter

from .conftest import CANNED_OPENAI_CHAT_COMPLETION, _SyncOpenAITransport


def test_autocapture_install_and_stubbed_sdk_call_do_not_open_network_sockets(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NFR-Perf-5: plumb must not call socket.connect while capturing an SDK call."""
    adapter, _blobstore = configured_api

    def blocked_connect(self: socket.socket, address: object) -> None:
        raise RuntimeError("plumb opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", blocked_connect)

    _autocapture.install()
    client = openai.OpenAI(
        api_key="fake-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=_SyncOpenAITransport(CANNED_OPENAI_CHAT_COMPLETION)),
    )

    with _api.run(task_id="no-network-io") as r:
        result = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
        )

    spans = adapter.get_spans_for_run(r.run_id)
    assert result.model == "gpt-4o"
    assert len(spans) == 1
    assert spans[0].name == "openai/chat/gpt-4o"

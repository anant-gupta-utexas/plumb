"""NFR-Sec-2: autocapture must not persist or log provider secrets."""

from __future__ import annotations

import logging
import re

import anthropic
import httpx
import openai
import pytest

import plumb.api as _api
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.autocapture._anthropic import _try_install as _try_install_anthropic
from plumb.autocapture._openai import _try_install as _try_install_openai
from plumb.core.entities import Span

from .conftest import (
    CANNED_ANTHROPIC_MESSAGE,
    CANNED_OPENAI_CHAT_COMPLETION,
    _SyncAnthropicTransport,
    _SyncOpenAITransport,
)

SECRET = "sk-test-real-12345678"
SECRET_BYTES = SECRET.encode("utf-8")
SECRET_RE = re.compile(r"sk-[a-zA-Z0-9-]{8,}")


def _anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key="fake-key",
        http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
    )


def _openai_client() -> openai.OpenAI:
    return openai.OpenAI(
        api_key="fake-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=_SyncOpenAITransport(CANNED_OPENAI_CHAT_COMPLETION)),
    )


def _read_span_blobs(blobstore: FilesystemBlobStore, span: Span) -> list[bytes]:
    hashes = [span.input_hash, span.output_hash]
    return [blobstore.get(h) for h in hashes if h is not None]


def _assert_secret_absent_from_blob_bytes(blobs: list[bytes]) -> None:
    assert blobs, "expected autocapture to persist at least one blob"
    assert any(b"<redacted>" in blob for blob in blobs)
    for blob in blobs:
        assert SECRET_BYTES not in blob
        assert SECRET_RE.search(blob.decode("utf-8", errors="replace")) is None


def _assert_secret_absent_from_logs(caplog: pytest.LogCaptureFixture) -> None:
    assert SECRET not in caplog.text
    assert SECRET_RE.search(caplog.text) is None


def test_provider_request_blobs_redact_secret_headers_and_metadata(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NFR-Sec-2: provider request blobs contain redaction markers, never secrets."""
    adapter, blobstore = configured_api
    caplog.set_level(logging.WARNING, logger="plumb.autocapture")
    _try_install_anthropic()
    _try_install_openai()

    with _api.run(task_id="secret-redaction") as r:
        _anthropic_client().messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
            metadata={"user_id": "safe-user", "api_key": SECRET},
            extra_headers={"Authorization": f"Bearer {SECRET}"},
        )
        _openai_client().chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            extra_body={"metadata": {"api_key": SECRET}},
            extra_headers={"x-api-key": SECRET},
        )

    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 2
    all_blobs: list[bytes] = []
    for span in spans:
        all_blobs.extend(_read_span_blobs(blobstore, span))

    _assert_secret_absent_from_blob_bytes(all_blobs)
    _assert_secret_absent_from_logs(caplog)


def test_blobstore_failure_warning_does_not_log_secret_exception_message(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """NFR-Sec-2: internal WARNING logs record class names, not secret-bearing messages."""
    adapter, blobstore = configured_api
    caplog.set_level(logging.WARNING, logger="plumb.autocapture")
    _try_install_openai()

    class SecretBlobStoreError(RuntimeError):
        def __str__(self) -> str:
            return SECRET

    def put_raises_secret(content: bytes) -> str:
        raise SecretBlobStoreError()

    monkeypatch.setattr(blobstore, "put", put_raises_secret)

    with _api.run(task_id="secret-redaction-logs") as r:
        _openai_client().chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            extra_headers={"x-api-key": SECRET},
        )

    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    assert any(
        getattr(record, "error_class", None) == "SecretBlobStoreError" for record in caplog.records
    )
    _assert_secret_absent_from_logs(caplog)

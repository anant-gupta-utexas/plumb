"""Integration tests for Anthropic autocapture (Task 4.2).

Covers:
- Sync Messages.create inside a run() → 1 span row + 2 blobs persisted
- Async AsyncMessages.create inside a run() → same
- FR-CAP-3: return type unchanged (anthropic.types.Message)
- FR-EDGE-1: RateLimitError → exception re-raised + failure span recorded
- SDK call outside a run → no span, no error
"""

from __future__ import annotations

import hashlib

import anthropic
import httpx
import pytest

import plumb.api as _api
import plumb.autocapture._state as _state
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.autocapture._anthropic import _try_install

from .conftest import (
    CANNED_ANTHROPIC_MESSAGE,
    CANNED_ANTHROPIC_RATE_LIMIT,
    _AsyncAnthropicTransport,
    _SyncAnthropicTransport,
)


# ---------------------------------------------------------------------------
# Sync integration tests
# ---------------------------------------------------------------------------


class TestSyncAnthropicCapture:
    def test_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="anthropic-sync-test") as r:
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].kind.value == "llm"
        assert spans[0].name == "anthropic/messages/claude-sonnet-4-6"

    def test_span_input_output_hash(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="hash-test") as r:
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        span = spans[0]
        assert span.input_hash is not None
        assert len(span.input_hash) == 64
        assert span.output_hash is not None
        assert len(span.output_hash) == 64

    def test_token_counts_recorded(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="tokens-test") as r:
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        span = spans[0]
        # tokens_in stores the sum (tokens_in + tokens_out) per the entity storage contract
        assert span.tokens_in == 15  # 10 + 5
        assert span.tokens_out is None

    def test_two_blobs_exist(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="blobs-test") as r:
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        span = spans[0]
        assert real_bs.exists(span.input_hash)
        assert real_bs.exists(span.output_hash)

    def test_fr_cap3_return_type_unchanged(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """FR-CAP-3: return type must be unchanged."""
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="return-type-test") as r:
            result = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert isinstance(result, anthropic.types.Message)

    def test_fr_edge1_rate_limit_error(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """FR-EDGE-1: RateLimitError re-raised + failure span recorded."""
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            max_retries=0,
            http_client=httpx.Client(
                transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_RATE_LIMIT, status=429)
            ),
        )

        with pytest.raises(anthropic.RateLimitError):
            with _api.run(task_id="edge1-test") as r:
                client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    messages=[{"role": "user", "content": "hi"}],
                )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].kind.value == "llm"
        assert spans[0].error_type == "RateLimitError"

    def test_no_span_outside_run(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """SDK call outside a run context → no span, no error."""
        adapter, bs = configured_api
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        # Call outside any run context
        result = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
        )
        assert isinstance(result, anthropic.types.Message)

    def test_idempotent_install(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """Second _try_install() must not double-wrap."""
        adapter, bs = configured_api
        _try_install()
        _try_install()

        client = anthropic.Anthropic(
            api_key="fake-key",
            http_client=httpx.Client(transport=_SyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)),
        )

        with _api.run(task_id="idempotent-test") as r:
            client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1  # exactly one, not two


# ---------------------------------------------------------------------------
# Async integration tests
# ---------------------------------------------------------------------------


class TestAsyncAnthropicCapture:
    @pytest.mark.asyncio
    async def test_async_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, bs = configured_api
        _try_install()

        client = anthropic.AsyncAnthropic(
            api_key="fake-key",
            http_client=httpx.AsyncClient(
                transport=_AsyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)
            ),
        )

        with _api.run(task_id="anthropic-async-test") as r:
            await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].kind.value == "llm"
        assert spans[0].name == "anthropic/messages/claude-sonnet-4-6"

    @pytest.mark.asyncio
    async def test_async_fr_cap3_return_type_unchanged(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """FR-CAP-3: async return type unchanged."""
        adapter, bs = configured_api
        _try_install()

        client = anthropic.AsyncAnthropic(
            api_key="fake-key",
            http_client=httpx.AsyncClient(
                transport=_AsyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)
            ),
        )

        with _api.run(task_id="async-return-type") as r:
            result = await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        assert isinstance(result, anthropic.types.Message)

    @pytest.mark.asyncio
    async def test_async_fr_edge1_rate_limit_error(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        """FR-EDGE-1: async RateLimitError re-raised + failure span recorded."""
        adapter, bs = configured_api
        _try_install()

        client = anthropic.AsyncAnthropic(
            api_key="fake-key",
            max_retries=0,
            http_client=httpx.AsyncClient(
                transport=_AsyncAnthropicTransport(CANNED_ANTHROPIC_RATE_LIMIT, status=429)
            ),
        )

        with pytest.raises(anthropic.RateLimitError):
            with _api.run(task_id="async-edge1") as r:
                await client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=100,
                    messages=[{"role": "user", "content": "hi"}],
                )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].error_type == "RateLimitError"

    @pytest.mark.asyncio
    async def test_async_two_blobs_exist(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()

        client = anthropic.AsyncAnthropic(
            api_key="fake-key",
            http_client=httpx.AsyncClient(
                transport=_AsyncAnthropicTransport(CANNED_ANTHROPIC_MESSAGE)
            ),
        )

        with _api.run(task_id="async-blobs-test") as r:
            await client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=100,
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        span = spans[0]
        assert real_bs.exists(span.input_hash)
        assert real_bs.exists(span.output_hash)

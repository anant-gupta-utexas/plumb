"""Integration tests for OpenAI autocapture (Phase 5)."""

from __future__ import annotations

import httpx
import openai
import pytest

import plumb.api as _api
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.autocapture._openai import _try_install

from .conftest import (
    CANNED_OPENAI_CHAT_COMPLETION,
    CANNED_OPENAI_RATE_LIMIT,
    CANNED_OPENAI_RESPONSE,
    _AsyncOpenAITransport,
    _SyncOpenAITransport,
)


def _sync_client(body: dict, status: int = 200) -> openai.OpenAI:
    return openai.OpenAI(
        api_key="fake-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=_SyncOpenAITransport(body, status=status)),
    )


def _async_client(body: dict, status: int = 200) -> openai.AsyncOpenAI:
    return openai.AsyncOpenAI(
        api_key="fake-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.AsyncClient(transport=_AsyncOpenAITransport(body, status=status)),
    )


class TestOpenAIChatCapture:
    def test_sync_chat_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()
        client = _sync_client(CANNED_OPENAI_CHAT_COMPLETION)

        with _api.run(task_id="openai-chat-sync") as r:
            result = client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].kind.value == "llm"
        assert spans[0].name == "openai/chat/gpt-4o"
        assert spans[0].tokens_in == 15
        assert spans[0].output_hash is not None
        assert real_bs.exists(spans[0].input_hash)
        assert real_bs.exists(spans[0].output_hash)
        assert isinstance(result, openai.types.chat.ChatCompletion)

    @pytest.mark.asyncio
    async def test_async_chat_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()
        client = _async_client(CANNED_OPENAI_CHAT_COMPLETION)

        with _api.run(task_id="openai-chat-async") as r:
            result = await client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].name == "openai/chat/gpt-4o"
        assert real_bs.exists(spans[0].input_hash)
        assert isinstance(result, openai.types.chat.ChatCompletion)

        await client.close()

    def test_rate_limit_error_reraised_and_failure_span_recorded(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()
        client = _sync_client(CANNED_OPENAI_RATE_LIMIT, status=429)

        with (
            pytest.raises(openai.RateLimitError),
            _api.run(task_id="openai-chat-rate-limit") as r,
        ):
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": "hi"}],
            )

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].status is not None
        assert spans[0].status.value == "failure"
        assert spans[0].error_type == "RateLimitError"


class TestOpenAIResponsesCapture:
    def test_sync_responses_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()
        client = _sync_client(CANNED_OPENAI_RESPONSE)

        with _api.run(task_id="openai-responses-sync") as r:
            result = client.responses.create(model="gpt-4o", input="hi")

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].name == "openai/responses/gpt-4o"
        assert spans[0].tokens_in == 15
        assert real_bs.exists(spans[0].input_hash)
        assert real_bs.exists(spans[0].output_hash)
        assert isinstance(result, openai.types.responses.Response)

    @pytest.mark.asyncio
    async def test_async_responses_span_row_persisted(
        self,
        configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
    ) -> None:
        adapter, real_bs = configured_api
        _try_install()
        client = _async_client(CANNED_OPENAI_RESPONSE)

        with _api.run(task_id="openai-responses-async") as r:
            result = await client.responses.create(model="gpt-4o", input="hi")

        spans = adapter.get_spans_for_run(r.run_id)
        assert len(spans) == 1
        assert spans[0].name == "openai/responses/gpt-4o"
        assert spans[0].tokens_in == 15
        assert real_bs.exists(spans[0].input_hash)
        assert isinstance(result, openai.types.responses.Response)

        await client.close()

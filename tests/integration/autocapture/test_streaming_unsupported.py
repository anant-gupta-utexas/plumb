"""Streaming autocapture currently records an unsupported-stream marker span."""

from __future__ import annotations

import anthropic
import httpx
import openai

import plumb.api as _api
from plumb.adapters.blobstore_fs import FilesystemBlobStore
from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.autocapture._anthropic import _try_install as _try_install_anthropic
from plumb.autocapture._openai import _try_install as _try_install_openai


class _SyncBytesTransport(httpx.BaseTransport):
    def __init__(self, content: bytes, content_type: str) -> None:
        self._content = content
        self._content_type = content_type

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=self._content,
            headers={"content-type": self._content_type},
            request=request,
        )


_OPENAI_STREAM = (
    b'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk",'
    b'"created":1710000000,"model":"gpt-4o","choices":[{"index":0,'
    b'"delta":{"role":"assistant","content":"Hello"},"finish_reason":null}]}\n\n'
    b'data: {"id":"chatcmpl_stream","object":"chat.completion.chunk",'
    b'"created":1710000000,"model":"gpt-4o","choices":[{"index":0,'
    b'"delta":{},"finish_reason":"stop"}]}\n\n'
    b"data: [DONE]\n\n"
)

_ANTHROPIC_STREAM = (
    b"event: message_start\n"
    b'data: {"type":"message_start","message":{"id":"msg_stream","type":"message",'
    b'"role":"assistant","model":"claude-sonnet-4-6","content":[],"stop_reason":null,'
    b'"stop_sequence":null,"usage":{"input_tokens":10,"output_tokens":0}}}\n\n'
    b"event: content_block_start\n"
    b'data: {"type":"content_block_start","index":0,'
    b'"content_block":{"type":"text","text":""}}\n\n'
    b"event: content_block_delta\n"
    b'data: {"type":"content_block_delta","index":0,'
    b'"delta":{"type":"text_delta","text":"Hello"}}\n\n'
    b"event: content_block_stop\n"
    b'data: {"type":"content_block_stop","index":0}\n\n'
    b"event: message_delta\n"
    b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn",'
    b'"stop_sequence":null},"usage":{"output_tokens":5}}\n\n'
    b"event: message_stop\n"
    b'data: {"type":"message_stop"}\n\n'
)


def test_openai_stream_records_unsupported_marker_span(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    adapter, real_bs = configured_api
    _try_install_openai()
    client = openai.OpenAI(
        api_key="fake-key",
        base_url="https://api.openai.test/v1",
        max_retries=0,
        http_client=httpx.Client(
            transport=_SyncBytesTransport(_OPENAI_STREAM, "text/event-stream")
        ),
    )

    with _api.run(task_id="openai-stream") as r:
        stream = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "hi"}],
            stream=True,
        )
        chunks = list(stream)

    assert chunks
    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    assert spans[0].status is not None
    assert spans[0].status.value == "success"
    assert spans[0].name == "openai/chat/gpt-4o"
    assert spans[0].output_hash is None
    assert spans[0].tokens_in is None
    assert spans[0].error_type == "unsupported_stream_capture"
    assert real_bs.exists(spans[0].input_hash)


def test_anthropic_stream_records_unsupported_marker_span(
    configured_api: tuple[SQLiteStorageAdapter, FilesystemBlobStore],
) -> None:
    adapter, real_bs = configured_api
    _try_install_anthropic()
    client = anthropic.Anthropic(
        api_key="fake-key",
        max_retries=0,
        http_client=httpx.Client(
            transport=_SyncBytesTransport(_ANTHROPIC_STREAM, "text/event-stream")
        ),
    )

    with _api.run(task_id="anthropic-stream") as r:
        with client.messages.stream(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": "hi"}],
        ) as stream:
            events = list(stream)

    assert events
    spans = adapter.get_spans_for_run(r.run_id)
    assert len(spans) == 1
    assert spans[0].status is not None
    assert spans[0].status.value == "success"
    assert spans[0].name == "anthropic/messages/claude-sonnet-4-6"
    assert spans[0].output_hash is None
    assert spans[0].tokens_in is None
    assert spans[0].error_type == "unsupported_stream_capture"
    assert real_bs.exists(spans[0].input_hash)

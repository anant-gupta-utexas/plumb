"""Span emission helpers for autocapture.

Converts an SDK request/response pair into a buffered Span via RunHandle.add_span
and stores the raw payloads in the blob store. All failures are swallowed (NFR-Rel-1).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any

from plumb.autocapture import _payloads
from plumb.core.entities import SpanKind, SpanStatus

logger = logging.getLogger(__name__)


def _get_active_run() -> Any:
    from plumb.api import _active_run
    return _active_run.get()


def _get_blobstore() -> Any:
    from plumb.api import _blobstore
    return _blobstore


def _put_blob(content: bytes) -> str:
    """Write content to blob store; return sha256 hex. Errors are logged, not raised."""
    try:
        bs = _get_blobstore()
        if bs is not None:
            return bs.put(content)
    except BaseException as exc:
        logger.warning(
            "plumb autocapture blobstore failure",
            extra={
                "plumb_internal_error": True,
                "subsystem": "autocapture",
                "error_class": type(exc).__name__,
            },
        )
    # Compute hash locally even if blob store failed
    return hashlib.sha256(content).hexdigest()


def emit_success_span(
    *,
    provider: str,
    endpoint: str | None,
    model: str | None,
    request_payload: bytes,
    response: Any,
    latency_ms: float,
) -> None:
    try:
        active = _get_active_run()
        if active is None:
            logger.debug(
                "plumb autocapture: no active run, span skipped",
                extra={"subsystem": "autocapture", "provider": provider},
            )
            return

        input_hash = hashlib.sha256(request_payload).hexdigest()

        # Serialize the response to canonical bytes
        try:
            if provider == "anthropic":
                response_payload = _payloads.canonicalize_anthropic_response(response)
            elif endpoint == "chat":
                response_payload = _payloads.canonicalize_openai_chat_response(response)
            else:
                response_payload = _payloads.canonicalize_openai_responses_response(response)
        except BaseException:
            response_payload = b"{}"

        output_hash = hashlib.sha256(response_payload).hexdigest()

        # Write blobs (errors logged but span emission continues)
        _put_blob(request_payload)
        _put_blob(response_payload)

        # Extract token counts from response.usage
        tokens: tuple[int, int] | None = None
        try:
            usage = getattr(response, "usage", None)
            if usage is not None:
                if provider == "anthropic" or endpoint == "responses":
                    tin = getattr(usage, "input_tokens", None)
                    tout = getattr(usage, "output_tokens", None)
                else:
                    tin = getattr(usage, "prompt_tokens", None)
                    tout = getattr(usage, "completion_tokens", None)
                if tin is not None and tout is not None:
                    tokens = (int(tin), int(tout))
        except BaseException:
            pass

        endpoint_str = endpoint or "unknown"
        model_str = model or "unknown"
        span_name = f"{provider}/{endpoint_str}/{model_str}"

        active.add_span(
            SpanKind.LLM,
            span_name,
            input_hash=input_hash,
            output_hash=output_hash,
            tokens=tokens,
            latency_ms=latency_ms,
            status=SpanStatus.SUCCESS,
        )
    except BaseException as exc:
        logger.warning(
            "plumb autocapture failure",
            extra={
                "plumb_internal_error": True,
                "subsystem": "autocapture",
                "provider": provider,
                "endpoint": endpoint,
                "error_class": type(exc).__name__,
            },
        )


def emit_failure_span(
    *,
    provider: str,
    endpoint: str | None,
    model: str | None,
    request_payload: bytes,
    latency_ms: float,
    error_type: str,
) -> None:
    try:
        active = _get_active_run()
        if active is None:
            logger.debug(
                "plumb autocapture: no active run, failure span skipped",
                extra={"subsystem": "autocapture", "provider": provider},
            )
            return

        input_hash = hashlib.sha256(request_payload).hexdigest()
        _put_blob(request_payload)

        endpoint_str = endpoint or "unknown"
        model_str = model or "unknown"
        span_name = f"{provider}/{endpoint_str}/{model_str}"

        active.add_span(
            SpanKind.LLM,
            span_name,
            input_hash=input_hash,
            output_hash=None,
            tokens=None,
            latency_ms=latency_ms,
            status=SpanStatus.FAILURE,
            error_type=error_type,
        )
    except BaseException as exc:
        logger.warning(
            "plumb autocapture failure",
            extra={
                "plumb_internal_error": True,
                "subsystem": "autocapture",
                "provider": provider,
                "endpoint": endpoint,
                "error_class": type(exc).__name__,
            },
        )

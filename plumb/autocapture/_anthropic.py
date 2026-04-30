"""Anthropic SDK patch installer (sync + async Messages.create).

Lazy import — anthropic is not imported at module load; only inside _try_install().
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

from plumb.autocapture import _payloads
from plumb.autocapture._state import _is_registered, _Patch, _register

logger = logging.getLogger(__name__)

_TARGET_MODULE = "anthropic.resources.messages"
_TARGETS = [
    ("Messages", "create"),
    ("Messages", "stream"),
    ("AsyncMessages", "create"),
]


def _try_install() -> None:
    """Install Anthropic patches. No-op if anthropic is not installed."""
    try:
        import anthropic.resources.messages as _msgs_mod
    except ModuleNotFoundError:
        return

    for cls_name, method_name in _TARGETS:
        key = f"{_TARGET_MODULE}.{cls_name}.{method_name}"
        if _is_registered(key):
            continue
        try:
            cls = getattr(_msgs_mod, cls_name)
            original = getattr(cls, method_name)
        except AttributeError:
            logger.warning(
                "plumb autocapture skip: anthropic patch target moved",
                extra={
                    "plumb_internal_error": True,
                    "subsystem": "autocapture",
                    "provider": "anthropic",
                    "target": f"{cls_name}.{method_name}",
                    "error_class": "AttributeError",
                },
            )
            continue

        if method_name == "stream":
            wrapped = _wrap_messages_stream(original)
        elif cls_name == "AsyncMessages":
            wrapped = _wrap_async_messages_create(original)
        else:
            wrapped = _wrap_messages_create(original)

        patch = _Patch(
            target_module=_TARGET_MODULE,
            target_qualname=f"{cls_name}.{method_name}",
            original=original,
        )
        if _register(patch):
            setattr(cls, method_name, wrapped)


def _wrap_messages_create(original: Any) -> Any:
    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        from plumb.api import _active_run

        active = _active_run.get()
        if active is None:
            return original(self, *args, **kwargs)

        start = time.perf_counter()
        request_payload = _payloads.safe_canonicalize_request(
            _payloads.canonicalize_anthropic_request,
            args,
            kwargs,
            provider="anthropic",
            endpoint="messages",
        )
        try:
            response = original(self, *args, **kwargs)
        except BaseException as exc:
            if request_payload is not _payloads.CANONICALIZATION_FAILED:
                from plumb.autocapture import _emit

                _emit.emit_failure_span(
                    provider="anthropic",
                    endpoint="messages",
                    model=kwargs.get("model"),
                    request_payload=request_payload,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error_type=type(exc).__name__,
                )
            raise

        if request_payload is _payloads.CANONICALIZATION_FAILED:
            return response

        from plumb.autocapture import _emit

        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model=getattr(response, "model", None) or kwargs.get("model"),
            request_payload=request_payload,
            response=response,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return response

    return wrapper


def _wrap_messages_stream(original: Any) -> Any:
    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        from plumb.api import _active_run

        active = _active_run.get()
        if active is None:
            return original(self, *args, **kwargs)

        start = time.perf_counter()
        request_payload = _payloads.safe_canonicalize_request(
            _payloads.canonicalize_anthropic_request,
            args,
            kwargs,
            provider="anthropic",
            endpoint="messages",
        )
        try:
            stream = original(self, *args, **kwargs)
        except BaseException as exc:
            if request_payload is not _payloads.CANONICALIZATION_FAILED:
                from plumb.autocapture import _emit

                _emit.emit_failure_span(
                    provider="anthropic",
                    endpoint="messages",
                    model=kwargs.get("model"),
                    request_payload=request_payload,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error_type=type(exc).__name__,
                )
            raise

        if request_payload is _payloads.CANONICALIZATION_FAILED:
            return stream

        from plumb.autocapture import _emit

        _emit.emit_unsupported_stream_span(
            provider="anthropic",
            endpoint="messages",
            model=kwargs.get("model"),
            request_payload=request_payload,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return stream

    return wrapper


def _wrap_async_messages_create(original: Any) -> Any:
    @functools.wraps(original)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        from plumb.api import _active_run

        active = _active_run.get()
        if active is None:
            return await original(self, *args, **kwargs)

        start = time.perf_counter()
        request_payload = _payloads.safe_canonicalize_request(
            _payloads.canonicalize_anthropic_request,
            args,
            kwargs,
            provider="anthropic",
            endpoint="messages",
        )
        try:
            response = await original(self, *args, **kwargs)
        except BaseException as exc:
            if request_payload is not _payloads.CANONICALIZATION_FAILED:
                from plumb.autocapture import _emit

                _emit.emit_failure_span(
                    provider="anthropic",
                    endpoint="messages",
                    model=kwargs.get("model"),
                    request_payload=request_payload,
                    latency_ms=(time.perf_counter() - start) * 1000,
                    error_type=type(exc).__name__,
                )
            raise

        if request_payload is _payloads.CANONICALIZATION_FAILED:
            return response

        from plumb.autocapture import _emit

        _emit.emit_success_span(
            provider="anthropic",
            endpoint="messages",
            model=getattr(response, "model", None) or kwargs.get("model"),
            request_payload=request_payload,
            response=response,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return response

    return wrapper

"""OpenAI SDK patch installer (Chat Completions + Responses, sync + async).

Lazy import — openai is not imported at module load; only inside _try_install().
"""

from __future__ import annotations

import functools
import logging
import time
from typing import Any

from plumb.autocapture import _payloads
from plumb.autocapture._state import _INSTALLED, _is_registered, _Patch

logger = logging.getLogger(__name__)

_CHAT_MODULE = "openai.resources.chat.completions"
_RESPONSES_MODULE = "openai.resources.responses"

_CHAT_REQ = "canonicalize_openai_chat_request"
_CHAT_RESP = "canonicalize_openai_chat_response"
_RESP_REQ = "canonicalize_openai_responses_request"
_RESP_RESP = "canonicalize_openai_responses_response"

_TARGETS = [
    (_CHAT_MODULE, "Completions", "create", "chat", _CHAT_REQ, _CHAT_RESP),
    (_CHAT_MODULE, "AsyncCompletions", "create", "chat", _CHAT_REQ, _CHAT_RESP),
    (_RESPONSES_MODULE, "Responses", "create", "responses", _RESP_REQ, _RESP_RESP),
    (_RESPONSES_MODULE, "AsyncResponses", "create", "responses", _RESP_REQ, _RESP_RESP),
]


def _try_install() -> None:
    """Install OpenAI patches. No-op if openai is not installed."""
    try:
        import openai  # noqa: F401
    except ModuleNotFoundError:
        return

    import importlib

    for mod_path, cls_name, method_name, endpoint, req_canon, resp_canon in _TARGETS:
        key = f"{mod_path}.{cls_name}.{method_name}"
        if _is_registered(key):
            continue
        try:
            mod = importlib.import_module(mod_path)
            cls = getattr(mod, cls_name)
            original = getattr(cls, method_name)
        except (ImportError, AttributeError):
            logger.warning(
                "plumb autocapture skip: openai patch target moved",
                extra={
                    "plumb_internal_error": True,
                    "subsystem": "autocapture",
                    "provider": "openai",
                    "target": f"{cls_name}.{method_name}",
                    "error_class": "AttributeError",
                },
            )
            continue

        is_async = cls_name.startswith("Async")
        if is_async:
            wrapped = _wrap_async(original, endpoint, req_canon, resp_canon)
        else:
            wrapped = _wrap_sync(original, endpoint, req_canon, resp_canon)

        setattr(cls, method_name, wrapped)
        _INSTALLED[key] = _Patch(
            target_module=mod_path,
            target_qualname=f"{cls_name}.{method_name}",
            original=original,
        )


def _wrap_sync(original: Any, endpoint: str, req_canon: str, resp_canon: str) -> Any:
    @functools.wraps(original)
    def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        from plumb.api import _active_run

        active = _active_run.get()
        if active is None:
            return original(self, *args, **kwargs)

        start = time.perf_counter()
        request_payload = getattr(_payloads, req_canon)(args, kwargs)
        try:
            response = original(self, *args, **kwargs)
        except BaseException as exc:
            from plumb.autocapture import _emit

            _emit.emit_failure_span(
                provider="openai",
                endpoint=endpoint,
                model=kwargs.get("model"),
                request_payload=request_payload,
                latency_ms=(time.perf_counter() - start) * 1000,
                error_type=type(exc).__name__,
            )
            raise

        from plumb.autocapture import _emit

        if kwargs.get("stream") is True:
            _emit.emit_unsupported_stream_span(
                provider="openai",
                endpoint=endpoint,
                model=kwargs.get("model"),
                request_payload=request_payload,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            return response

        _emit.emit_success_span(
            provider="openai",
            endpoint=endpoint,
            model=getattr(response, "model", None) or kwargs.get("model"),
            request_payload=request_payload,
            response=response,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return response

    return wrapper


def _wrap_async(original: Any, endpoint: str, req_canon: str, resp_canon: str) -> Any:
    @functools.wraps(original)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        from plumb.api import _active_run

        active = _active_run.get()
        if active is None:
            return await original(self, *args, **kwargs)

        start = time.perf_counter()
        request_payload = getattr(_payloads, req_canon)(args, kwargs)
        try:
            response = await original(self, *args, **kwargs)
        except BaseException as exc:
            from plumb.autocapture import _emit

            _emit.emit_failure_span(
                provider="openai",
                endpoint=endpoint,
                model=kwargs.get("model"),
                request_payload=request_payload,
                latency_ms=(time.perf_counter() - start) * 1000,
                error_type=type(exc).__name__,
            )
            raise

        from plumb.autocapture import _emit

        if kwargs.get("stream") is True:
            _emit.emit_unsupported_stream_span(
                provider="openai",
                endpoint=endpoint,
                model=kwargs.get("model"),
                request_payload=request_payload,
                latency_ms=(time.perf_counter() - start) * 1000,
            )
            return response

        _emit.emit_success_span(
            provider="openai",
            endpoint=endpoint,
            model=getattr(response, "model", None) or kwargs.get("model"),
            request_payload=request_payload,
            response=response,
            latency_ms=(time.perf_counter() - start) * 1000,
        )
        return response

    return wrapper

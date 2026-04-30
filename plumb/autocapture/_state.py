"""Thread-safe install registry for autocapture SDK patches."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class _Patch:
    target_module: str
    target_qualname: str
    original: Callable[..., Any]


_INSTALL_LOCK: threading.Lock = threading.Lock()
_INSTALLED: dict[str, _Patch] = {}


def _register(patch: _Patch) -> None:
    """Add patch to the registry under its canonical key. Idempotent under lock."""
    key = f"{patch.target_module}.{patch.target_qualname}"
    if key not in _INSTALLED:
        _INSTALLED[key] = patch


def _unregister(key: str) -> None:
    """Remove a patch from the registry. No-op if key is absent."""
    _INSTALLED.pop(key, None)


def _is_registered(key: str) -> bool:
    return key in _INSTALLED

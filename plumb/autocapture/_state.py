"""Thread-safe install registry for autocapture SDK patches.

`_INSTALL_LOCK` is a re-entrant lock so the public `install()`/`uninstall()`
functions can hold it across an entire install pass while internal helpers
(`_register`, `_unregister`, `_is_registered`) re-acquire it for their own
mutations. This makes the registry helpers self-contained: callers do not
need to know about the lock to use them safely.
"""

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


_INSTALL_LOCK: threading.RLock = threading.RLock()
_INSTALLED: dict[str, _Patch] = {}


def _register(patch: _Patch) -> bool:
    """Add patch to the registry under its canonical key. Self-locks.

    Returns True if the patch was newly registered, False if a patch was
    already registered for this target (no-op — idempotent).
    """
    key = f"{patch.target_module}.{patch.target_qualname}"
    with _INSTALL_LOCK:
        if key in _INSTALLED:
            return False
        _INSTALLED[key] = patch
        return True


def _unregister(key: str) -> _Patch | None:
    """Remove a patch from the registry. Self-locks. Returns the popped patch or None."""
    with _INSTALL_LOCK:
        return _INSTALLED.pop(key, None)


def _is_registered(key: str) -> bool:
    """Return True if a patch is registered under `key`. Self-locks."""
    with _INSTALL_LOCK:
        return key in _INSTALLED

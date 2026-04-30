"""Autocapture package — public install/uninstall/is_installed surface.

No eager SDK imports at package-load time (NFR-Perf-6).
Patches are installed lazily on first run() call via plumb.api._init_storage_singletons().
"""

from __future__ import annotations

import logging

from plumb.autocapture._state import _INSTALL_LOCK, _INSTALLED

logger = logging.getLogger(__name__)

_PROVIDERS = (
    "plumb.autocapture._anthropic",
    "plumb.autocapture._openai",
)


def install() -> None:
    """Install all available SDK patches. Idempotent. Thread-safe.

    Patches that fail to import their target SDK are silently skipped.
    """
    with _INSTALL_LOCK:
        for module_path in _PROVIDERS:
            try:
                import importlib

                mod = importlib.import_module(module_path)
                mod._try_install()
            except BaseException as exc:
                logger.warning(
                    "plumb autocapture install failed",
                    extra={
                        "plumb_internal_error": True,
                        "subsystem": "autocapture",
                        "provider_module": module_path,
                        "error_class": type(exc).__name__,
                    },
                )


def uninstall() -> None:
    """Restore all patched SDK methods to their originals. Idempotent. Thread-safe."""
    with _INSTALL_LOCK:
        for key, patch in list(_INSTALLED.items()):
            try:
                import importlib

                mod = importlib.import_module(patch.target_module)
                # Walk the qualname to find the class, then restore the method.
                parts = patch.target_qualname.split(".")
                obj = mod
                for part in parts[:-1]:
                    obj = getattr(obj, part)
                setattr(obj, parts[-1], patch.original)
            except BaseException as exc:
                logger.warning(
                    "plumb autocapture uninstall failed for patch",
                    extra={
                        "plumb_internal_error": True,
                        "subsystem": "autocapture",
                        "patch_key": key,
                        "error_class": type(exc).__name__,
                    },
                )
            del _INSTALLED[key]


def is_installed() -> bool:
    """Return True if at least one SDK patch is currently active."""
    return bool(_INSTALLED)

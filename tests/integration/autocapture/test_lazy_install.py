"""Integration tests for lazy autocapture install from plumb.api (Phase 6.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

import plumb.api as _api
import plumb.autocapture as _autocapture
from plumb.config import get_settings


def _reset_api_singletons(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_api, "_storage", None)
    monkeypatch.setattr(_api, "_blobstore", None)
    monkeypatch.setattr(_api, "_storage_writer", _api._NoopStorageWriter())


def test_first_run_triggers_autocapture_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_api_singletons(monkeypatch)
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "plumb_data"))
    monkeypatch.setenv("PLUMB_AUTOCAPTURE", "1")
    get_settings.cache_clear()

    install_call_count = 0

    def fake_install() -> None:
        nonlocal install_call_count
        install_call_count += 1

    monkeypatch.setattr(_autocapture, "install", fake_install)

    with _api.run(task_id="lazy-install-1"):
        pass

    assert install_call_count == 1

    with _api.run(task_id="lazy-install-2"):
        pass

    assert install_call_count == 1

    if _api._storage is not None:
        _api._storage.close()
    get_settings.cache_clear()


def test_autocapture_env_zero_skips_install(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _reset_api_singletons(monkeypatch)
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "plumb_data"))
    monkeypatch.setenv("PLUMB_AUTOCAPTURE", "0")
    get_settings.cache_clear()

    install_call_count = 0

    def fake_install() -> None:
        nonlocal install_call_count
        install_call_count += 1

    monkeypatch.setattr(_autocapture, "install", fake_install)

    with _api.run(task_id="lazy-install-disabled"):
        pass

    assert install_call_count == 0
    assert _autocapture.is_installed() is False

    if _api._storage is not None:
        _api._storage.close()
    get_settings.cache_clear()

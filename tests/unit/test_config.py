"""Tests for plumb/config.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from plumb.config import Settings, get_settings


def test_default_log_level() -> None:
    s = Settings()
    assert s.log_level == "WARNING"


def test_default_autocapture_false() -> None:
    s = Settings()
    assert s.autocapture is False


def test_default_data_dir_is_path() -> None:
    s = Settings()
    assert isinstance(s.data_dir, Path)


def test_data_dir_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", "/tmp/test_plumb")
    get_settings.cache_clear()
    s = get_settings()
    assert s.data_dir == Path("/tmp/test_plumb")
    get_settings.cache_clear()


def test_log_level_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_LOG_LEVEL", "DEBUG")
    s = Settings()
    assert s.log_level == "DEBUG"


def test_autocapture_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_AUTOCAPTURE", "true")
    s = Settings()
    assert s.autocapture is True


def test_env_prefix_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_LOG_LEVEL", "INFO")
    s = Settings()
    assert s.log_level == "INFO"


def test_get_settings_is_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    s1 = get_settings()
    s2 = get_settings()
    assert s1 is s2
    get_settings.cache_clear()


def test_get_settings_cache_clear_rereads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    get_settings.cache_clear()
    monkeypatch.setenv("PLUMB_DATA_DIR", "/tmp/first")
    s1 = get_settings()
    assert s1.data_dir == Path("/tmp/first")

    get_settings.cache_clear()
    monkeypatch.setenv("PLUMB_DATA_DIR", "/tmp/second")
    s2 = get_settings()
    assert s2.data_dir == Path("/tmp/second")
    get_settings.cache_clear()

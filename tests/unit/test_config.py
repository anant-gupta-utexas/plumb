"""Tests for plumb/config.py."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from plumb.config import Settings, ensure_data_dir, get_settings


def test_default_log_level() -> None:
    s = Settings()
    assert s.log_level == "WARNING"


def test_default_autocapture_true() -> None:
    s = Settings()
    assert s.autocapture is True


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


# ---------------------------------------------------------------------------
# ensure_data_dir (Task 6.1)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode bits only")
def test_ensure_data_dir_creates_with_mode_0700(tmp_path: Path) -> None:
    target = tmp_path / "plumb_data"
    s = Settings(data_dir=target)
    result = ensure_data_dir(s)
    assert result.exists()
    assert (result.stat().st_mode & 0o777) == 0o700


def test_ensure_data_dir_returns_absolute_resolved_path(tmp_path: Path) -> None:
    s = Settings(data_dir=tmp_path / "sub")
    result = ensure_data_dir(s)
    assert result.is_absolute()


def test_ensure_data_dir_idempotent_does_not_change_mode(tmp_path: Path) -> None:
    """Calling twice is a no-op; second call must not raise."""
    s = Settings(data_dir=tmp_path / "data")
    ensure_data_dir(s)
    ensure_data_dir(s)  # must not raise


def test_ensure_data_dir_existing_dir_no_error(tmp_path: Path) -> None:
    """Pre-existing directory: no error raised."""
    target = tmp_path / "existing"
    target.mkdir()
    s = Settings(data_dir=target)
    result = ensure_data_dir(s)
    assert result == target.resolve()


def test_ensure_data_dir_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "from_env"))
    get_settings.cache_clear()
    result = ensure_data_dir()
    assert result.name == "from_env"
    get_settings.cache_clear()


def test_ensure_data_dir_uses_default_settings_when_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PLUMB_DATA_DIR", str(tmp_path / "default_path"))
    get_settings.cache_clear()
    result = ensure_data_dir(None)
    assert result.name == "default_path"
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Judge settings (T1.4)
# ---------------------------------------------------------------------------


def test_judge_provider_default_is_none() -> None:
    s = Settings()
    assert s.judge_provider is None


def test_judge_provider_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_JUDGE_PROVIDER", "anthropic")
    s = Settings()
    assert s.judge_provider == "anthropic"


def test_judge_anthropic_api_key_default_is_none() -> None:
    s = Settings()
    assert s.judge_anthropic_api_key is None


def test_judge_anthropic_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_JUDGE_ANTHROPIC_API_KEY", "sk-ant-test")
    s = Settings()
    assert s.judge_anthropic_api_key == "sk-ant-test"


def test_judge_api_key_default_is_none() -> None:
    s = Settings()
    assert s.judge_api_key is None


def test_judge_api_key_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_JUDGE_API_KEY", "sk-openrouter-test")
    s = Settings()
    assert s.judge_api_key == "sk-openrouter-test"


def test_judge_base_url_default_is_none() -> None:
    s = Settings()
    assert s.judge_base_url is None


def test_judge_base_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_JUDGE_BASE_URL", "https://openrouter.ai/api/v1")
    s = Settings()
    assert s.judge_base_url == "https://openrouter.ai/api/v1"


def test_judge_model_default() -> None:
    s = Settings()
    assert s.judge_model == "claude-sonnet-4-6"


def test_judge_model_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PLUMB_JUDGE_MODEL", "claude-opus-4-5")
    s = Settings()
    assert s.judge_model == "claude-opus-4-5"


def test_existing_defaults_unchanged() -> None:
    s = Settings()
    assert isinstance(s.data_dir, Path)
    assert s.log_level == "WARNING"
    assert s.autocapture is True

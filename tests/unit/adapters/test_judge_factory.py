"""Tests for plumb/adapters/__init__.py — get_judge_adapter factory."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from plumb.adapters import get_judge_adapter
from plumb.config import Settings


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(**kwargs) -> Settings:
    """Build a Settings instance with env_prefix disabled for testing."""
    defaults = {
        "data_dir": "/tmp/plumb_test",
        "judge_provider": None,
        "judge_anthropic_api_key": None,
        "judge_api_key": None,
        "judge_base_url": None,
        "judge_model": "claude-sonnet-4-6",
    }
    defaults.update(kwargs)
    return Settings.model_validate(defaults)


def _write_prompt(tmp_path: Path, metric_name: str, content: str = "Rate this.") -> Path:
    prompt_file = tmp_path / f"{metric_name}.md"
    prompt_file.write_text(content, encoding="utf-8")
    return prompt_file


# ---------------------------------------------------------------------------
# Provider not set
# ---------------------------------------------------------------------------


def test_no_provider_raises_value_error(tmp_path: Path) -> None:
    settings = _settings(judge_provider=None)
    with pytest.raises(ValueError, match="PLUMB_JUDGE_PROVIDER"):
        get_judge_adapter(settings, metric_name="quality")


def test_empty_provider_raises_value_error(tmp_path: Path) -> None:
    settings = _settings(judge_provider="")
    with pytest.raises(ValueError, match="PLUMB_JUDGE_PROVIDER"):
        get_judge_adapter(settings, metric_name="quality")


# ---------------------------------------------------------------------------
# Unsupported provider
# ---------------------------------------------------------------------------


def test_unsupported_provider_raises_value_error(tmp_path: Path) -> None:
    settings = _settings(judge_provider="unknown")
    with pytest.raises(ValueError, match="Unsupported PLUMB_JUDGE_PROVIDER: 'unknown'"):
        # load_prompt will fail first if no prompt dir; mock it out
        with patch(
            "plumb._prompt_loader.load_prompt", return_value=("prompt text", "a1b2c3d4")
        ):
            get_judge_adapter(settings, metric_name="quality")


# ---------------------------------------------------------------------------
# Anthropic provider
# ---------------------------------------------------------------------------


def test_anthropic_missing_key_raises(tmp_path: Path) -> None:
    settings = _settings(judge_provider="anthropic", judge_anthropic_api_key=None)
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with pytest.raises(ValueError, match="PLUMB_JUDGE_ANTHROPIC_API_KEY"):
            get_judge_adapter(settings, metric_name="quality")


def test_anthropic_returns_anthropic_judge(tmp_path: Path) -> None:
    from plumb.adapters.judge_anthropic import AnthropicJudge
    from plumb.core.ports import JudgeAdapter

    settings = _settings(judge_provider="anthropic", judge_anthropic_api_key="sk-ant-key")
    with patch("plumb._prompt_loader.load_prompt", return_value=("judge prompt", "a1b2c3d4")):
        with patch("plumb.adapters.judge_anthropic.AnthropicJudge._build_client"):
            adapter = get_judge_adapter(settings, metric_name="routing_top1")

    assert isinstance(adapter, AnthropicJudge)
    assert isinstance(adapter, JudgeAdapter)


def test_anthropic_prompt_passed_to_adapter(tmp_path: Path) -> None:
    from plumb.adapters.judge_anthropic import AnthropicJudge

    settings = _settings(judge_provider="anthropic", judge_anthropic_api_key="sk-ant-key")
    with patch(
        "plumb._prompt_loader.load_prompt", return_value=("my judge prompt", "deadbeef")
    ):
        with patch("plumb.adapters.judge_anthropic.AnthropicJudge._build_client"):
            adapter = get_judge_adapter(settings, metric_name="routing_top1")

    assert isinstance(adapter, AnthropicJudge)
    assert adapter._prompt == "my judge prompt"
    assert adapter._prompt_sha == "deadbeef"


# ---------------------------------------------------------------------------
# OpenAI-compat provider
# ---------------------------------------------------------------------------


def test_openai_compat_missing_key_raises(tmp_path: Path) -> None:
    settings = _settings(judge_provider="openai_compat", judge_api_key=None)
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with pytest.raises(ValueError, match="PLUMB_JUDGE_API_KEY"):
            get_judge_adapter(settings, metric_name="quality")


def test_openai_compat_returns_openai_judge(tmp_path: Path) -> None:
    from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge
    from plumb.core.ports import JudgeAdapter

    settings = _settings(judge_provider="openai_compat", judge_api_key="sk-openai-key")
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with patch(
            "plumb.adapters.judge_openai_compat.OpenAICompatibleJudge._build_client"
        ):
            adapter = get_judge_adapter(settings, metric_name="quality")

    assert isinstance(adapter, OpenAICompatibleJudge)
    assert isinstance(adapter, JudgeAdapter)


def test_openai_compat_base_url_forwarded(tmp_path: Path) -> None:
    from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge

    settings = _settings(
        judge_provider="openai_compat",
        judge_api_key="sk-key",
        judge_base_url="https://openrouter.ai/api/v1",
    )
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with patch(
            "plumb.adapters.judge_openai_compat.OpenAICompatibleJudge._build_client"
        ):
            adapter = get_judge_adapter(settings, metric_name="quality")

    assert isinstance(adapter, OpenAICompatibleJudge)
    assert adapter._base_url == "https://openrouter.ai/api/v1"


def test_openai_compat_no_base_url_is_none(tmp_path: Path) -> None:
    from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge

    settings = _settings(
        judge_provider="openai_compat",
        judge_api_key="sk-key",
        judge_base_url=None,
    )
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with patch(
            "plumb.adapters.judge_openai_compat.OpenAICompatibleJudge._build_client"
        ):
            adapter = get_judge_adapter(settings, metric_name="quality")

    assert isinstance(adapter, OpenAICompatibleJudge)
    assert adapter._base_url is None


# ---------------------------------------------------------------------------
# Prompt file missing propagates FileNotFoundError
# ---------------------------------------------------------------------------


def test_missing_prompt_propagates_file_not_found(tmp_path: Path) -> None:
    settings = _settings(judge_provider="anthropic", judge_anthropic_api_key="sk-ant-key")
    # load_prompt raises FileNotFoundError when file is absent
    with pytest.raises(FileNotFoundError):
        get_judge_adapter(settings, metric_name="nonexistent_metric")


# ---------------------------------------------------------------------------
# Lazy imports: provider isolation (NFR-Perf-6)
# ---------------------------------------------------------------------------


def test_anthropic_provider_does_not_import_openai(tmp_path: Path) -> None:
    """Selecting 'anthropic' must not cause openai to be imported."""
    openai_was_already_imported = "openai" in sys.modules

    settings = _settings(judge_provider="anthropic", judge_anthropic_api_key="sk-ant-key")
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with patch("plumb.adapters.judge_anthropic.AnthropicJudge._build_client"):
            get_judge_adapter(settings, metric_name="quality")

    if not openai_was_already_imported:
        assert "openai" not in sys.modules, "openai must not be imported for provider=anthropic"


def test_openai_compat_provider_does_not_import_anthropic(tmp_path: Path) -> None:
    """Selecting 'openai_compat' must not cause anthropic to be imported."""
    anthropic_was_already_imported = "anthropic" in sys.modules

    settings = _settings(judge_provider="openai_compat", judge_api_key="sk-key")
    with patch("plumb._prompt_loader.load_prompt", return_value=("prompt", "sha")):
        with patch(
            "plumb.adapters.judge_openai_compat.OpenAICompatibleJudge._build_client"
        ):
            get_judge_adapter(settings, metric_name="quality")

    if not anthropic_was_already_imported:
        assert "anthropic" not in sys.modules, (
            "anthropic must not be imported for provider=openai_compat"
        )

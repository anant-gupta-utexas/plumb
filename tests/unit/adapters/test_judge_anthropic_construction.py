"""Constructor and metadata tests for plumb/adapters/judge_anthropic.py.

Scoring tests live in test_judge_anthropic_scoring.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from plumb.adapters.judge_anthropic import AnthropicJudge
from plumb.core.errors import ValidationError


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValidationError):
        AnthropicJudge(api_key="", prompt="p", prompt_sha="a1b2c3d4")


def test_rejects_empty_prompt() -> None:
    with pytest.raises(ValidationError):
        AnthropicJudge(api_key="sk-ant-test", prompt="", prompt_sha="a1b2c3d4")


def test_rejects_empty_prompt_sha() -> None:
    with pytest.raises(ValidationError):
        AnthropicJudge(api_key="sk-ant-test", prompt="p", prompt_sha="")


def test_accepts_injected_client() -> None:
    client = MagicMock()
    judge = AnthropicJudge(api_key="sk-ant-test", prompt="p", prompt_sha="sha", client=client)
    assert judge._client is client


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_name_and_version() -> None:
    client = MagicMock()
    judge = AnthropicJudge(
        api_key="sk-ant-test", prompt="p", prompt_sha="a1b2c3d4", client=client
    )
    assert judge.name == "anthropic"
    assert judge.version == "1"


def test_isinstance_judge_adapter() -> None:
    from plumb.core.ports import JudgeAdapter

    client = MagicMock()
    judge = AnthropicJudge(
        api_key="sk-ant-test", prompt="p", prompt_sha="a1b2c3d4", client=client
    )
    assert isinstance(judge, JudgeAdapter)

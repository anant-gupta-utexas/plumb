"""Constructor and metadata tests for plumb/adapters/judge_openai_compat.py.

Scoring tests live in test_judge_openai_compat_scoring.py.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge
from plumb.core.errors import ValidationError


# ---------------------------------------------------------------------------
# Constructor validation
# ---------------------------------------------------------------------------


def test_rejects_empty_api_key() -> None:
    with pytest.raises(ValidationError):
        OpenAICompatibleJudge(api_key="", prompt="p", prompt_sha="a1b2c3d4")


def test_rejects_empty_prompt() -> None:
    with pytest.raises(ValidationError):
        OpenAICompatibleJudge(api_key="sk-test", prompt="", prompt_sha="a1b2c3d4")


def test_rejects_empty_prompt_sha() -> None:
    with pytest.raises(ValidationError):
        OpenAICompatibleJudge(api_key="sk-test", prompt="p", prompt_sha="")


def test_accepts_injected_client() -> None:
    client = MagicMock()
    judge = OpenAICompatibleJudge(api_key="sk-test", prompt="p", prompt_sha="sha", client=client)
    assert judge._client is client


def test_base_url_none_does_not_pass_to_kwargs() -> None:
    """base_url=None → _base_url stored as None (SDK uses its default)."""
    client = MagicMock()
    judge = OpenAICompatibleJudge(
        api_key="sk-test", prompt="p", prompt_sha="sha", base_url=None, client=client
    )
    assert judge._base_url is None


def test_base_url_stored_when_provided() -> None:
    client = MagicMock()
    judge = OpenAICompatibleJudge(
        api_key="sk-test",
        prompt="p",
        prompt_sha="sha",
        base_url="https://openrouter.ai/api/v1",
        client=client,
    )
    assert judge._base_url == "https://openrouter.ai/api/v1"


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


def test_name_and_version() -> None:
    client = MagicMock()
    judge = OpenAICompatibleJudge(
        api_key="sk-test", prompt="p", prompt_sha="sha", client=client
    )
    assert judge.name == "openai_compat"
    assert judge.version == "1"


def test_isinstance_judge_adapter() -> None:
    from plumb.core.ports import JudgeAdapter

    client = MagicMock()
    judge = OpenAICompatibleJudge(
        api_key="sk-test", prompt="p", prompt_sha="sha", client=client
    )
    assert isinstance(judge, JudgeAdapter)

# plumb/adapters — port implementations; no eager imports (NFR-Perf-6)

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from plumb.config import Settings
    from plumb.core.ports import JudgeAdapter


def get_judge_adapter(settings: Settings, *, metric_name: str) -> JudgeAdapter:
    """Instantiate the configured judge adapter.

    Reads provider, credentials, and model from *settings*; loads the judge
    prompt via :func:`plumb._prompt_loader.load_prompt`. SDK imports are lazy
    so importing ``plumb`` does not pull in ``anthropic`` or ``openai``.

    Args:
        settings: Resolved :class:`~plumb.config.Settings` instance.
        metric_name: Metric name; used to locate the prompt file.

    Returns:
        A :class:`~plumb.core.ports.JudgeAdapter` ready to call ``.score()``.

    Raises:
        ValueError: ``PLUMB_JUDGE_PROVIDER`` is not set, or is an unsupported
            value, or required credentials are missing.
        FileNotFoundError: The prompt file for *metric_name* does not exist.

    Example::

        from plumb.config import get_settings
        from plumb.adapters import get_judge_adapter
        adapter = get_judge_adapter(get_settings(), metric_name="routing_top1")
        result = adapter.score(metric_name="routing_top1", prompt="", content="...", model="gpt-4o")
    """
    provider = settings.judge_provider
    if not provider:
        raise ValueError(
            "PLUMB_JUDGE_PROVIDER is not set. "
            "Set it to 'anthropic' or 'openai_compat' to use 'plumb judge run'."
        )

    # Validate provider and credentials before loading the prompt so callers
    # see meaningful errors ("unsupported provider", "missing API key") rather
    # than a FileNotFoundError that masks the real configuration problem.
    if provider not in ("anthropic", "openai_compat"):
        raise ValueError(f"Unsupported PLUMB_JUDGE_PROVIDER: {provider!r}")

    if provider == "anthropic" and not settings.judge_anthropic_api_key:
        raise ValueError(
            "PLUMB_JUDGE_ANTHROPIC_API_KEY is not set. "
            "Provide your Anthropic API key to use provider='anthropic'."
        )

    if provider == "openai_compat" and not settings.judge_api_key:
        raise ValueError(
            "PLUMB_JUDGE_API_KEY is not set. Provide your API key to use provider='openai_compat'."
        )

    # Resolve the prompt directory from the *supplied* settings object, not the
    # cached global, so callers with a custom data_dir get the correct path.
    from pathlib import Path

    from plumb._prompt_loader import load_prompt
    from plumb.config import ensure_data_dir

    prompts_dir: Path = ensure_data_dir(settings) / "judge_prompts"
    prompt_text, prompt_sha = load_prompt(metric_name, prompts_dir=prompts_dir)

    if provider == "anthropic":
        return _make_anthropic(settings, prompt_text, prompt_sha)

    return _make_openai_compat(settings, prompt_text, prompt_sha)


def _make_anthropic(settings: Settings, prompt_text: str, prompt_sha: str) -> JudgeAdapter:
    from plumb.adapters.judge_anthropic import AnthropicJudge

    api_key = settings.judge_anthropic_api_key
    if not api_key:
        raise ValueError(
            "PLUMB_JUDGE_ANTHROPIC_API_KEY is not set. "
            "Provide your Anthropic API key to use provider='anthropic'."
        )
    return AnthropicJudge(api_key=api_key, prompt=prompt_text, prompt_sha=prompt_sha)


def _make_openai_compat(settings: Settings, prompt_text: str, prompt_sha: str) -> JudgeAdapter:
    from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge

    api_key = settings.judge_api_key
    if not api_key:
        raise ValueError(
            "PLUMB_JUDGE_API_KEY is not set. Provide your API key to use provider='openai_compat'."
        )
    return OpenAICompatibleJudge(
        api_key=api_key,
        prompt=prompt_text,
        prompt_sha=prompt_sha,
        base_url=settings.judge_base_url,
    )

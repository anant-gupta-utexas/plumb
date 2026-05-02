"""OpenAI-compatible judge adapter (INT-JUDGE-2).

Works with any API that speaks the OpenAI chat-completions protocol:
OpenAI, OpenRouter, Ollama, vLLM, LM Studio, LiteLLM, etc.

Example usage::

    from plumb.adapters.judge_openai_compat import OpenAICompatibleJudge
    judge = OpenAICompatibleJudge(
        api_key="sk-...",
        prompt="Rate this output as pass or fail.",
        prompt_sha="a1b2c3d4",
        base_url="https://openrouter.ai/api/v1",
    )
    result = judge.score(
        metric_name="routing_top1", prompt="", content="...", model="gpt-4o"
    )
"""

from __future__ import annotations

import logging
import time
from typing import Any

from plumb.adapters._judge_common import (
    JudgeFatalError,
    JudgeTransientError,
    RawJudgeReply,
    parse_reply,
    redact_body,
    with_judge_retry,
)
from plumb.core.entities import JudgeResult
from plumb.core.errors import ValidationError

logger = logging.getLogger(__name__)

_PROVIDER = "openai_compat"
_MAX_RATIONALE_ERROR = 500


class OpenAICompatibleJudge:
    """LLM-as-judge adapter backed by the OpenAI-compatible chat completions API.

    Implements :class:`plumb.core.ports.JudgeAdapter`.

    Args:
        api_key: API key for the provider. Must be non-empty.
        prompt: The judge system prompt text. Must be non-empty.
        prompt_sha: 8-char SHA256 prefix of the prompt (from
            :func:`plumb._prompt_loader.load_prompt`). Must be non-empty.
        base_url: Optional base URL override (e.g. ``"https://openrouter.ai/api/v1"``).
            If ``None``, the SDK uses its default (``api.openai.com``).
        client: Optional pre-built ``openai.OpenAI`` client for
            dependency injection in tests.

    Example::

        judge = OpenAICompatibleJudge(
            api_key="sk-...", prompt="...", prompt_sha="a1b2c3d4",
            base_url="https://openrouter.ai/api/v1",
        )
        result = judge.score(
            metric_name="quality", prompt="", content="hello", model="gpt-4o"
        )
    """

    name: str = _PROVIDER
    version: str = "1"

    def __init__(
        self,
        *,
        api_key: str,
        prompt: str,
        prompt_sha: str,
        base_url: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not api_key:
            raise ValidationError("api_key must be non-empty")
        if not prompt:
            raise ValidationError("prompt must be non-empty")
        if not prompt_sha:
            raise ValidationError("prompt_sha must be non-empty")

        self._api_key = api_key
        self._prompt = prompt
        self._prompt_sha = prompt_sha
        self._base_url = base_url
        self._client = client or self._build_client(api_key, base_url)

    @staticmethod
    def _build_client(api_key: str, base_url: str | None) -> Any:
        import openai

        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url is not None:
            kwargs["base_url"] = base_url
        return openai.OpenAI(**kwargs)

    def score(
        self,
        *,
        metric_name: str,
        prompt: str,  # ignored — adapter uses its constructor prompt
        content: str,
        model: str,
        timeout_s: float = 60.0,
    ) -> JudgeResult:
        """Score *content* against this adapter's system prompt.

        The *prompt* parameter is accepted (required by the Protocol) but
        ignored. The adapter always uses the prompt supplied at construction.

        Args:
            metric_name: Name of the metric being evaluated.
            prompt: Ignored. The constructor-supplied prompt is used.
            content: The candidate content to evaluate.
            model: Model identifier, e.g. ``"gpt-4o"``.
            timeout_s: HTTP timeout in seconds.

        Returns:
            A :class:`~plumb.core.entities.JudgeResult` with ``value_label``
            set to ``"pass"``, ``"fail"``, or ``"error"`` (fail-open).

        Example::

            result = judge.score(
                metric_name="quality", prompt="", content="hello", model="gpt-4o"
            )
            assert result.scorer_version.startswith("openai_compat:")
        """
        scorer_version = f"{_PROVIDER}:{model}:{self._prompt_sha}"
        try:
            raw = self._invoke(content=content, model=model, timeout_s=timeout_s)
        except (JudgeTransientError, JudgeFatalError) as exc:
            return self._fail_open(metric_name, scorer_version, str(exc))

        try:
            label, numeric, rationale = parse_reply(raw.text)
        except ValueError as exc:
            return self._fail_open(metric_name, scorer_version, str(exc))

        return JudgeResult(
            metric_name=metric_name,
            scorer_version=scorer_version,
            rationale=rationale,
            tokens_in=raw.tokens_in,
            tokens_out=raw.tokens_out,
            latency_ms=raw.latency_ms,
            value_label=label,
            value_numeric=numeric,
        )

    @with_judge_retry
    def _invoke(self, *, content: str, model: str, timeout_s: float) -> RawJudgeReply:
        import openai

        t0 = time.monotonic()
        try:
            resp = self._client.chat.completions.create(
                model=model,
                temperature=0.0,
                max_tokens=1024,
                messages=[
                    {"role": "system", "content": self._prompt},
                    {"role": "user", "content": content},
                ],
                timeout=timeout_s,
            )
        except openai.RateLimitError as exc:
            raise JudgeTransientError(str(exc)) from exc
        except openai.APIConnectionError as exc:
            raise JudgeTransientError(str(exc)) from exc
        except openai.APIStatusError as exc:
            if exc.status_code >= 500:
                raise JudgeTransientError(str(exc)) from exc
            raise JudgeFatalError(str(exc)) from exc
        except openai.OpenAIError as exc:
            raise JudgeFatalError(str(exc)) from exc

        latency_ms = (time.monotonic() - t0) * 1000.0
        text = resp.choices[0].message.content or "" if resp.choices else ""
        tokens_in = resp.usage.prompt_tokens if resp.usage else 0
        tokens_out = resp.usage.completion_tokens if resp.usage else 0
        return RawJudgeReply(
            text=text,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _fail_open(metric_name: str, scorer_version: str, reason: str) -> JudgeResult:
        safe_reason = redact_body(reason)[:_MAX_RATIONALE_ERROR]
        logger.warning(
            "OpenAICompatibleJudge fail-open for metric=%r: %s", metric_name, safe_reason
        )
        return JudgeResult(
            metric_name=metric_name,
            scorer_version=f"{scorer_version}:error",
            rationale=safe_reason,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0.0,
            value_label="error",
        )

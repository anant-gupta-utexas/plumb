"""Anthropic-native judge adapter (INT-JUDGE-1).

Uses the ``anthropic`` SDK directly; supports prompt caching via
``cache_control={"type": "ephemeral"}`` on the system prompt.

Example usage::

    from plumb.adapters.judge_anthropic import AnthropicJudge
    judge = AnthropicJudge(
        api_key="sk-ant-...",
        prompt="Rate this output as pass or fail.",
        prompt_sha="a1b2c3d4",
    )
    result = judge.score(metric_name="routing_top1", prompt="", content="...", model="claude-sonnet-4-6")
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

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

if TYPE_CHECKING:
    import anthropic as _anthropic_module

logger = logging.getLogger(__name__)

_PROVIDER = "anthropic"
_MAX_RATIONALE_ERROR = 500


class AnthropicJudge:
    """LLM-as-judge adapter backed by the Anthropic Messages API.

    Implements :class:`plumb.core.ports.JudgeAdapter`.

    Args:
        api_key: Anthropic API key. Must be non-empty.
        prompt: The judge system prompt text. Must be non-empty.
        prompt_sha: 8-char SHA256 prefix of the prompt (from
            :func:`plumb._prompt_loader.load_prompt`). Must be non-empty.
        model: Default model; can be overridden per ``score()`` call.
        client: Optional pre-built ``anthropic.Anthropic`` client for
            dependency injection in tests.

    Example::

        judge = AnthropicJudge(api_key="sk-...", prompt="...", prompt_sha="a1b2c3d4")
        result = judge.score(metric_name="quality", prompt="", content="hello", model="claude-sonnet-4-6")
    """

    name: str = _PROVIDER
    version: str = "1"

    def __init__(
        self,
        *,
        api_key: str,
        prompt: str,
        prompt_sha: str,
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
        self._client = client or self._build_client(api_key)

    @staticmethod
    def _build_client(api_key: str) -> Any:
        import anthropic

        return anthropic.Anthropic(api_key=api_key)

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
            model: Anthropic model identifier, e.g. ``"claude-sonnet-4-6"``.
            timeout_s: HTTP timeout in seconds.

        Returns:
            A :class:`~plumb.core.entities.JudgeResult` with ``value_label``
            set to ``"pass"``, ``"fail"``, or ``"error"`` (fail-open).

        Example::

            result = judge.score(metric_name="quality", prompt="", content="hello", model="claude-sonnet-4-6")
            assert result.scorer_version.startswith("anthropic:")
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
        import anthropic

        t0 = time.monotonic()
        try:
            resp = self._client.messages.create(
                model=model,
                max_tokens=1024,
                temperature=0.0,
                system=[
                    {
                        "type": "text",
                        "text": self._prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=[{"role": "user", "content": content}],
                timeout=timeout_s,
            )
        except anthropic.RateLimitError as exc:
            raise JudgeTransientError(str(exc)) from exc
        except anthropic.APIConnectionError as exc:
            raise JudgeTransientError(str(exc)) from exc
        except anthropic.APIStatusError as exc:
            if exc.status_code >= 500:
                raise JudgeTransientError(str(exc)) from exc
            raise JudgeFatalError(str(exc)) from exc
        except anthropic.AnthropicError as exc:
            raise JudgeFatalError(str(exc)) from exc

        latency_ms = (time.monotonic() - t0) * 1000.0
        text = resp.content[0].text if resp.content else ""
        return RawJudgeReply(
            text=text,
            tokens_in=resp.usage.input_tokens,
            tokens_out=resp.usage.output_tokens,
            latency_ms=latency_ms,
        )

    @staticmethod
    def _fail_open(metric_name: str, scorer_version: str, reason: str) -> JudgeResult:
        safe_reason = redact_body(reason)[:_MAX_RATIONALE_ERROR]
        logger.warning("AnthropicJudge fail-open for metric=%r: %s", metric_name, safe_reason)
        return JudgeResult(
            metric_name=metric_name,
            scorer_version=f"{scorer_version}:error",
            rationale=safe_reason,
            tokens_in=0,
            tokens_out=0,
            latency_ms=0.0,
            value_label="error",
        )

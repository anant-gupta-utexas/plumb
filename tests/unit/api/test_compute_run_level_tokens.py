"""Tests for _compute_run_level_tokens (Task 9, FR-USAGE-3 auto-fill)."""

from __future__ import annotations

from plumb.api import _compute_run_level_tokens
from plumb.core.entities import Span, SpanKind

_RUN_ID = "a" * 32


def _span(span_id_byte: str, tokens_in: int | None, tokens_out: int | None) -> Span:
    return Span(
        span_id=span_id_byte * 32,
        run_id=_RUN_ID,
        kind=SpanKind.LLM,
        name="s",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )


class TestComputeRunLevelTokens:
    def test_explicit_wins_no_spans(self) -> None:
        tokens_in, tokens_out = _compute_run_level_tokens(999, 888, [])
        assert (tokens_in, tokens_out) == (999, 888)

    def test_explicit_wins_over_span_sum_no_merge(self) -> None:
        spans = [_span("1", 10, 25), _span("2", 5, 30)]
        tokens_in, tokens_out = _compute_run_level_tokens(999, None, spans)
        # explicit tokens_in wins; tokens_out stays as explicitly passed (None),
        # no merging with the span-derived sum.
        assert (tokens_in, tokens_out) == (999, None)

    def test_auto_fill_sums_eligible_spans(self) -> None:
        spans = [_span("1", 10, 25), _span("2", 5, 30)]
        tokens_in, tokens_out = _compute_run_level_tokens(None, None, spans)
        assert (tokens_in, tokens_out) == (15, 55)

    def test_auto_fill_excludes_spans_with_none_tokens_in(self) -> None:
        spans = [_span("1", 10, 25), _span("2", None, None)]
        tokens_in, tokens_out = _compute_run_level_tokens(None, None, spans)
        assert (tokens_in, tokens_out) == (10, 25)

    def test_auto_fill_no_eligible_spans_returns_none(self) -> None:
        spans = [_span("1", None, None)]
        tokens_in, tokens_out = _compute_run_level_tokens(None, None, spans)
        assert (tokens_in, tokens_out) == (None, None)

    def test_auto_fill_no_spans_returns_none(self) -> None:
        tokens_in, tokens_out = _compute_run_level_tokens(None, None, [])
        assert (tokens_in, tokens_out) == (None, None)

    def test_eligible_span_with_none_tokens_out_counts_as_zero(self) -> None:
        spans = [_span("1", 10, None), _span("2", 5, 30)]
        tokens_in, tokens_out = _compute_run_level_tokens(None, None, spans)
        assert (tokens_in, tokens_out) == (15, 30)

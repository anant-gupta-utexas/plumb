"""Tests for parse_reply in plumb/adapters/_judge_common.py.

Includes a Hypothesis property test asserting that parse_reply never returns
a mixed (label + numeric) state — it either returns exactly one set, or raises.
"""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import settings as h_settings
from hypothesis import strategies as st

from plumb.adapters._judge_common import parse_reply


# ---------------------------------------------------------------------------
# Happy paths
# ---------------------------------------------------------------------------


def test_parse_pass_verdict() -> None:
    label, num, rationale = parse_reply('{"verdict":"pass","rationale":"ok"}')
    assert label == "pass"
    assert num is None
    assert rationale == "ok"


def test_parse_fail_verdict() -> None:
    label, num, rationale = parse_reply('{"verdict":"fail","rationale":"bad"}')
    assert label == "fail"
    assert num is None
    assert rationale == "bad"


def test_parse_numeric_verdict() -> None:
    label, num, rationale = parse_reply('{"verdict":0.92,"rationale":"close"}')
    assert label is None
    assert num == pytest.approx(0.92)
    assert rationale == "close"


def test_parse_numeric_integer_verdict() -> None:
    label, num, rationale = parse_reply('{"verdict":1,"rationale":"perfect"}')
    assert label is None
    assert isinstance(num, float)
    assert num == 1.0


def test_parse_zero_numeric_verdict() -> None:
    label, num, rationale = parse_reply('{"verdict":0,"rationale":"wrong"}')
    assert label is None
    assert num == 0.0


def test_parse_code_fenced_json() -> None:
    text = '```json\n{"verdict":"pass","rationale":""}\n```'
    label, num, rationale = parse_reply(text)
    assert label == "pass"
    assert num is None
    assert rationale == ""


def test_parse_code_fenced_no_lang_tag() -> None:
    text = '```\n{"verdict":"fail","rationale":"nope"}\n```'
    label, num, rationale = parse_reply(text)
    assert label == "fail"


def test_parse_rationale_truncated_to_1000_chars() -> None:
    long_rationale = "x" * 2000
    label, num, rationale = parse_reply(
        f'{{"verdict":"pass","rationale":"{long_rationale}"}}'
    )
    assert len(rationale) == 1000


def test_parse_missing_rationale_defaults_to_empty() -> None:
    label, num, rationale = parse_reply('{"verdict":"pass"}')
    assert rationale == ""


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


def test_parse_not_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply("not json")


def test_parse_invalid_verdict_string_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('{"verdict":"maybe"}')


def test_parse_bool_verdict_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('{"verdict":true}')


def test_parse_false_bool_verdict_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('{"verdict":false}')


def test_parse_missing_verdict_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('{"rationale":"ok"}')


def test_parse_non_dict_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('["pass"]')


def test_parse_null_verdict_raises() -> None:
    with pytest.raises(ValueError):
        parse_reply('{"verdict":null}')


# ---------------------------------------------------------------------------
# Hypothesis property test
# ---------------------------------------------------------------------------


@given(st.text())
@h_settings(max_examples=300)
def test_parse_reply_never_mixed_state(text: str) -> None:
    """parse_reply must return exactly one of label/numeric set, or raise."""
    try:
        label, num, _ = parse_reply(text)
    except Exception:
        return
    label_set = label is not None
    num_set = num is not None
    assert label_set != num_set, f"Mixed state: label={label!r}, num={num!r}"

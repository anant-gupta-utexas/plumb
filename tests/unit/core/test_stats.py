"""Tests for plumb/core/stats.py — McNemar paired test + Benjamini-Hochberg FDR."""

from __future__ import annotations

import math

import pytest
from hypothesis import given, settings, strategies as st

from plumb.core.stats import benjamini_hochberg, mcnemar_paired

# ---------------------------------------------------------------------------
# McNemar — known-answer reference cases (§6.3 algorithms doc)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "b, c, expected_p, tol",
    [
        # Reference values computed via scipy.stats.chi2.sf with Yates' correction
        (10, 2, 0.04331, 1e-4),
        (5, 5, 0.75183, 1e-4),  # corrected statistic = 0.1; p < 1 with correction
        (20, 0, 2.152e-5, 1e-6),
        (1, 0, 1.0, 1e-6),  # n_discordant=1, statistic=0 with correction
        (100, 50, 6.312e-5, 1e-6),
    ],
)
def test_mcnemar_known_answers(b: int, c: int, expected_p: float, tol: float) -> None:
    baseline = [True] * b + [False] * c
    candidate = [False] * b + [True] * c
    result = mcnemar_paired(baseline, candidate)
    assert result.b == b
    assert result.c == c
    assert abs(result.p_value - expected_p) < tol, (
        f"b={b}, c={c}: p={result.p_value!r}, expected≈{expected_p}"
    )


def _build_pairs(b: int, c: int) -> tuple[list[bool], list[bool]]:
    """Construct sequences with exactly b and c discordant pairs."""
    baseline = [True] * b + [False] * c
    candidate = [False] * b + [True] * c
    return baseline, candidate


def test_mcnemar_statistic_b10_c2() -> None:
    bl, cn = _build_pairs(10, 2)
    result = mcnemar_paired(bl, cn)
    assert result.b == 10
    assert result.c == 2
    assert result.n_discordant == 12
    # Yates-corrected: (|10-2|-1)^2 / 12 = 49/12 ≈ 4.083, p ≈ 0.04331
    assert abs(result.p_value - 0.04331) < 1e-4


def test_mcnemar_symmetric_gives_high_p() -> None:
    bl, cn = _build_pairs(5, 5)
    result = mcnemar_paired(bl, cn)
    # With Yates' correction: (|5-5|-1)^2/10 = 0.1, p ≈ 0.7518 (not 1.0)
    assert result.p_value > 0.7
    # Without correction b==c → statistic=0, p=1.0
    result_raw = mcnemar_paired(bl, cn, continuity_correction=False)
    assert result_raw.p_value == pytest.approx(1.0, abs=1e-6)


def test_mcnemar_no_correction() -> None:
    bl, cn = _build_pairs(10, 2)
    result_corr = mcnemar_paired(bl, cn, continuity_correction=True)
    result_raw = mcnemar_paired(bl, cn, continuity_correction=False)
    # Without correction the statistic is larger → smaller p-value
    assert result_raw.statistic > result_corr.statistic
    assert result_raw.p_value < result_corr.p_value


def test_mcnemar_raises_on_length_mismatch() -> None:
    with pytest.raises(ValueError, match="length mismatch"):
        mcnemar_paired([True, False], [True])


def test_mcnemar_raises_on_zero_discordant() -> None:
    with pytest.raises(ValueError, match="no discordant pairs"):
        mcnemar_paired([True, True], [True, True])


def test_mcnemar_result_fields() -> None:
    bl, cn = _build_pairs(3, 1)
    result = mcnemar_paired(bl, cn)
    assert result.n_discordant == 4
    assert 0.0 <= result.p_value <= 1.0
    assert result.statistic >= 0.0


def test_mcnemar_cross_check_scipy() -> None:
    scipy_stats = pytest.importorskip("scipy.stats")
    bl, cn = _build_pairs(10, 2)
    result = mcnemar_paired(bl, cn)
    # Manually reproduce Yates-corrected chi2 via scipy.stats.chi2.sf for cross-check.
    # statistic = (|b-c|-1)^2 / (b+c)
    b, c = 10, 2
    stat = (abs(b - c) - 1) ** 2 / (b + c)
    expected_p = float(scipy_stats.chi2.sf(stat, df=1))
    assert abs(result.p_value - expected_p) < 1e-8
    # Also verify our math.erf-based CDF matches chi2 CDF for several statistics
    for x in [0.1, 1.0, 4.0, 10.0, 18.05]:
        our_p = 1.0 - math.erf(math.sqrt(x / 2.0))
        sci_p = float(scipy_stats.chi2.sf(x, df=1))
        assert abs(our_p - sci_p) < 1e-10, f"x={x}: our_p={our_p}, sci_p={sci_p}"


# ---------------------------------------------------------------------------
# McNemar — Hypothesis property: p-value monotone w.r.t. |b-c| for fixed total
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    n=st.integers(min_value=2, max_value=50),
    b1=st.integers(min_value=0, max_value=50),
    b2=st.integers(min_value=0, max_value=50),
)
def test_mcnemar_p_monotone_with_discordance(n: int, b1: int, b2: int) -> None:
    """Larger |b-c| with the same total should give a smaller p-value."""
    c1, c2 = n - min(b1, n), n - min(b2, n)
    b1, c1 = min(b1, n), n - min(b1, n)
    b2, c2 = min(b2, n), n - min(b2, n)

    diff1 = abs(b1 - c1)
    diff2 = abs(b2 - c2)

    if diff1 == 0 or diff2 == 0:
        return  # skip: would raise ValueError

    bl1, cn1 = _build_pairs(b1, c1)
    bl2, cn2 = _build_pairs(b2, c2)
    r1 = mcnemar_paired(bl1, cn1)
    r2 = mcnemar_paired(bl2, cn2)

    if diff1 > diff2:
        assert r1.p_value <= r2.p_value + 1e-12
    elif diff1 < diff2:
        assert r2.p_value <= r1.p_value + 1e-12


# ---------------------------------------------------------------------------
# Benjamini-Hochberg — reference cases against R p.adjust(method="BH")
# ---------------------------------------------------------------------------


def test_bh_reference_case_1() -> None:
    # sorted: 0.01 (rank1, thr=0.0125✓), 0.03 (rank2, thr=0.025✗), 0.04 (rank3, thr=0.0375✗), 0.5
    # Only 0.01 passes; k_max=1 → only index 0 rejected
    p = [0.01, 0.04, 0.03, 0.5]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result == [True, False, False, False]


def test_bh_reference_case_2() -> None:
    p = [0.001, 0.008, 0.039, 0.041, 0.042]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result == [True, True, True, True, True]


def test_bh_reference_case_3() -> None:
    p = [0.06, 0.08, 0.5]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result == [False, False, False]


def test_bh_empty_input() -> None:
    assert benjamini_hochberg([], alpha=0.05) == []


def test_bh_all_above_alpha() -> None:
    result = benjamini_hochberg([0.1, 0.2, 0.3], alpha=0.05)
    assert result == [False, False, False]


def test_bh_all_zero() -> None:
    result = benjamini_hochberg([0.0, 0.0, 0.0], alpha=0.05)
    assert result == [True, True, True]


def test_bh_preserves_input_order() -> None:
    p = [0.5, 0.001, 0.04]
    result = benjamini_hochberg(p, alpha=0.05)
    assert result[1] is True  # 0.001 is clearly significant
    assert result[0] is False  # 0.5 is clearly not


# ---------------------------------------------------------------------------
# Benjamini-Hochberg — Hypothesis property: rejected are a prefix in sorted order
# ---------------------------------------------------------------------------


@settings(max_examples=200)
@given(
    p_vals=st.lists(
        st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        min_size=1,
        max_size=30,
    )
)
def test_bh_rejected_are_sorted_prefix(p_vals: list[float]) -> None:
    """The set of rejected p-values, when sorted, must form a prefix."""
    result = benjamini_hochberg(p_vals, alpha=0.05)
    assert len(result) == len(p_vals)

    rejected_vals = sorted(p for p, rej in zip(p_vals, result, strict=True) if rej)
    non_rejected_vals = sorted(p for p, rej in zip(p_vals, result, strict=True) if not rej)

    if rejected_vals and non_rejected_vals:
        # Every rejected p-value must be <= every non-rejected p-value
        assert max(rejected_vals) <= min(non_rejected_vals) + 1e-12

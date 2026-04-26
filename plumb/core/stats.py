"""Pure statistical helpers: paired McNemar test + Benjamini-Hochberg FDR.

No I/O, no SciPy dependency — uses only stdlib math.
"""

from __future__ import annotations

import math
from collections.abc import Sequence

from plumb.core.entities import McNemarResult


def _chi2_cdf_df1(x: float) -> float:
    """Chi-squared CDF with df=1 via stdlib math.erf.

    df=1 chi-squared CDF = erf(sqrt(x/2))
    """
    if x <= 0:
        return 0.0
    return math.erf(math.sqrt(x / 2.0))


def mcnemar_paired(
    baseline_outcomes: Sequence[bool],
    candidate_outcomes: Sequence[bool],
    *,
    continuity_correction: bool = True,
) -> McNemarResult:
    """Paired McNemar test with optional Yates' continuity correction.

    Args:
        baseline_outcomes: Boolean pass/fail for each example under the baseline.
        candidate_outcomes: Boolean pass/fail for each example under the candidate.
        continuity_correction: Apply Yates' correction (default True).

    Returns:
        McNemarResult with b, c, chi-squared statistic, and two-sided p-value.

    Raises:
        ValueError: If sequences differ in length or have no discordant pairs.
    """
    if len(baseline_outcomes) != len(candidate_outcomes):
        raise ValueError(
            f"length mismatch: baseline={len(baseline_outcomes)}, "
            f"candidate={len(candidate_outcomes)}"
        )

    b = sum(
        1 for bl, cn in zip(baseline_outcomes, candidate_outcomes, strict=True) if bl and not cn
    )
    c = sum(
        1 for bl, cn in zip(baseline_outcomes, candidate_outcomes, strict=True) if not bl and cn
    )
    n_discordant = b + c
    if n_discordant < 1:
        raise ValueError("no discordant pairs — McNemar undefined")

    if continuity_correction:
        statistic = (abs(b - c) - 1) ** 2 / n_discordant
    else:
        statistic = (b - c) ** 2 / n_discordant

    p_value = 1.0 - _chi2_cdf_df1(statistic)

    return McNemarResult(
        b=b,
        c=c,
        statistic=statistic,
        p_value=p_value,
        n_discordant=n_discordant,
    )


def benjamini_hochberg(
    p_values: Sequence[float],
    *,
    alpha: float = 0.05,
) -> list[bool]:
    """Benjamini-Hochberg FDR correction.

    Args:
        p_values: Raw p-values in any order.
        alpha: False discovery rate threshold (default 0.05).

    Returns:
        A list of booleans, same length as p_values, True where null is rejected.
    """
    n = len(p_values)
    if n == 0:
        return []

    # Decorate-sort-undecorate: keep original index for output order.
    indexed = sorted(enumerate(p_values), key=lambda t: t[1])

    # Find largest k (1-indexed rank) where p_(k) <= (k/n) * alpha.
    k_max = 0
    for rank, (_, p) in enumerate(indexed, start=1):
        if p <= (rank / n) * alpha:
            k_max = rank

    rejected = [False] * n
    for rank in range(1, k_max + 1):
        orig_idx = indexed[rank - 1][0]
        rejected[orig_idx] = True

    return rejected

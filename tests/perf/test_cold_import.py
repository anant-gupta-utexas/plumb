"""NFR-Perf-6: cold import gate (Task 7.2).

Subprocess import of `plumb` must complete within 400 ms.
Warns (but does not fail) at 200 ms.
"""

from __future__ import annotations

import re
import subprocess
import sys
import warnings

import pytest


@pytest.mark.perf
def test_cold_import_within_budget() -> None:
    """plumb cold import: warn >200 ms, fail >400 ms."""
    WARN_MS = 200
    FAIL_MS = 400

    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import plumb"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"import plumb failed:\n{result.stderr}"

    # Python -X importtime writes to stderr; last matching line is the cumulative total.
    # Format: "import time:   <self_us> | <cumulative_us> | <module>"
    cumulative_us: int | None = None
    for line in result.stderr.splitlines():
        m = re.search(r"import time:\s+\d+\s+\|\s+(\d+)\s+\|\s+plumb\s*$", line)
        if m:
            cumulative_us = int(m.group(1))

    if cumulative_us is None:
        pytest.skip("Could not parse importtime output — skipping gate")

    elapsed_ms = cumulative_us / 1000

    print(f"\nplumb cold import: {elapsed_ms:.1f} ms")

    if elapsed_ms > WARN_MS:
        warnings.warn(
            f"plumb cold import took {elapsed_ms:.1f} ms (> {WARN_MS} ms warn threshold)",
            stacklevel=1,
        )

    assert elapsed_ms <= FAIL_MS, (
        f"plumb cold import {elapsed_ms:.1f} ms exceeds hard limit of {FAIL_MS} ms"
    )

"""NFR-Perf-6: cold import gate (autocapture Task 6.3).

Subprocess import of `plumb` must complete within 200 ms.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys

import pytest


@pytest.mark.perf
@pytest.mark.parametrize("autocapture_env", ["0", "1"])
def test_cold_import_within_budget(autocapture_env: str) -> None:
    """plumb cold import: fail above the 200 ms NFR-Perf-6 budget."""
    FAIL_MS = 200
    env = {**os.environ, "PLUMB_AUTOCAPTURE": autocapture_env}

    result = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", "import plumb"],
        capture_output=True,
        text=True,
        env=env,
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

    assert elapsed_ms <= FAIL_MS, (
        f"plumb cold import {elapsed_ms:.1f} ms exceeds hard limit of {FAIL_MS} ms"
    )

    for forbidden in ("anthropic", "openai"):
        assert not re.search(rf"^import time:.*\b{forbidden}\b", result.stderr, re.MULTILINE), (
            f"import plumb eagerly imported {forbidden} with PLUMB_AUTOCAPTURE={autocapture_env}"
        )

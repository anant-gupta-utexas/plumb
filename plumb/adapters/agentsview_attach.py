"""Stub for the agentsview_attach backfill adapter (implemented in a future slice)."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def backfill(path: Path, alias: str | None = None) -> dict[str, Any]:
    """Backfill plumb data from a legacy AgentsView SQLite database.

    Args:
        path: Filesystem path to the source SQLite database.
        alias: Optional display name for the attached database.

    Raises:
        NotImplementedError: always — implementation lands in the agentsview slice.
    """
    raise NotImplementedError("agentsview_attach not yet implemented")

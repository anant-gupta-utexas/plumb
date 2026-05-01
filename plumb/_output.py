"""Output formatting helpers for the plumb CLI."""

from __future__ import annotations

import csv
import json
import sys
from typing import Any


def is_tty() -> bool:
    """Return True when stdout is an interactive terminal."""
    return sys.stdout.isatty()


def print_json(rows: list[dict[str, Any]]) -> None:
    """Print rows as newline-delimited JSON (one object per line)."""
    for row in rows:
        print(json.dumps(row, default=str))


def print_csv(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Print rows as CSV with a header row matching ``columns``."""
    writer = csv.DictWriter(
        sys.stdout, fieldnames=columns, extrasaction="ignore", lineterminator="\n"
    )
    writer.writeheader()
    writer.writerows(rows)


def print_table(rows: list[dict[str, Any]], columns: list[str]) -> None:
    """Render rows as a rich table; falls back to pipe-separated text if rich is unavailable."""
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(show_header=True, header_style="bold")
        for col in columns:
            table.add_column(col)
        for row in rows:
            table.add_row(*[str(row.get(col, "")) for col in columns])
        Console().print(table)
    except ImportError:
        header = " | ".join(columns)
        print(header)
        print("-" * len(header))
        for row in rows:
            print(" | ".join(str(row.get(col, "")) for col in columns))


def format_output(rows: list[dict[str, Any]], columns: list[str], fmt: str) -> None:
    """Dispatch to the correct renderer; falls back to JSON when not a TTY.

    Args:
        rows: List of row dicts to render.
        columns: Ordered column names.
        fmt: One of ``table``, ``json``, or ``csv``.

    Raises:
        ValueError: if ``fmt`` is not one of the three supported values.
    """
    if fmt not in ("table", "json", "csv"):
        raise ValueError(f"Unsupported format {fmt!r}. Choose table, json, or csv.")
    if fmt == "table" and not is_tty():
        fmt = "json"
    if fmt == "table":
        print_table(rows, columns)
    elif fmt == "json":
        print_json(rows)
    else:
        print_csv(rows, columns)

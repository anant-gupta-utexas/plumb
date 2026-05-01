"""Unit tests for plumb._output format_output (T1.3)."""

from __future__ import annotations

import io
import json
import sys

import pytest

from plumb._output import format_output

_ROWS = [{"name": "alice", "score": 1}, {"name": "bob", "score": 2}]
_COLS = ["name", "score"]


def _capture(monkeypatch, fmt: str, tty: bool = False) -> str:
    monkeypatch.setattr("plumb._output.is_tty", lambda: tty)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    format_output(_ROWS, _COLS, fmt)
    return buf.getvalue()


def test_format_json(monkeypatch) -> None:
    out = _capture(monkeypatch, "json")
    lines = out.strip().splitlines()
    assert len(lines) == 2
    obj = json.loads(lines[0])
    assert obj["name"] == "alice"
    assert obj["score"] == 1


def test_format_csv_has_header(monkeypatch) -> None:
    out = _capture(monkeypatch, "csv")
    lines = out.strip().splitlines()
    assert lines[0] == "name,score"
    assert "alice" in lines[1]
    assert "bob" in lines[2]


def test_format_table_non_tty_falls_back_to_json(monkeypatch) -> None:
    out = _capture(monkeypatch, "table", tty=False)
    lines = out.strip().splitlines()
    assert len(lines) == 2
    json.loads(lines[0])  # must be valid JSON


def test_format_table_tty_renders_table(monkeypatch) -> None:
    # Rich table output should contain column names
    out = _capture(monkeypatch, "table", tty=True)
    assert "name" in out
    assert "alice" in out


def test_format_invalid_raises() -> None:
    with pytest.raises(ValueError, match="table, json, or csv"):
        format_output(_ROWS, _COLS, "xml")


def test_format_empty_rows_json(monkeypatch) -> None:
    monkeypatch.setattr("plumb._output.is_tty", lambda: False)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    format_output([], _COLS, "json")
    assert buf.getvalue() == ""


def test_format_empty_rows_csv(monkeypatch) -> None:
    monkeypatch.setattr("plumb._output.is_tty", lambda: False)
    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    format_output([], _COLS, "csv")
    lines = buf.getvalue().strip().splitlines()
    assert lines == ["name,score"]

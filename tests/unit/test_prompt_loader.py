"""Tests for plumb/_prompt_loader.py."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from plumb._prompt_loader import load_prompt
from plumb.core.errors import ValidationError

# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


def test_load_prompt_returns_text_and_sha8(tmp_path: Path) -> None:
    prompt_file = tmp_path / "routing_top1.md"
    prompt_file.write_text("Rate this output.", encoding="utf-8")

    text, sha8 = load_prompt("routing_top1", prompts_dir=tmp_path)

    assert text == "Rate this output."
    assert sha8 == hashlib.sha256(b"Rate this output.").hexdigest()[:8]
    assert len(sha8) == 8


def test_load_prompt_sha8_is_hex(tmp_path: Path) -> None:
    (tmp_path / "my_metric.md").write_text("hello", encoding="utf-8")
    _, sha8 = load_prompt("my_metric", prompts_dir=tmp_path)
    assert all(c in "0123456789abcdef" for c in sha8)


def test_load_prompt_accepts_underscores_in_name(tmp_path: Path) -> None:
    (tmp_path / "a_b_c.md").write_text("x", encoding="utf-8")
    text, _ = load_prompt("a_b_c", prompts_dir=tmp_path)
    assert text == "x"


def test_load_prompt_accepts_trailing_digits(tmp_path: Path) -> None:
    (tmp_path / "metric123.md").write_text("y", encoding="utf-8")
    text, _ = load_prompt("metric123", prompts_dir=tmp_path)
    assert text == "y"


def test_load_prompt_sha8_matches_sha256(tmp_path: Path) -> None:
    content = "Multi-line\nprompt\ntext\n"
    (tmp_path / "judge.md").write_text(content, encoding="utf-8")
    _, sha8 = load_prompt("judge", prompts_dir=tmp_path)
    expected = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
    assert sha8 == expected


# ---------------------------------------------------------------------------
# Validation errors
# ---------------------------------------------------------------------------


def test_empty_metric_name_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("", prompts_dir=tmp_path)


def test_uppercase_metric_name_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("MyMetric", prompts_dir=tmp_path)


def test_path_traversal_dotdot_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("../foo", prompts_dir=tmp_path)


def test_path_traversal_absolute_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("/etc/passwd", prompts_dir=tmp_path)


def test_path_traversal_slash_in_name_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("foo/bar", prompts_dir=tmp_path)


def test_metric_name_with_dot_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("foo.bar", prompts_dir=tmp_path)


def test_metric_name_starts_with_digit_raises(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        load_prompt("1metric", prompts_dir=tmp_path)


# ---------------------------------------------------------------------------
# FileNotFoundError
# ---------------------------------------------------------------------------


def test_missing_file_raises_file_not_found(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt("missing_metric", prompts_dir=tmp_path)
    assert "missing_metric" in str(exc_info.value)


def test_missing_file_error_contains_absolute_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError) as exc_info:
        load_prompt("absent", prompts_dir=tmp_path)
    error_msg = str(exc_info.value)
    assert Path(error_msg.split(": ", 1)[-1]).is_absolute() or str(tmp_path) in error_msg


# ---------------------------------------------------------------------------
# Default prompts_dir resolution (smoke test — does not hit filesystem)
# ---------------------------------------------------------------------------


def test_prompts_dir_override_used(tmp_path: Path) -> None:
    (tmp_path / "smoke.md").write_text("smoke", encoding="utf-8")
    text, _ = load_prompt("smoke", prompts_dir=tmp_path)
    assert text == "smoke"

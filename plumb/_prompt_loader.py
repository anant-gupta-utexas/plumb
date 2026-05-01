"""Load judge prompt files from the data directory.

Example usage::

    from plumb._prompt_loader import load_prompt
    text, sha8 = load_prompt("routing_top1")
    # text is the file contents; sha8 is the first 8 hex chars of sha256(text)
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from plumb.core.errors import ValidationError

_METRIC_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def load_prompt(metric_name: str, *, prompts_dir: Path | None = None) -> tuple[str, str]:
    """Load a judge prompt file and return ``(prompt_text, prompt_sha8)``.

    Resolution order: ``{prompts_dir}/{metric_name}.md``. When *prompts_dir*
    is ``None`` the default ``$PLUMB_DATA_DIR/judge_prompts/`` is used.

    ``prompt_sha8`` is the first 8 hex characters of ``sha256(prompt_text)``,
    encoded as UTF-8 before hashing.

    Args:
        metric_name: Lowercase alphanumeric identifier matching
            ``^[a-z][a-z0-9_]{0,63}$``. Path traversal characters (``/``,
            ``.``) are rejected by the pattern.
        prompts_dir: Override the prompt directory (useful in tests).

    Returns:
        A ``(prompt_text, sha8)`` tuple.

    Raises:
        ValidationError: ``metric_name`` is empty or does not match the
            allowed pattern.
        FileNotFoundError: The resolved prompt file does not exist. The
            exception message contains the absolute path.

    Example::

        text, sha8 = load_prompt("routing_top1")
        assert len(sha8) == 8
    """
    if not metric_name:
        raise ValidationError("metric_name must be non-empty")
    if not _METRIC_NAME_RE.match(metric_name):
        raise ValidationError(
            f"metric_name {metric_name!r} is invalid; must match ^[a-z][a-z0-9_]{{0,63}}$"
        )

    resolved_dir = _resolve_prompts_dir(prompts_dir)
    prompt_path = (resolved_dir / f"{metric_name}.md").resolve()

    if not prompt_path.exists():
        raise FileNotFoundError(f"Judge prompt file not found: {prompt_path}")

    text = prompt_path.read_text(encoding="utf-8")
    sha8 = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return text, sha8


def _resolve_prompts_dir(prompts_dir: Path | None) -> Path:
    if prompts_dir is not None:
        return prompts_dir
    from plumb.config import ensure_data_dir, get_settings

    return ensure_data_dir(get_settings()) / "judge_prompts"

"""Environment-driven configuration for plumb (PLUMB_* env vars)."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime settings sourced from PLUMB_* environment variables."""

    data_dir: Path = Path.home() / ".plumb"
    log_level: str = "WARNING"
    autocapture: bool = True

    model_config = {"env_prefix": "PLUMB_", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings instance (reads env vars once)."""
    return Settings()


def ensure_data_dir(settings: Settings | None = None) -> Path:
    """Resolve PLUMB_DATA_DIR; create with mode 0700 on first use; return absolute Path.

    Idempotent: if the directory already exists, its mode bits are not modified.
    Handles tilde expansion and symlink resolution.
    """
    if settings is None:
        settings = get_settings()

    path = Path(settings.data_dir).expanduser().resolve()

    if not path.exists():
        path.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(path, 0o700)

    return path

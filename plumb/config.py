"""Environment-driven configuration for plumb (PLUMB_* env vars)."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Runtime settings sourced from PLUMB_* environment variables."""

    data_dir: Path = Path.home() / ".plumb"
    log_level: str = "WARNING"
    autocapture: bool = False

    model_config = {"env_prefix": "PLUMB_", "case_sensitive": False}


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the cached Settings instance (reads env vars once)."""
    return Settings()

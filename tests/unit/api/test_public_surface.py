"""Public surface tests (Task 5.5 — AC-API-1)."""

from __future__ import annotations

import subprocess
import sys

import pytest

import plumb


class TestPublicSurface:
    def test_run_importable(self) -> None:
        from plumb import run  # noqa: F401

    def test_run_handle_importable(self) -> None:
        from plumb import RunHandle  # noqa: F401

    def test_all_defined(self) -> None:
        assert hasattr(plumb, "__all__")
        assert "run" in plumb.__all__
        assert "RunHandle" in plumb.__all__
        assert "autocapture_install" in plumb.__all__
        assert "autocapture_uninstall" in plumb.__all__
        assert "autocapture_is_installed" in plumb.__all__

    def test_version_literal(self) -> None:
        assert plumb.__version__ == "0.1.0"

    def test_run_handle_construct_guard(self) -> None:
        """AC-API-1: RunHandle() raises TypeError — not a user-constructible entry point."""
        with pytest.raises(TypeError, match="not user-constructible"):
            plumb.RunHandle()  # type: ignore[call-arg]

    def test_run_handle_none_builder_guard(self) -> None:
        with pytest.raises(TypeError):
            plumb.RunHandle(_builder=None)

    def test_only_run_is_public_entry_point(self) -> None:
        """AC-API-1: `run` is the only instrumentation entry point.

        RunHandle is explicitly allowed (public for type hints, guarded by __init__).
        All entity/error re-exports are type-annotation helpers only.
        """
        from plumb.api import run as api_run

        assert plumb.run is api_run
        assert callable(plumb.autocapture_install)
        assert callable(plumb.autocapture_uninstall)
        assert callable(plumb.autocapture_is_installed)

    def test_no_eager_heavy_imports(self) -> None:
        """Cold-import must not pull in heavy optional libraries."""
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import plumb; import sys; print('\\n'.join(sys.modules.keys()))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        loaded = result.stdout.splitlines()
        forbidden = {"anthropic", "openai", "httpx", "fastapi", "uvicorn", "typer"}
        for mod in loaded:
            root = mod.split(".")[0]
            assert root not in forbidden, f"plumb eagerly imported forbidden module: {root!r}"

    def test_sqlite3_not_eagerly_imported(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import plumb; import sys; print('\\n'.join(sys.modules.keys()))",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        loaded = set(result.stdout.splitlines())
        assert "sqlite3" not in loaded, "sqlite3 must not be eagerly imported"

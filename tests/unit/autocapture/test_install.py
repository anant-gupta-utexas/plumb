"""Unit tests for plumb.autocapture install/uninstall/is_installed (Task 1.3)."""

from __future__ import annotations

from unittest.mock import patch

import pytest

import plumb.autocapture as autocapture
import plumb.autocapture._state as state


@pytest.fixture(autouse=True)
def clean_registry():
    state._INSTALLED.clear()
    yield
    state._INSTALLED.clear()


class TestIsInstalled:
    def test_false_when_nothing_installed(self) -> None:
        assert autocapture.is_installed() is False

    def test_true_when_something_registered(self) -> None:
        from plumb.autocapture._state import _Patch

        state._INSTALLED["fake.Key"] = _Patch("fake", "Key", lambda: None)
        assert autocapture.is_installed() is True


class TestInstallNoSdks:
    def test_no_error_when_neither_sdk_installed(self) -> None:
        """With neither anthropic nor openai installed, install() does nothing without error."""
        with patch.dict("sys.modules", {"anthropic": None, "openai": None}):
            autocapture.install()
        assert not autocapture.is_installed()

    def test_idempotent_double_call(self) -> None:
        """Second call to install() when nothing is installable is a no-op."""
        with patch.dict("sys.modules", {"anthropic": None, "openai": None}):
            autocapture.install()
            autocapture.install()
        assert not autocapture.is_installed()


class TestUninstall:
    def test_uninstall_when_nothing_installed(self) -> None:
        """uninstall() with empty registry is a no-op."""
        autocapture.uninstall()
        assert not autocapture.is_installed()

    def test_install_uninstall_leaves_empty(self) -> None:
        """install() then uninstall() then is_installed() returns False."""
        # Manually populate registry as if install() had run
        import types

        from plumb.autocapture._state import _Patch

        # Create a fake module with a fake class method to restore
        fake_mod = types.ModuleType("fake_mod")
        fake_cls = type("FakeCls", (), {"create": lambda self: None})
        original_fn = fake_cls.create
        fake_mod.FakeCls = fake_cls
        import sys

        sys.modules["fake_mod"] = fake_mod

        state._INSTALLED["fake_mod.FakeCls.create"] = _Patch(
            target_module="fake_mod",
            target_qualname="FakeCls.create",
            original=original_fn,
        )
        assert autocapture.is_installed()

        autocapture.uninstall()
        assert not autocapture.is_installed()
        assert fake_cls.create is original_fn

        del sys.modules["fake_mod"]

    def test_uninstall_idempotent(self) -> None:
        autocapture.uninstall()
        autocapture.uninstall()
        assert not autocapture.is_installed()

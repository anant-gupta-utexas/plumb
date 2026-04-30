"""Unit tests for plumb.autocapture._state (Task 1.2)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

import pytest

import plumb.autocapture._state as state
from plumb.autocapture._state import _Patch, _is_registered, _register, _unregister


def _noop(*args: Any, **kwargs: Any) -> None:
    pass


def _make_patch(module: str = "some.module", qualname: str = "Cls.method") -> _Patch:
    return _Patch(target_module=module, target_qualname=qualname, original=_noop)


@pytest.fixture(autouse=True)
def clean_registry():
    """Reset _INSTALLED before and after every test."""
    state._INSTALLED.clear()
    yield
    state._INSTALLED.clear()


class TestPatchDataclass:
    def test_frozen(self) -> None:
        patch = _make_patch()
        with pytest.raises((AttributeError, TypeError)):
            patch.target_module = "other"  # type: ignore[misc]

    def test_fields(self) -> None:
        patch = _make_patch("mod", "Cls.fn")
        assert patch.target_module == "mod"
        assert patch.target_qualname == "Cls.fn"
        assert patch.original is _noop


class TestRegister:
    def test_single_registration(self) -> None:
        patch = _make_patch("a.b", "C.create")
        _register(patch)
        assert _is_registered("a.b.C.create")
        assert state._INSTALLED["a.b.C.create"] is patch

    def test_idempotent_same_key(self) -> None:
        patch1 = _make_patch("a.b", "C.create")
        patch2 = _Patch("a.b", "C.create", lambda: None)
        _register(patch1)
        _register(patch2)
        # First registration wins
        assert state._INSTALLED["a.b.C.create"] is patch1
        assert len(state._INSTALLED) == 1

    def test_distinct_keys(self) -> None:
        _register(_make_patch("a.b", "C.create"))
        _register(_make_patch("x.y", "D.method"))
        assert len(state._INSTALLED) == 2


class TestUnregister:
    def test_removes_existing(self) -> None:
        _register(_make_patch("a.b", "C.create"))
        _unregister("a.b.C.create")
        assert not _is_registered("a.b.C.create")

    def test_noop_on_missing(self) -> None:
        _unregister("nonexistent.Key")  # must not raise


class TestIsRegistered:
    def test_false_when_empty(self) -> None:
        assert not _is_registered("anything")

    def test_true_after_register(self) -> None:
        _register(_make_patch("m", "K.fn"))
        assert _is_registered("m.K.fn")

    def test_false_after_unregister(self) -> None:
        _register(_make_patch("m", "K.fn"))
        _unregister("m.K.fn")
        assert not _is_registered("m.K.fn")


class TestConcurrentRegister:
    def test_four_threads_distinct_keys(self) -> None:
        """Concurrent _register calls from 4 threads on distinct keys produce a 4-entry registry."""
        barrier = threading.Barrier(4)
        errors: list[Exception] = []

        def worker(idx: int) -> None:
            try:
                barrier.wait()
                with state._INSTALL_LOCK:
                    _register(_make_patch(f"mod{idx}", f"Cls{idx}.create"))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(state._INSTALLED) == 4

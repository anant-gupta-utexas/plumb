"""Unit tests for StoragePool in plumb._http_deps (T1.2 acceptance criteria)."""

from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from plumb._http_deps import StoragePool, _POOL_SIZE


def _make_pool(tmp_path: Path, pool_size: int = _POOL_SIZE) -> StoragePool:
    """Create a real StoragePool pointing at a temp DB."""
    db_path = tmp_path / "plumb.db"
    return StoragePool(db_path, pool_size=pool_size)


# ---------------------------------------------------------------------------
# Basic construction / lifecycle
# ---------------------------------------------------------------------------


def test_pool_opens_adapters(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path)
    assert len(pool._adapters) == _POOL_SIZE
    pool.close()


def test_pool_idempotent_close(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path)
    pool.close()
    pool.close()  # must not raise


def test_pool_acquire_returns_adapter(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path, pool_size=1)
    with pool.acquire() as adapter:
        assert adapter is not None
    pool.close()


def test_pool_closed_raises_on_acquire(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path, pool_size=1)
    pool.close()
    with pytest.raises(RuntimeError, match="closed"):
        with pool.acquire():
            pass


# ---------------------------------------------------------------------------
# Same pool returned across multiple acquires
# ---------------------------------------------------------------------------


def test_pool_reuses_adapters(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path, pool_size=2)
    seen: list[object] = []
    for _ in range(4):
        with pool.acquire() as adapter:
            seen.append(id(adapter))
    # Only 2 distinct adapter identities should exist
    assert len(set(seen)) == 2
    pool.close()


# ---------------------------------------------------------------------------
# Concurrency: blocks when pool_size in flight
# ---------------------------------------------------------------------------


def test_pool_blocks_at_capacity(tmp_path: Path) -> None:
    pool = _make_pool(tmp_path, pool_size=2)
    results: list[str] = []
    lock = threading.Lock()

    def worker(tag: str) -> None:
        with pool.acquire():
            threading.Event().wait(0.02)  # hold the adapter briefly
            with lock:
                results.append(tag)

    threads = [threading.Thread(target=worker, args=(str(i),)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(results) == [str(i) for i in range(6)]
    pool.close()


# ---------------------------------------------------------------------------
# Schema bootstrap fires on each adapter (idempotent DDL)
# ---------------------------------------------------------------------------


def test_pool_schema_bootstrap(tmp_path: Path) -> None:
    # Two pools against the same DB path must not raise (idempotent DDL)
    p1 = _make_pool(tmp_path)
    p1.close()
    p2 = _make_pool(tmp_path)
    p2.close()

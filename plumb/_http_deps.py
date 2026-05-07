"""Dependency injection for the plumb HTTP service: pool + lifespan.

``StoragePool`` holds a fixed number of ``SQLiteStorageAdapter`` instances and
manages concurrent access via a ``threading.Semaphore`` (routes are sync, so
asyncio semaphores are not required).
"""

from __future__ import annotations

import threading
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI, Request

from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
from plumb.config import ensure_data_dir, get_settings

if TYPE_CHECKING:
    pass

_POOL_SIZE = 4


class _RealClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class StoragePool:
    """Bounded pool of ``SQLiteStorageAdapter`` instances.

    Opens ``pool_size`` adapters at construction time; each ``acquire()``
    blocks until one is available and returns it under a context manager that
    automatically calls ``release()`` on exit.

    Attributes:
        _adapters: The fixed list of adapters in the pool.
        _semaphore: Counting semaphore that limits concurrent acquisitions.
        _idx: Round-robin index for adapter selection.
        _idx_lock: Mutex protecting ``_idx``.
        _closed: Whether ``close()`` has been called.
    """

    def __init__(self, db_path: Path, pool_size: int = _POOL_SIZE) -> None:
        """Open ``pool_size`` adapters against ``db_path``.

        Args:
            db_path: Path to the SQLite database file.
            pool_size: Number of adapter instances to maintain.
        """
        self._adapters: list[SQLiteStorageAdapter] = [
            SQLiteStorageAdapter(db_path, clock=_RealClock()) for _ in range(pool_size)
        ]
        self._semaphore = threading.Semaphore(pool_size)
        self._idx = 0
        self._idx_lock = threading.Lock()
        self._closed = False

    @contextmanager
    def acquire(self) -> Iterator[SQLiteStorageAdapter]:
        """Acquire an adapter, blocking until one is available.

        Yields:
            A ``SQLiteStorageAdapter`` for the caller's exclusive use.

        Raises:
            RuntimeError: If the pool has been closed.
        """
        if self._closed:
            raise RuntimeError("StoragePool is closed")
        self._semaphore.acquire()
        try:
            with self._idx_lock:
                adapter = self._adapters[self._idx % len(self._adapters)]
                self._idx += 1
            yield adapter
        finally:
            self._semaphore.release()

    def close(self) -> None:
        """Close all adapters in the pool. Idempotent.

        Adapters are closed even if some raise on ``close()``; all are
        attempted before any exception propagates.
        """
        if self._closed:
            return
        self._closed = True
        for adapter in self._adapters:
            adapter.close()


@asynccontextmanager
async def get_pool_lifespan(app: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan: open the pool at startup, close it at shutdown.

    Stores the pool on ``app.state.pool`` so route handlers can retrieve it
    via ``get_pool``.

    Args:
        app: The FastAPI application instance.

    Yields:
        Nothing — control returns to FastAPI between startup and shutdown.
    """
    settings = get_settings()
    db_path = ensure_data_dir(settings) / "plumb.db"
    pool = StoragePool(db_path)
    app.state.pool = pool
    try:
        yield
    finally:
        pool.close()


def get_pool(request: Request) -> StoragePool:
    """FastAPI dependency: return the app-scoped storage pool.

    Args:
        request: The incoming HTTP request (injected by FastAPI).

    Returns:
        The ``StoragePool`` stored on ``app.state``.
    """
    return request.app.state.pool  # type: ignore[no-any-return]

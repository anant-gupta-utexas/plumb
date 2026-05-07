"""E2E smoke test: start ``plumb serve`` in a subprocess and hit all endpoints.

Marked ``@pytest.mark.e2e`` — skipped by default unless run with
``pytest tests/http/e2e/`` or ``-m e2e``.
Skipped on Windows (signal handling differs).
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 5.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def _seed_db(db_path: Path) -> str:
    """Seed the DB with one run and return its run_id."""
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from plumb.core.entities import Example, ExampleSource, Run, RunKind, RunStatus

    class _C:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    run_id = "a" * 32
    task_id = "smoke.task"
    adapter = SQLiteStorageAdapter(db_path, clock=_C())
    run = Run(
        run_id=run_id,
        task_id=task_id,
        kind=RunKind.OFFLINE,
        status=RunStatus.SUCCESS,
        start_ts=datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC),
        end_ts=datetime(2026, 1, 1, 12, 0, 10, tzinfo=UTC),
    )
    adapter.write_run(run, [])
    ex = Example(
        example_id="b" * 32,
        task_id=task_id,
        inputs_hash="c" * 64,
        source=ExampleSource.SYNTHETIC,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    adapter.write_example(ex)
    adapter.close()
    return run_id


@pytest.mark.skipif(sys.platform == "win32", reason="signal handling differs on Windows")
def test_serve_smoke(tmp_path: Path) -> None:
    """Spawn plumb serve and hit all five endpoints."""
    try:
        import httpx
    except ImportError:
        pytest.skip("httpx not available")

    db_path = tmp_path / "plumb.db"
    run_id = _seed_db(db_path)
    port = _free_port()

    env = {**os.environ, "PLUMB_DATA_DIR": str(tmp_path)}
    proc = subprocess.Popen(
        [sys.executable, "-m", "plumb.cli", "serve", "--port", str(port)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    try:
        assert _wait_for_port("127.0.0.1", port, timeout=5.0), "Server did not start within 5s"

        base = f"http://127.0.0.1:{port}"
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(f"{base}/health")
            assert resp.status_code == 200
            assert resp.json()["status"] == "ok"

            resp = client.get(f"{base}/runs")
            assert resp.status_code == 200
            assert resp.json()["total"] >= 1

            resp = client.get(f"{base}/runs/{run_id}")
            assert resp.status_code == 200

            resp = client.get(f"{base}/examples")
            assert resp.status_code == 200

            resp = client.get(f"{base}/stats/task/smoke.task")
            assert resp.status_code == 200
    finally:
        proc.send_signal(signal.SIGTERM)
        try:
            proc.wait(timeout=5.0)
        except subprocess.TimeoutExpired:
            proc.kill()

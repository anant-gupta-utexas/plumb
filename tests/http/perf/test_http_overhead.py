"""Performance gate: NFR-Perf-7 budgets against a 10k-run DB.

Marked ``@pytest.mark.perf`` — only runs under ``pytest tests/http/perf/``.

Budget table (from plan §11.2):
  /health              p95 <  5 ms
  /runs?limit=100      p95 < 50 ms
  /runs/{id}           p95 < 30 ms
  /examples            p95 < 20 ms
  /stats/task/{id}     p95 < 200 ms
"""

from __future__ import annotations

import statistics
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.perf

_N_RUNS = 10_000
_REPS = 30

# Budget table from plan §11.2 (milliseconds)
_BUDGETS_MS = {
    "/health": 5,
    "/runs?limit=100": 50,
    "/runs/{run_id}": 30,
    "/examples": 20,
    "/stats/task/{task_id}": 200,
}


def _seed_perf_db(db_path: Path, n: int) -> tuple[str, str]:
    """Seed ``n`` runs and return (run_id, task_id)."""
    from plumb.adapters.storage_sqlite import SQLiteStorageAdapter
    from plumb.core.entities import Example, ExampleSource, Run, RunKind, RunStatus

    class _C:
        def now(self) -> datetime:
            return datetime(2026, 1, 1, tzinfo=UTC)

    adapter = SQLiteStorageAdapter(db_path, clock=_C())
    task_id = "perf.task"
    first_run_id = "a" * 32

    for i in range(n):
        hex_id = format(i, "032x")
        start = datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=i)
        end = start + timedelta(seconds=10)
        run = Run(
            run_id=hex_id,
            task_id=task_id,
            kind=RunKind.OFFLINE,
            status=RunStatus.SUCCESS,
            start_ts=start,
            end_ts=end,
        )
        adapter.write_run(run, [])

    # One example
    adapter.write_example(
        Example(
            example_id="b" * 32,
            task_id=task_id,
            inputs_hash="c" * 64,
            source=ExampleSource.SYNTHETIC,
            created_at=datetime(2026, 1, 1, tzinfo=UTC),
        )
    )
    adapter.close()
    return first_run_id, task_id


@pytest.fixture(scope="module")
def perf_client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    db_path = tmp_path_factory.mktemp("perf") / "plumb.db"
    run_id, task_id = _seed_perf_db(db_path, _N_RUNS)

    from plumb._http_deps import StoragePool
    from plumb.http import app

    pool = StoragePool(db_path, pool_size=1)
    app.state.pool = pool
    client = TestClient(app, raise_server_exceptions=True)
    yield client, run_id, task_id
    pool.close()


def _measure_p95(client: TestClient, url: str, reps: int) -> float:
    times = []
    for _ in range(reps):
        t0 = time.perf_counter()
        resp = client.get(url)
        times.append((time.perf_counter() - t0) * 1000)
        assert resp.status_code == 200
    times.sort()
    idx = max(0, int(0.95 * reps) - 1)
    return times[idx]


def test_health_p95(perf_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = perf_client
    p95 = _measure_p95(client, "/health", _REPS)
    assert p95 < _BUDGETS_MS["/health"], f"/health p95={p95:.1f}ms exceeds {_BUDGETS_MS['/health']}ms"


def test_runs_list_p95(perf_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = perf_client
    p95 = _measure_p95(client, "/runs?limit=100", _REPS)
    assert p95 < _BUDGETS_MS["/runs?limit=100"], f"/runs p95={p95:.1f}ms exceeds {_BUDGETS_MS['/runs?limit=100']}ms"


def test_run_detail_p95(perf_client) -> None:  # type: ignore[no-untyped-def]
    client, run_id, _ = perf_client
    p95 = _measure_p95(client, f"/runs/{run_id}", _REPS)
    assert p95 < _BUDGETS_MS["/runs/{run_id}"], f"/runs/{{id}} p95={p95:.1f}ms exceeds {_BUDGETS_MS['/runs/{run_id}']}ms"


def test_examples_p95(perf_client) -> None:  # type: ignore[no-untyped-def]
    client, _, _ = perf_client
    p95 = _measure_p95(client, "/examples", _REPS)
    assert p95 < _BUDGETS_MS["/examples"], f"/examples p95={p95:.1f}ms exceeds {_BUDGETS_MS['/examples']}ms"


def test_stats_p95(perf_client) -> None:  # type: ignore[no-untyped-def]
    client, _, task_id = perf_client
    p95 = _measure_p95(client, f"/stats/task/{task_id}", _REPS)
    assert p95 < _BUDGETS_MS["/stats/task/{task_id}"], (
        f"/stats p95={p95:.1f}ms exceeds {_BUDGETS_MS['/stats/task/{task_id}']}ms"
    )

"""Minimal FastAPI stub — full HTTP service implemented in a future slice."""

from fastapi import FastAPI

app = FastAPI(title="plumb")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness probe."""
    return {"status": "ok"}

"""Minimal FastAPI stub — full HTTP service implemented in a future slice."""

try:
    from fastapi import FastAPI
except ImportError as _e:
    raise ImportError(
        "plumb HTTP service requires 'fastapi' and 'uvicorn'. "
        "Install them with: pip install 'plumb[http]'"
    ) from _e

app = FastAPI(title="plumb")


@app.get("/health")
def health() -> dict[str, str]:
    """Return a simple liveness probe."""
    return {"status": "ok"}

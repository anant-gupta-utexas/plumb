from plumb.api import RunHandle, run
from plumb.core.entities import (
    Example,
    ExampleSource,
    JudgeResult,
    McNemarResult,
    Run,
    RunKind,
    RunStatus,
    Score,
    ScorerKind,
    Span,
    SpanKind,
    SpanStatus,
)
from plumb.core.errors import (
    BlobNotFoundError,
    JudgeError,
    PlumbError,
    StorageError,
    ValidationError,
)

__version__ = "0.1.0"  # hardcoded per context §6 item 1; switch to importlib.metadata at PyPI ship

__all__ = [
    "run",
    "RunHandle",  # public for type hints only; direct construction raises TypeError
    "RunKind",
    "RunStatus",
    "SpanKind",
    "SpanStatus",
    "ScorerKind",
    "ExampleSource",
    "Run",
    "Span",
    "Score",
    "Example",
    "JudgeResult",
    "McNemarResult",
    "PlumbError",
    "StorageError",
    "BlobNotFoundError",
    "ValidationError",
    "JudgeError",
    "__version__",
]

from plumb.api import RunHandle, run
from plumb.autocapture import (
    install as autocapture_install,
    is_installed as autocapture_is_installed,
    uninstall as autocapture_uninstall,
)
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

__version__ = "1.0.1"  # hardcoded per context §6 item 1; switch to importlib.metadata at PyPI ship

__all__ = [
    "run",
    "RunHandle",  # public for type hints only; direct construction raises TypeError
    "autocapture_install",
    "autocapture_uninstall",
    "autocapture_is_installed",
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

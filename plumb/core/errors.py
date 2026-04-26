"""Exception hierarchy for plumb. Never propagated past plumb/api.py per NFR-Rel-1."""


class PlumbError(Exception):
    """Base class for all plumb-internal errors."""


class StorageError(PlumbError):
    """Raised when a storage operation fails (read or write)."""


class BlobNotFoundError(PlumbError):
    """Raised when a blob cannot be found by its content hash."""


class ValidationError(PlumbError):
    """Raised when entity invariants or API argument constraints are violated."""


class JudgeError(PlumbError):
    """Raised when a judge adapter call fails."""

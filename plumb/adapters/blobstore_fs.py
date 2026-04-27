"""Content-addressed filesystem blob store (TRD §7.2, DATA-BLOB-1..5)."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from plumb.core.errors import BlobNotFoundError, ValidationError

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class FilesystemBlobStore:
    """Immutable, content-addressed store backed by the local filesystem.

    Layout: ``root/<hex[:2]>/<hex[2:]>``
    Mode bits: root=0700, fan-out subdirs=0700, blob files=0600.
    """

    def __init__(self, root: Path) -> None:
        self._root = root

    def put(self, content: bytes) -> str:
        """Write *content* and return its 64-char sha256 hex digest.

        Idempotent: putting the same content twice returns the same digest
        and leaves exactly one file on disk.
        """
        digest = hashlib.sha256(content).hexdigest()
        target = self._root / digest[:2] / digest[2:]

        # mkdir with mode=0700; explicit chmod defeats permissive umasks
        target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(target.parent.parent, 0o700)  # root
        os.chmod(target.parent, 0o700)          # fan-out subdir

        try:
            fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            return digest  # same hash ⇒ same content; already persisted

        try:
            os.write(fd, content)
            os.fsync(fd)
        finally:
            os.close(fd)

        return digest

    def get(self, sha256_hex: str) -> bytes:
        """Return the bytes stored under *sha256_hex*.

        Raises:
            ValidationError: if *sha256_hex* is not a 64-char lowercase hex string.
            BlobNotFoundError: if no blob is stored under that digest.
        """
        self._validate_hex(sha256_hex)
        target = self._root / sha256_hex[:2] / sha256_hex[2:]
        try:
            return target.read_bytes()
        except FileNotFoundError:
            raise BlobNotFoundError(sha256_hex) from None

    def exists(self, sha256_hex: str) -> bool:
        """Return True iff a blob with *sha256_hex* is stored."""
        self._validate_hex(sha256_hex)
        return (self._root / sha256_hex[:2] / sha256_hex[2:]).exists()

    @staticmethod
    def _validate_hex(sha256_hex: str) -> None:
        if not _HEX64.match(sha256_hex):
            raise ValidationError(
                f"sha256_hex must be a 64-char lowercase hex string, got {sha256_hex!r}"
            )

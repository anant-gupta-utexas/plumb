"""Tests for FilesystemBlobStore.put / .get / .exists (Task 2.1)."""

import hashlib

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from plumb.adapters.blobstore_fs import FilesystemBlobStore
from pathlib import Path
from plumb.core.errors import BlobNotFoundError, ValidationError


@pytest.fixture()
def store(tmp_path):
    return FilesystemBlobStore(tmp_path / "blobs")


def test_put_returns_sha256_hex(store) -> None:
    digest = store.put(b"hello world")
    expected = hashlib.sha256(b"hello world").hexdigest()
    assert digest == expected
    assert len(digest) == 64
    assert digest == digest.lower()


def test_put_creates_dir_on_first_use(tmp_path) -> None:
    root = tmp_path / "blobs"
    assert not root.exists()
    store = FilesystemBlobStore(root)
    store.put(b"data")
    assert root.exists()


def test_put_idempotent_same_digest(store) -> None:
    d1 = store.put(b"same content")
    d2 = store.put(b"same content")
    assert d1 == d2
    # only one file on disk
    digest = d1
    blob_path = store._root / digest[:2] / digest[2:]
    assert blob_path.exists()
    # only one file in the fan-out dir
    assert len(list((store._root / digest[:2]).iterdir())) == 1


def test_put_empty_bytes(store) -> None:
    digest = store.put(b"")
    expected = hashlib.sha256(b"").hexdigest()
    assert digest == expected
    assert store.get(digest) == b""


def test_get_returns_exact_bytes(store) -> None:
    content = b"\x00\xff\xab\xcd" * 256
    digest = store.put(content)
    assert store.get(digest) == content


def test_get_missing_raises_blob_not_found(store) -> None:
    missing = "a" * 64
    with pytest.raises(BlobNotFoundError, match=missing):
        store.get(missing)


def test_get_malformed_hex_raises_validation_error(store) -> None:
    with pytest.raises(ValidationError):
        store.get("not-a-valid-hex-string")


def test_get_wrong_length_raises_validation_error(store) -> None:
    with pytest.raises(ValidationError):
        store.get("ab" * 16)  # 32 chars, not 64


def test_exists_true_after_put(store) -> None:
    digest = store.put(b"exists check")
    assert store.exists(digest) is True


def test_exists_false_for_unknown(store) -> None:
    assert store.exists("b" * 64) is False


def test_exists_malformed_raises_validation_error(store) -> None:
    with pytest.raises(ValidationError):
        store.exists("ZZZZ")


@given(content=st.binary(min_size=0, max_size=1024))
@settings(max_examples=100)
def test_roundtrip_property(content: bytes) -> None:
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        store = FilesystemBlobStore(Path(d) / "blobs")
        digest = store.put(content)
        assert store.get(digest) == content

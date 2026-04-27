"""Mode-bit invariant tests for FilesystemBlobStore (Task 2.2)."""

import os
import stat

import pytest

from plumb.adapters.blobstore_fs import FilesystemBlobStore


@pytest.fixture()
def store(tmp_path):
    return FilesystemBlobStore(tmp_path / "blobs")


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes only")
def test_root_mode_after_put(store) -> None:
    store.put(b"mode check root")
    mode = stat.S_IMODE(os.stat(store._root).st_mode)
    assert mode == 0o700, f"root mode {mode:o} != 700"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes only")
def test_fanout_subdir_mode_after_put(store) -> None:
    digest = store.put(b"mode check subdir")
    subdir = store._root / digest[:2]
    mode = stat.S_IMODE(os.stat(subdir).st_mode)
    assert mode == 0o700, f"subdir mode {mode:o} != 700"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes only")
def test_blob_file_mode_after_put(store) -> None:
    digest = store.put(b"mode check file")
    blob = store._root / digest[:2] / digest[2:]
    mode = stat.S_IMODE(os.stat(blob).st_mode)
    assert mode == 0o600, f"blob mode {mode:o} != 600"


@pytest.mark.skipif(os.name == "nt", reason="POSIX modes only")
def test_mode_bits_survive_permissive_umask(tmp_path) -> None:
    old_umask = os.umask(0)
    try:
        store = FilesystemBlobStore(tmp_path / "blobs_umask0")
        digest = store.put(b"umask test")
        blob = store._root / digest[:2] / digest[2:]
        assert stat.S_IMODE(os.stat(store._root).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(store._root / digest[:2]).st_mode) == 0o700
        assert stat.S_IMODE(os.stat(blob).st_mode) == 0o600
    finally:
        os.umask(old_umask)

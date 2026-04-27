"""Concurrency / O_EXCL race tests for FilesystemBlobStore (Task 2.3)."""

import hashlib
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from plumb.adapters.blobstore_fs import FilesystemBlobStore

_CONTENT = b"concurrent put content"
_EXPECTED_DIGEST = hashlib.sha256(_CONTENT).hexdigest()


def test_concurrent_put_same_content(tmp_path) -> None:
    store = FilesystemBlobStore(tmp_path / "blobs")
    n_threads = 10

    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=n_threads) as pool:
        futures = [pool.submit(store.put, _CONTENT) for _ in range(n_threads)]
        digests = [f.result() for f in as_completed(futures)]
    elapsed = time.monotonic() - start

    assert elapsed < 1.0, f"concurrent puts took {elapsed:.2f}s > 1s"
    assert len(digests) == n_threads
    assert all(d == _EXPECTED_DIGEST for d in digests)

    blob_path = store._root / _EXPECTED_DIGEST[:2] / _EXPECTED_DIGEST[2:]
    assert blob_path.exists()
    # exactly one file in the fan-out dir
    assert len(list((store._root / _EXPECTED_DIGEST[:2]).iterdir())) == 1

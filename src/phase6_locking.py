"""Cross-process locking for Phase 6 aggregate files and run directories."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from filelock import FileLock, Timeout


@contextmanager
def exclusive_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 60.0,
) -> Iterator[None]:
    """Hold a cross-platform OS-backed file lock.

    ``filelock`` owns the release token internally and releases an abandoned
    OS lock when a process exits.  The lock file may remain on disk, but a
    later process cannot accidentally delete a live owner's lock.
    """

    if timeout_seconds < 0.0:
        raise ValueError("lock timeout must be nonnegative")
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = FileLock(str(path), timeout=timeout_seconds)
    try:
        with lock:
            yield
    except Timeout as exc:
        raise TimeoutError(f"timed out waiting for Phase 6 lock: {path}") from exc

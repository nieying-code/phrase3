"""Cross-process locking for Phase 6 aggregate registries."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock
from time import monotonic, sleep
from typing import Iterator

import psutil


_IN_PROCESS_LOCK = Lock()


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _remove_stale_lock(path: Path) -> bool:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        owner_pid = int(payload["pid"])
    except (OSError, ValueError, KeyError, json.JSONDecodeError):
        return False
    if psutil.pid_exists(owner_pid):
        return False
    try:
        path.unlink()
    except FileNotFoundError:
        pass
    return True


@contextmanager
def exclusive_file_lock(
    path: Path,
    *,
    timeout_seconds: float = 60.0,
    poll_seconds: float = 0.05,
) -> Iterator[None]:
    """Hold an exclusive inter-process lock implemented with O_EXCL."""

    if timeout_seconds <= 0.0:
        raise ValueError("lock timeout must be positive")
    acquired_in_process = _IN_PROCESS_LOCK.acquire(
        timeout=timeout_seconds
    )
    if not acquired_in_process:
        raise TimeoutError(
            f"timed out waiting for in-process Phase 6 lock: {path}"
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        deadline = monotonic() + timeout_seconds
        descriptor: int | None = None
        while descriptor is None:
            try:
                descriptor = os.open(
                    path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                )
            except FileExistsError:
                _remove_stale_lock(path)
                if monotonic() >= deadline:
                    raise TimeoutError(
                        f"timed out waiting for Phase 6 lock: {path}"
                    )
                sleep(poll_seconds)
        try:
            payload = json.dumps(
                {
                    "pid": os.getpid(),
                    "created_at_utc": _utc_now(),
                }
            ).encode("utf-8")
            os.write(descriptor, payload)
            os.close(descriptor)
            descriptor = None
            yield
        finally:
            if descriptor is not None:
                os.close(descriptor)
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    finally:
        _IN_PROCESS_LOCK.release()

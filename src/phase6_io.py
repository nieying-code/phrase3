"""Cross-platform atomic output helpers for Phase 6 artifacts."""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
from time import sleep
from typing import Any, Iterable, Mapping, Sequence


ATOMIC_REPLACE_MAX_ATTEMPTS = 20
ATOMIC_REPLACE_RETRY_SECONDS = 0.05


def read_lf_bytes(path: Path) -> bytes:
    """Read a controlled text file and reject non-LF worktree bytes."""

    payload = path.read_bytes()
    if b"\r" in payload:
        raise RuntimeError(f"controlled Phase 6 text is not LF-only: {path}")
    return payload


def sha256_lf_text_file(path: Path) -> str:
    return hashlib.sha256(read_lf_bytes(path)).hexdigest()


def _replace_with_retry(temporary: Path, destination: Path) -> None:
    for attempt in range(ATOMIC_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(temporary, destination)
            return
        except PermissionError:
            if attempt + 1 == ATOMIC_REPLACE_MAX_ATTEMPTS:
                raise
            sleep(ATOMIC_REPLACE_RETRY_SECONDS)


def atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    """Write deterministic LF JSON and tolerate short Windows file locks."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        _replace_with_retry(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def atomic_write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    """Write CSV atomically with an explicit cross-platform line ending."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open(
            "w",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            writer = csv.DictWriter(
                handle,
                fieldnames=fieldnames,
                lineterminator="\r\n",
            )
            writer.writeheader()
            writer.writerows(rows)
        _replace_with_retry(temporary, path)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass

"""Bounded status reader for Phase 6 E1/E2/E4/E5 family runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psutil


MAX_STATUS_BYTES = 64 * 1024
MAX_OUTPUT_BYTES = 16 * 1024


def _file_info(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "exists": path.exists(),
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


def _matching_processes(run_id: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    for process in psutil.process_iter(("pid", "name", "cmdline")):
        try:
            command = " ".join(process.info.get("cmdline") or ())
            if run_id not in command:
                continue
            matches.append(
                {
                    "pid": process.info["pid"],
                    "name": process.info.get("name"),
                    "cpu_percent": process.cpu_percent(interval=None),
                    "memory_mb": process.memory_info().rss / (1024.0**2),
                }
            )
        except (psutil.Error, OSError):
            continue
    return matches


def build_family_status(
    output_root: Path,
    run_id: str,
) -> dict[str, Any]:
    directory = (
        output_root
        / "experiments"
        / "phase6"
        / "family_runs"
        / run_id
    )
    status_path = directory / "status_summary.json"
    payload: dict[str, Any] = {}
    read_error: str | None = None
    if status_path.exists():
        size = status_path.stat().st_size
        if size > MAX_STATUS_BYTES:
            read_error = f"status summary exceeds {MAX_STATUS_BYTES} bytes"
        else:
            try:
                loaded = json.loads(status_path.read_text(encoding="utf-8"))
                payload = {
                    key: loaded.get(key)
                    for key in (
                        "run_id",
                        "family",
                        "execution_mode",
                        "status",
                        "planned_work_units",
                        "completed_work_units",
                        "failure",
                        "updated_at_utc",
                    )
                }
            except (OSError, json.JSONDecodeError) as exc:
                read_error = f"{type(exc).__name__}: {exc}"
    return {
        **payload,
        "run_id": payload.get("run_id") or run_id,
        "run_directory": str(directory.resolve()),
        "source": "status_summary" if payload else None,
        "status": payload.get("status") or "not_found",
        "processes": _matching_processes(run_id),
        "files": {
            name: _file_info(directory / filename)
            for name, filename in (
                ("status_summary", "status_summary.json"),
                ("result", "result.json"),
                ("checkpoint", "checkpoint.json"),
                ("runner_exception", "runner_exception.json"),
            )
        },
        "read_error": read_error,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    payload = build_family_status(args.output, args.run_id)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        payload["processes"] = payload["processes"][:4]
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise RuntimeError("bounded family status output exceeds 16 KiB")
    print(encoded)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

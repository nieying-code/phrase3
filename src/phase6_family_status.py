"""Bounded status reader for Phase 6 E1/E2/E4/E5 family runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import psutil

from .phase6_families import compact_failure


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
                    "run_id": loaded.get("run_id"),
                    "family": loaded.get("family"),
                    "execution_mode": loaded.get("execution_mode"),
                    "status": loaded.get("status"),
                    "planned_work_units": loaded.get(
                        "planned_work_units"
                    ),
                    "completed_work_units": loaded.get(
                        "completed_work_units"
                    ),
                    "failure": compact_failure(loaded.get("failure")),
                    "updated_at_utc": loaded.get("updated_at_utc"),
                }
            except (OSError, json.JSONDecodeError) as exc:
                read_error = f"{type(exc).__name__}: {exc}"[:1000]
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


def bounded_status_json(payload: dict[str, Any]) -> str:
    """Serialize status with deterministic reductions and no failure mode."""

    bounded = dict(payload)
    for name, limit in (
        ("run_id", 512),
        ("run_directory", 2000),
        ("source", 128),
        ("status", 128),
        ("read_error", 1000),
    ):
        if bounded.get(name) is not None:
            bounded[name] = str(bounded[name])[:limit]
    bounded["failure"] = compact_failure(bounded.get("failure"))
    bounded["processes"] = [
        {
            "pid": row.get("pid"),
            "name": str(row.get("name") or "")[:256],
            "cpu_percent": row.get("cpu_percent"),
            "memory_mb": row.get("memory_mb"),
        }
        for row in list(bounded.get("processes") or ())[:4]
    ]
    bounded["files"] = {
        str(name)[:128]: {
            "path": str(info.get("path") or "")[:1500],
            "exists": bool(info.get("exists")),
            "size_bytes": info.get("size_bytes"),
        }
        for name, info in dict(bounded.get("files") or {}).items()
    }
    encoded = json.dumps(bounded, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        return encoded
    bounded["processes"] = []
    for info in bounded["files"].values():
        info["path"] = Path(info["path"]).name[:256]
    encoded = json.dumps(bounded, ensure_ascii=False, indent=2)
    if len(encoded.encode("utf-8")) <= MAX_OUTPUT_BYTES:
        return encoded
    minimal = {
        "run_id": str(bounded.get("run_id") or "")[:512],
        "status": str(bounded.get("status") or "unreadable")[:128],
        "failure": compact_failure(bounded.get("failure"), message_limit=512),
        "read_error": (
            str(bounded.get("read_error") or "status output was reduced")[:512]
        ),
    }
    return json.dumps(minimal, ensure_ascii=False, indent=2)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    payload = build_family_status(args.output, args.run_id)
    print(bounded_status_json(payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

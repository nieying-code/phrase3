from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_development import validate_run_id


def _bounded(path: Path) -> dict:
    if not path.is_file():
        return {"status": "missing", "path": str(path)}
    if path.stat().st_size > 16 * 1024:
        return {
            "status": "invalid_bounded_status_artifact",
            "path": str(path),
            "failure": {
                "stage": "status_read",
                "status": "oversized_status_summary",
                "message": "status artifact exceeds the frozen 16 KiB bound",
                "exception_type": "BoundedStatusError",
            },
        }
    payload = json.loads(path.read_text(encoding="utf-8"))
    failure = payload.get("failure") or None
    if failure:
        failure = {
            key: failure.get(key)
            for key in ("stage", "status", "message", "exception_type")
        }
        if failure.get("message"):
            failure["message"] = str(failure["message"])[:1000]
    allowed = {
        "run_id", "case_id", "status", "current_stage", "completed_stage_count",
        "required_primary_run_count", "completed_primary_run_count",
        "formal_OOS_gate_passed", "next_decision",
        "algorithm_performance_authorized", "updated_at_utc",
    }
    return {key: value for key, value in payload.items() if key in allowed} | {
        "failure": failure
    }


def build_status(output_root: Path, *, run_id: str | None = None) -> dict:
    root = output_root.resolve()
    if run_id:
        validate_run_id(run_id)
        run_root = (root / "formal/OOS/runs").resolve()
        directory = (run_root / run_id).resolve()
        if directory.parent != run_root:
            raise ValueError("run path escapes controlled OOS root")
        return _bounded(directory / "status_summary.json")
    return _bounded(root / "formal/OOS/formal_OOS_progress.json")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read bounded M2 formal OOS status")
    parser.add_argument("--output-root", default="outputs/phase6_m2_formal_oos_v1_1")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    print(json.dumps(
        build_status(Path(args.output_root), run_id=args.run_id), ensure_ascii=False
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

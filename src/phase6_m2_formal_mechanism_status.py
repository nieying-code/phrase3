from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_development import validate_run_id


def _bounded(path: Path) -> dict:
    if not path.is_file() or path.stat().st_size > 16384:
        return {"status": "missing_or_oversized"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    if "required_primary_run_count" in payload:
        return {
            "status": payload.get("status"),
            "required_primary_run_count": payload.get("required_primary_run_count"),
            "completed_primary_run_count": payload.get("completed_primary_run_count"),
            "missing_case_count": len(payload.get("missing_case_ids") or []),
            "invalid_primary_run_ids": payload.get("invalid_primary_run_ids") or [],
            "failed_primary_run_ids": payload.get("failed_primary_run_ids") or [],
            "duplicate_case_ids": payload.get("duplicate_case_ids") or [],
            "diagnostic_run_ids": payload.get("diagnostic_run_ids") or [],
            "finalization_failure_run_ids": payload.get("finalization_failure_run_ids") or [],
            "common_random_numbers_verified": payload.get("common_random_numbers_verified"),
            "formal_mechanism_gate_passed": payload.get("formal_mechanism_gate_passed"),
            "next_decision": payload.get("next_decision"),
            "formal_OOS_authorized": payload.get("formal_OOS_authorized"),
            "updated_at_utc": payload.get("updated_at_utc"),
        }
    failure = payload.get("failure") or {}
    return {
        "run_id": payload.get("run_id"),
        "case_id": payload.get("case_id"),
        "status": payload.get("status"),
        "current_stage": payload.get("current_stage"),
        "completed_stage_count": payload.get("completed_stage_count"),
        "failure": {
            "stage": failure.get("stage"),
            "status": failure.get("status"),
            "message": str(failure.get("message") or "")[:1000],
            "exception_type": failure.get("exception_type"),
        } if failure else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bounded M2 formal mechanism status")
    parser.add_argument("--output", default="outputs/phase6_m2_formal_extension_v1_1")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = Path(args.output).resolve() / "formal/mechanism"
    if args.run_id:
        validate_run_id(args.run_id)
        payload = _bounded(root / "runs" / args.run_id / "status_summary.json")
    else:
        payload = _bounded(root / "formal_mechanism_progress.json")
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode("utf-8")) > 16384:
        raise RuntimeError("bounded formal mechanism status exceeds 16 KiB")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

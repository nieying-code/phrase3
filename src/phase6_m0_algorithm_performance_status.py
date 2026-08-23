from __future__ import annotations

import argparse
import json
from pathlib import Path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Bounded M0 E3 algorithm performance status")
    parser.add_argument("--output", default="outputs/phase6_m0_e3_algorithm_performance_v1_0")
    args = parser.parse_args(argv)
    path = Path(args.output).resolve() / "formal/primary/experiments/phase6/algorithm_performance_status_summary.json"
    if not path.is_file() or path.stat().st_size > 16384:
        payload = {"status": "missing_or_oversized"}
    else:
        source = json.loads(path.read_text(encoding="utf-8"))
        payload = {key: source.get(key) for key in (
            "status", "required_primary_run_count", "completed_primary_run_count",
            "required_budget_pair_count", "completed_budget_pair_count",
            "required_algorithm_execution_count", "completed_algorithm_execution_count",
            "missing_case_ids", "failed_primary_run_ids", "duplicate_case_ids",
            "invalid_primary_runs", "diagnostic_run_ids",
            "M0_E3_algorithm_performance_gate_passed", "updated_at_utc",
        )}
    text = json.dumps(payload, ensure_ascii=False)
    if len(text.encode("utf-8")) > 16384:
        raise RuntimeError("bounded status exceeds 16 KiB")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_formal_oos import run_formal_oos


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen M2 formal OOS batch")
    parser.add_argument("--config", default="configs/phase6_m2_formal_extension.yaml")
    parser.add_argument("--runner-config", default="configs/phase6_m2_formal_oos_runner.yaml")
    parser.add_argument("--approval", default="configs/phase6_m2_formal_oos_approval.yaml")
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--authorize-formal-oos-execution", action="store_true")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--parent-run-id")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    results = run_formal_oos(
        root=root,
        config_path=root / args.config,
        runner_path=root / args.runner_config,
        approval_path=root / args.approval,
        authorize=args.authorize_formal_oos_execution,
        run_id_prefix=args.run_id_prefix,
        case_ids=args.case_id,
        parent_run_id=args.parent_run_id,
    )
    progress = results[-1].get("formal_OOS_progress", {}) if results else {}
    complete = len(results) == 10 and all(row["status"] == "optimal" for row in results)
    print(json.dumps({
        "status": "optimal" if complete else "incomplete",
        "completed_run_count": len(results),
        "formal_OOS_gate_passed": progress.get("formal_OOS_gate_passed", False),
        "algorithm_performance_authorized": False,
    }))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())

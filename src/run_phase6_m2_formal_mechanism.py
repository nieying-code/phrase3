from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_formal_mechanism import run_formal_mechanism


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen M2 formal mechanism batch")
    parser.add_argument("--config", default="configs/phase6_m2_formal_extension.yaml")
    parser.add_argument("--runner-config", default="configs/phase6_m2_formal_mechanism_runner.yaml")
    parser.add_argument("--approval", default="configs/phase6_m2_formal_mechanism_approval.yaml")
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--authorize-formal-mechanism-execution", action="store_true")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--parent-run-id")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    rows = run_formal_mechanism(
        root=root,
        config_path=root / args.config,
        runner_path=root / args.runner_config,
        approval_path=root / args.approval,
        authorize=args.authorize_formal_mechanism_execution,
        run_id_prefix=args.run_id_prefix,
        case_ids=args.case_id,
        parent_run_id=args.parent_run_id,
    )
    progress = rows[-1].get("formal_progress", {}) if rows else {}
    complete = len(rows) == 50 and all(row["status"] == "optimal" for row in rows)
    print(json.dumps({
        "status": "optimal" if complete else "incomplete",
        "completed_run_count": len(rows),
        "formal_mechanism_gate_passed": progress.get("formal_mechanism_gate_passed", False),
        "formal_OOS_authorized": False,
    }))
    return 0 if complete else 2


if __name__ == "__main__":
    raise SystemExit(main())


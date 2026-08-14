from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_formal_extension import run_pilot


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen M2 formal-extension technical pilot")
    parser.add_argument("--config", default="configs/phase6_m2_formal_extension.yaml")
    parser.add_argument("--runner-config", default="configs/phase6_m2_formal_extension_runner.yaml")
    parser.add_argument("--approval", default="configs/phase6_m2_formal_extension_pilot_approval.yaml")
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--authorize-pilot-execution", action="store_true")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--parent-run-id")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    results = run_pilot(
        root=root, config_path=root / args.config,
        runner_path=root / args.runner_config, approval_path=root / args.approval,
        authorize=args.authorize_pilot_execution, run_id_prefix=args.run_id_prefix,
        case_ids=args.case_id, parent_run_id=args.parent_run_id,
    )
    projection = results[-1].get("projection", {}) if results else {}
    print(json.dumps({
        "status": "optimal" if len(results) == 16 and all(row["status"] == "optimal" for row in results) else "incomplete",
        "completed_run_count": len(results),
        "pilot_compute_gate_passed": projection.get("pilot_compute_gate_passed", False),
        "formal_extension_authorized": False,
    }))
    return 0 if len(results) == 16 and all(row["status"] == "optimal" for row in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m0_algorithm_performance import run_batch, run_diagnostic, validate_preflight


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run frozen M0 E3 algorithm performance batch")
    parser.add_argument("--runner-config", default="configs/phase6_m0_algorithm_performance_runner.yaml")
    parser.add_argument("--approval", default="configs/phase6_m0_algorithm_performance_approval_v1_0.yaml")
    parser.add_argument("--run-id-prefix")
    parser.add_argument("--case-id")
    parser.add_argument("--parent-run-id")
    parser.add_argument("--authorize-m0-e3-algorithm-performance", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    if args.preflight_only:
        context = validate_preflight(
            root=root,
            runner_path=root / args.runner_config,
            approval_path=root / args.approval,
            require_execution_branch=False,
        )
        print(json.dumps({
            "status": "preflight_passed",
            "primary_run_count": len(context["cases"]),
            "algorithm_execution_count": sum(case.algorithm_execution_count for case in context["cases"]),
            "fingerprints": context["fingerprints"],
            "scenario_generation_count": 0,
            "gurobi_call_count": 0,
        }))
        return 0
    if not args.run_id_prefix:
        parser.error("--run-id-prefix is required for execution")
    diagnostic_requested = bool(args.case_id or args.parent_run_id)
    if diagnostic_requested and not (args.case_id and args.parent_run_id):
        parser.error("diagnostic execution requires both --case-id and --parent-run-id")
    if diagnostic_requested:
        result = run_diagnostic(
            root=root,
            runner_path=root / args.runner_config,
            approval_path=root / args.approval,
            authorize=args.authorize_m0_e3_algorithm_performance,
            run_id_prefix=args.run_id_prefix,
            case_id=args.case_id,
            parent_run_id=args.parent_run_id,
        )
        print(json.dumps({"status": result.get("status"), "diagnostic": True}))
        return 0 if result.get("status") == "optimal" else 2
    projection = run_batch(
        root=root,
        runner_path=root / args.runner_config,
        approval_path=root / args.approval,
        authorize=args.authorize_m0_e3_algorithm_performance,
        run_id_prefix=args.run_id_prefix,
    )
    print(json.dumps({
        "status": projection["status"],
        "completed_primary_run_count": projection["completed_primary_run_count"],
        "completed_algorithm_execution_count": projection["completed_algorithm_execution_count"],
        "M0_E3_algorithm_performance_gate_passed": projection["M0_E3_algorithm_performance_gate_passed"],
    }))
    return 0 if projection["M0_E3_algorithm_performance_gate_passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())

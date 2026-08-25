"""CLI for the frozen 240-execution M2 algorithm-performance batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_algorithm_performance_formal import run_formal_batch, validate_preflight


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-config",default="configs/phase6_m2_algorithm_performance_formal_runner_v1_0.yaml")
    parser.add_argument("--approval",default="configs/phase6_m2_algorithm_performance_formal_approval_v1_0.yaml")
    parser.add_argument("--run-id-prefix")
    parser.add_argument("--authorize-m2-algorithm-performance-formal",action="store_true")
    parser.add_argument("--preflight-only",action="store_true")
    args=parser.parse_args(argv); root=Path.cwd().resolve()
    if args.preflight_only:
        context=validate_preflight(root,root/args.runner_config,root/args.approval,require_authorization=False)
        print(json.dumps({"status":"preflight_passed","primary_sequence_count":len(context["cases"]),"algorithm_execution_count":240,"scenario_generation_count":0,"gurobi_call_count":0}))
        return 0
    if not args.run_id_prefix: parser.error("--run-id-prefix is required")
    projection=run_formal_batch(root=root,runner_path=root/args.runner_config,approval_path=root/args.approval,authorize=args.authorize_m2_algorithm_performance_formal,run_id_prefix=args.run_id_prefix)
    print(json.dumps(projection,ensure_ascii=False,indent=2))
    return 0 if projection.get("formal_algorithm_performance_gate_passed") is True else 2


if __name__=="__main__": raise SystemExit(main())

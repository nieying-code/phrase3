from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_1_formal_test import run_formal_test


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run the frozen M2.1 formal test batch")
    parser.add_argument("--freeze", default="configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml")
    parser.add_argument("--runner-config", default="configs/phase6_m2_1_formal_test_runner.yaml")
    parser.add_argument("--approval", default="configs/phase6_m2_1_formal_test_approval.yaml")
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--authorize-formal-test-execution", action="store_true")
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--parent-run-id")
    args = parser.parse_args(argv); root = Path.cwd().resolve()
    results = run_formal_test(root=root, freeze_path=root/args.freeze, runner_path=root/args.runner_config, approval_path=root/args.approval, authorize=args.authorize_formal_test_execution, run_id_prefix=args.run_id_prefix, case_ids=args.case_id, parent_run_id=args.parent_run_id)
    projection = results[-1].get("formal_test_projection", {}) if results else {}
    complete = len(results)==10 and all(row["status"]=="optimal" for row in results) and projection.get("formal_test_gate_passed") is True
    print(json.dumps({"status":"optimal" if complete else "incomplete","completed_run_count":len(results),"formal_test_gate_passed":projection.get("formal_test_gate_passed",False),"formal_extension_authorized":False,"algorithm_performance_authorized":False}))
    return 0 if complete else 2


if __name__ == "__main__": raise SystemExit(main())

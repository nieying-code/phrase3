"""CLI for explicitly authorized M2 threshold-refinement development runs."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
from .phase6_m2_threshold_refinement import APPROVAL_PATH, run_matrix

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="configs/phase6_m2_threshold_refinement.yaml")
    parser.add_argument("--runner-config", default="configs/phase6_m2_threshold_refinement_runner.yaml")
    parser.add_argument("--approval", default=APPROVAL_PATH)
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--parent-run-id")
    parser.add_argument("--authorize-development-execution", action="store_true")
    args = parser.parse_args(argv); root = Path(__file__).resolve().parents[1]
    try:
        rows = run_matrix(root=root, config_path=root/args.config, runner_path=root/args.runner_config, approval_path=root/args.approval, authorize=args.authorize_development_execution, run_id_prefix=args.run_id_prefix, case_ids=args.case_id or None, parent_run_id=args.parent_run_id)
    except Exception as exc:
        print(json.dumps({"status":"preflight_or_runner_failure","exception_type":type(exc).__name__,"message":str(exc)[:1000]}, ensure_ascii=False), file=sys.stderr); return 2
    ok = bool(rows) and all(row["status"] == "optimal" for row in rows)
    print(json.dumps({"status":"optimal" if ok else "failed","completed_case_count":len(rows),"formal_extension_authorized":False}, ensure_ascii=False))
    return 0 if ok else 1

if __name__ == "__main__":
    raise SystemExit(main())

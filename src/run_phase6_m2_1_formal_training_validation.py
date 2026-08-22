"""CLI for the frozen M2.1 formal training/validation batch."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_1_formal_training_validation import (
    APPROVAL_PATH,
    CONFIG_PATH,
    RUNNER_CONFIG_PATH,
    run_formal_training_validation,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Run all ten M2.1 formal training/validation triplets")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--runner-config", default=RUNNER_CONFIG_PATH)
    parser.add_argument("--approval", default=APPROVAL_PATH)
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--case-id", action="append")
    parser.add_argument("--parent-run-id")
    parser.add_argument("--authorize-formal-training-validation-execution", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        results = run_formal_training_validation(
            root=root, config_path=root / args.config,
            runner_path=root / args.runner_config, approval_path=root / args.approval,
            authorize=args.authorize_formal_training_validation_execution,
            run_id_prefix=args.run_id_prefix, case_ids=args.case_id,
            parent_run_id=args.parent_run_id,
        )
        gate = bool(results and results[-1].get("projection", {}).get("formal_training_validation_gate_passed"))
        ok = len(results) == 10 and all(row["status"] == "optimal" for row in results) and gate
        print(json.dumps({
            "status": "optimal" if ok else "failed",
            "completed_primary_run_count": len(results),
            "formal_training_validation_gate_passed": gate,
            "selected_plan_freeze_authorized": False,
            "formal_test_authorized": False,
        }, sort_keys=True))
        return 0 if ok else 1
    except KeyboardInterrupt:
        print(json.dumps({"status": "interrupted", "formal_test_authorized": False}, sort_keys=True))
        return 130
    except Exception as exc:
        print(json.dumps({
            "status": "runner_exception", "message": f"{type(exc).__name__}: {exc}"[:1000],
            "formal_test_authorized": False,
        }, sort_keys=True))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

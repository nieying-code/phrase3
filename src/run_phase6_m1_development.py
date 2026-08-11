"""CLI for explicitly authorized Phase 6 M1 development execution."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from .phase6_m1_development import (
    M1_DEVELOPMENT_APPROVAL,
    run_development_matrix,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default="configs/phase6_m1_procurement_cap.yaml",
    )
    parser.add_argument(
        "--runner-config",
        default="configs/phase6_m1_runner.yaml",
    )
    parser.add_argument("--approval", default=M1_DEVELOPMENT_APPROVAL)
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--parent-run-id")
    parser.add_argument(
        "--authorize-development-execution",
        action="store_true",
        help="Required in addition to the frozen matrix status.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        results = run_development_matrix(
            project_root=root,
            config_path=root / args.config,
            runner_config_path=root / args.runner_config,
            approval_path=root / args.approval,
            authorize_development_execution=(
                args.authorize_development_execution
            ),
            run_id_prefix=args.run_id_prefix,
            case_ids=args.case_id or None,
            parent_run_id=args.parent_run_id,
        )
    except Exception as exc:
        print(
            json.dumps(
                {
                    "status": "preflight_or_runner_failure",
                    "exception_type": type(exc).__name__,
                    "message": str(exc)[:1000],
                    "development_execution_may_have_started": bool(
                        args.authorize_development_execution
                    ),
                },
                ensure_ascii=False,
            ),
            file=sys.stderr,
        )
        return 2
    print(
        json.dumps(
            {
                "status": (
                    "optimal"
                    if results and all(row["status"] == "optimal" for row in results)
                    else "failed"
                ),
                "completed_case_count": len(results),
                "run_ids": [row["run_id"] for row in results],
                "formal_extension_authorized": False,
            },
            ensure_ascii=False,
        )
    )
    return 0 if results and all(row["status"] == "optimal" for row in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())

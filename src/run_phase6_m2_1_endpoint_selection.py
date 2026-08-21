"""Design-stage CLI guard for the frozen M2.1 endpoint-selection protocol."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_1_endpoint_selection import (
    APPROVAL_PATH,
    CONFIG_PATH,
    RUNNER_PATH,
    M21ExecutionNotAuthorized,
    validate_design_only_preflight,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate the non-executable M2.1 design")
    parser.add_argument("--config", default=CONFIG_PATH)
    parser.add_argument("--runner-config", default=RUNNER_PATH)
    parser.add_argument("--approval", default=APPROVAL_PATH)
    parser.add_argument("--authorize-pilot-execution", action="store_true")
    parser.add_argument("--authorize-formal-execution", action="store_true")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    try:
        validate_design_only_preflight(
            root=root,
            config_path=root / args.config,
            runner_path=root / args.runner_config,
            approval_path=root / args.approval,
            authorize_pilot=args.authorize_pilot_execution,
            authorize_formal=args.authorize_formal_execution,
        )
    except M21ExecutionNotAuthorized as exc:
        print(json.dumps({
            "status": "execution_not_authorized",
            "message": str(exc),
            "scenario_generation_count": 0,
            "gurobi_call_count": 0,
        }, sort_keys=True))
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI for the frozen M2 algorithm-performance technical pilot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_algorithm_performance import run_pilot_batch


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner-config", type=Path, default=Path("configs/phase6_m2_algorithm_performance_runner_v1_1.yaml"))
    parser.add_argument("--approval", type=Path, default=Path("configs/phase6_m2_algorithm_performance_pilot_approval_v1_1.yaml"))
    parser.add_argument("--run-id-prefix", required=True)
    parser.add_argument("--authorize-m2-algorithm-performance-pilot", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    projection = run_pilot_batch(
        root=root, runner_path=(root / args.runner_config).resolve(),
        approval_path=(root / args.approval).resolve(),
        authorize=args.authorize_m2_algorithm_performance_pilot,
        run_id_prefix=args.run_id_prefix,
    )
    print(json.dumps(projection, ensure_ascii=False, indent=2))
    if projection.get("pilot_compute_gate_passed") is not True:
        raise SystemExit(2)


if __name__ == "__main__":
    main()

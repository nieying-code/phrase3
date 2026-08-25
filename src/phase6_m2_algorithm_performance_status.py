"""Bounded status reader for M2 algorithm-performance evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_algorithm_performance import read_status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, default=Path("outputs/phase6_m2_algorithm_performance_v1_1"))
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if args.run_id:
        if any(token in args.run_id for token in ("/", "\\", "..")):
            raise SystemExit("unsafe run ID")
        path = args.output_root / "pilot" / "runs" / args.run_id / "status_summary.json"
    else:
        path = args.output_root / "pilot" / "status_summary.json"
    print(json.dumps(read_status(path), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

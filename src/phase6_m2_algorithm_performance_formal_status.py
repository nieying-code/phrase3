from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_algorithm_performance_formal import read_status


def main() -> None:
    parser=argparse.ArgumentParser(description="Bounded M2 formal algorithm-performance status reader")
    parser.add_argument("--output-root",type=Path,default=Path("outputs/phase6_m2_algorithm_performance_formal_v1_1"))
    args=parser.parse_args()
    print(json.dumps(read_status(args.output_root/"formal/primary/status_summary.json"),ensure_ascii=False,indent=2))


if __name__=="__main__": main()

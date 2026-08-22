from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_1_formal_test import OUTPUT_ROOT, SUBDIRECTORY, _load_json
from .phase6_m2_development import validate_run_id


def main(argv=None) -> int:
    parser=argparse.ArgumentParser(description="Read compact M2.1 formal-test status")
    parser.add_argument("--output-root",default=OUTPUT_ROOT); parser.add_argument("--run-id"); args=parser.parse_args(argv)
    root=Path(args.output_root).resolve(); path=root/SUBDIRECTORY/"formal_test_projection.json"
    if args.run_id:
        validate_run_id(args.run_id); path=root/SUBDIRECTORY/"runs"/args.run_id/"status_summary.json"
    if not path.is_file(): print(json.dumps({"status":"missing","path":str(path)})); return 2
    if path.stat().st_size>16*1024: raise RuntimeError("status artifact exceeds 16 KiB")
    print(json.dumps(_load_json(path))); return 0


if __name__ == "__main__": raise SystemExit(main())

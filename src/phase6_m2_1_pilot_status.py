"""Bounded status reader for M2.1 pilot runs; never parses large result/checkpoint files."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_1_pilot import OUTPUT_ROOT, validate_run_id


MAX_BYTES = 16 * 1024


def read_status(root: Path, run_id: str) -> dict:
    validate_run_id(run_id)
    controlled = (root / OUTPUT_ROOT / "pilot/runs").resolve()
    path = (controlled / run_id / "status_summary.json").resolve()
    if path.parent.parent != controlled or not path.is_file():
        raise FileNotFoundError(f"M2.1 status not found: {run_id}")
    if path.stat().st_size > MAX_BYTES:
        raise ValueError("M2.1 status_summary.json exceeds 16 KiB")
    payload = json.loads(path.read_text(encoding="utf-8"))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("bounded M2.1 status output exceeds 16 KiB")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read a bounded M2.1 pilot status summary")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args(argv)
    print(json.dumps(read_status(Path.cwd().resolve(), args.run_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

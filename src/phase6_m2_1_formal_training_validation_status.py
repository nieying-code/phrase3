"""Bounded status reader for M2.1 formal training/validation runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .phase6_m2_development import validate_run_id


OUTPUT_ROOT = "outputs/phase6_m2_1_formal_training_validation_v1_0"
MAX_BYTES = 16384


def read_status(root: Path, run_id: str | None = None) -> dict:
    base = root / OUTPUT_ROOT / "training_validation"
    if run_id is None:
        path = base / "projection.json"
    else:
        validate_run_id(run_id)
        runs = (base / "runs").resolve()
        directory = (runs / run_id).resolve()
        if directory.parent != runs:
            raise ValueError("status run_id escapes controlled output root")
        path = directory / "status_summary.json"
    raw = path.read_bytes()
    if len(raw) > MAX_BYTES:
        raise ValueError("bounded M2.1 formal status exceeds 16 KiB")
    payload = json.loads(raw.decode("utf-8"))
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ValueError("bounded M2.1 formal status output exceeds 16 KiB")
    return payload


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Read bounded M2.1 formal status")
    parser.add_argument("--root", default=".")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    print(json.dumps(read_status(Path(args.root).resolve(), args.run_id), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

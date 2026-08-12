"""Bounded status reader for M2 development runs; never parses large results."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Sequence

from .phase6_m2_development import resolve_run_directory


MAX_STATUS_BYTES = 16 * 1024


def read_status(output_root: Path, run_id: str | None) -> dict[str, Any]:
    base = output_root / "development"
    if run_id is None:
        path = base / "development_activation_projection.json"
        kind = "projection"
    else:
        path = resolve_run_directory(output_root, run_id) / "status_summary.json"
        kind = "status_summary"
    if not path.is_file():
        return {"status": "not_found", "source": str(path)}
    if path.stat().st_size > MAX_STATUS_BYTES:
        raise RuntimeError(f"bounded M2 status file exceeds 16 KiB: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {"source_kind": kind, "source": str(path), "payload": payload}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="outputs/phase6_m2_supply_disruption_v1_1")
    parser.add_argument("--run-id")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    print(json.dumps(read_status(root / args.output_root, args.run_id), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

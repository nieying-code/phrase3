"""Bounded status reader; never loads large M2C2 results."""
from __future__ import annotations
import argparse, json
from pathlib import Path
from .phase6_m2c2_confirmation import OUTPUT_ROOT, _run_directory

MAX_BYTES = 16 * 1024
def read_status(output_root: Path, run_id: str | None):
    path = output_root / "confirmation/confirmation_projection.json" if run_id is None else _run_directory(output_root, run_id) / "status_summary.json"
    if not path.is_file(): return {"status":"not_found","source":str(path)}
    if path.stat().st_size > MAX_BYTES: raise RuntimeError("bounded status exceeds 16 KiB")
    return {"source":str(path),"payload":json.loads(path.read_text(encoding="utf-8"))}
def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--output-root",default=OUTPUT_ROOT); p.add_argument("--run-id"); a=p.parse_args(argv)
    root=Path(__file__).resolve().parents[1]; print(json.dumps(read_status(root/a.output_root,a.run_id),ensure_ascii=False)); return 0
if __name__ == "__main__": raise SystemExit(main())

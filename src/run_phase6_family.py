"""Command-line entry point for Phase 6 E1/E2/E4/E5 family runs."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .phase6_families import _atomic_write_json
from .phase6_family_runner import run_family_sequence


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_preflight_failure(
    output_root: Path,
    *,
    run_id: str,
    family: str,
    execution_mode: str,
    exc: Exception,
) -> None:
    directory = (
        output_root
        / "experiments"
        / "phase6"
        / "family_runs"
        / run_id
    )
    failure = {
        "stage": "runner_preflight",
        "status": "runner_exception",
        "message": f"{type(exc).__name__}: {exc}"[:1000],
    }
    _atomic_write_json(
        directory / "runner_exception.json",
        {
            "run_id": run_id,
            "family": family,
            "execution_mode": execution_mode,
            "status": "runner_exception",
            "failure": failure,
            "updated_at_utc": _utc_now(),
        },
    )
    _atomic_write_json(
        directory / "status_summary.json",
        {
            "run_id": run_id,
            "family": family,
            "execution_mode": execution_mode,
            "status": "runner_exception",
            "planned_work_units": 0,
            "completed_work_units": 0,
            "failure": failure,
            "updated_at_utc": _utc_now(),
        },
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a checkpointed Phase 6 experiment family",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=Path("configs/phase6_experiment_matrix.yaml"),
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/phase6_family_runner.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument(
        "--family",
        choices=("E1", "E2", "E4", "E5"),
        required=True,
    )
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=("development", "pilot", "formal"),
        required=True,
    )
    parser.add_argument("--tier")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--parent-run-id")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_family_sequence(
            matrix_path=args.matrix,
            family_config_path=args.config,
            output_root=args.output,
            family=args.family,
            seed=args.seed,
            execution_mode=args.mode,
            run_id=args.run_id,
            tier_id=args.tier,
            parent_run_id=args.parent_run_id,
        )
    except Exception as exc:
        _write_preflight_failure(
            args.output,
            run_id=args.run_id,
            family=args.family,
            execution_mode=args.mode,
            exc=exc,
        )
        print(
            json.dumps(
                {
                    "run_id": args.run_id,
                    "family": args.family,
                    "status": "runner_exception",
                    "message": f"{type(exc).__name__}: {exc}",
                },
                ensure_ascii=False,
            )
        )
        return 1
    summary: dict[str, Any] = {
        "run_id": result["run_id"],
        "family": result["family"],
        "status": result["status"],
        "planned_work_units": result["planned_work_units"],
        "completed_work_units": result["completed_work_units"],
        "projection_status": result.get("projection_status"),
        "formal_execution_authorized": result.get(
            "formal_execution_authorized"
        ),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if result["status"] == "optimal" else 1


if __name__ == "__main__":
    raise SystemExit(main())

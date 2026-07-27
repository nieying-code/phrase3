"""Run or resume one Phase 6 development, pilot, or formal sequence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from typing import Any

from .phase6_runner import load_phase6_runner_config, run_phase6_sequence


def _default_run_id(mode: str, tier: str, seed: int) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{mode}_{tier}_{seed}_{timestamp}"


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def run(
    *,
    config_path: Path,
    output_root: Path,
    tier_id: str,
    seed: int,
    execution_mode: str,
    run_id: str,
    resume: bool = False,
    parent_run_id: str | None = None,
) -> dict[str, Any]:
    """Execute one guarded Phase 6 sequence and retain runner exceptions."""

    stage = "runner_config_load"
    try:
        config = load_phase6_runner_config(config_path)
        matrix_path = (
            config_path.resolve().parent.parent / str(config["matrix_path"])
        ).resolve()
        stage = "phase6_sequence"
        return run_phase6_sequence(
            matrix_path=matrix_path,
            runner_config_path=config_path,
            output_root=output_root,
            tier_id=tier_id,
            seed=seed,
            execution_mode=execution_mode,
            run_id=run_id,
            resume=resume,
            parent_run_id=parent_run_id,
        )
    except Exception as exc:
        checkpoint_path = (
            output_root.resolve()
            / "experiments"
            / "phase6"
            / "runs"
            / run_id
            / "checkpoint.json"
        )
        completed_budget_count = 0
        checkpoint_status = None
        if checkpoint_path.exists():
            try:
                checkpoint = json.loads(
                    checkpoint_path.read_text(encoding="utf-8")
                )
                completed_budget_count = len(
                    checkpoint.get("comparisons", ())
                )
                checkpoint_status = checkpoint.get("status")
            except Exception:
                checkpoint_status = "unreadable"
        payload = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "status": "runner_exception",
            "execution_mode": execution_mode,
            "tier_id": tier_id,
            "seed": seed,
            "completed_budget_count": completed_budget_count,
            "checkpoint_status": checkpoint_status,
            "checkpoint_path": str(checkpoint_path),
            "failure": {
                "stage": stage,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        }
        diagnostic = (
            output_root.resolve()
            / "experiments"
            / "phase6"
            / "runs"
            / run_id
            / "runner_exception.json"
        )
        _atomic_write_json(diagnostic, payload)
        return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/phase6_runner.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    parser.add_argument("--tier", required=True)
    parser.add_argument("--seed", type=int, required=True)
    parser.add_argument(
        "--mode",
        choices=("development", "pilot", "formal"),
        required=True,
    )
    parser.add_argument("--run-id")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--parent-run-id",
        help="Failed terminal run that this diagnostic retry investigates",
    )
    args = parser.parse_args()
    run_id = args.run_id or _default_run_id(args.mode, args.tier, args.seed)
    result = run(
        config_path=args.config,
        output_root=args.output,
        tier_id=args.tier,
        seed=args.seed,
        execution_mode=args.mode,
        run_id=run_id,
        resume=args.resume,
        parent_run_id=args.parent_run_id,
    )
    print(
        json.dumps(
            {
                "run_id": result["run_id"],
                "status": result["status"],
                "tier_id": result["tier_id"],
                "seed": result["seed"],
                "completed_budget_count": result.get(
                    "completed_budget_count",
                    0,
                ),
                "failure": result.get("failure"),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result["status"] != "optimal":
        raise SystemExit(f"phase 6 run failed: {result['status']}")


if __name__ == "__main__":
    main()

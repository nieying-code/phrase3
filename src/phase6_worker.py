"""Subprocess worker for one Phase 6 algorithm-budget solve."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from time import perf_counter
from typing import Any

from .ccg import run_standard_ccg, select_initial_scenarios
from .phase6_protocol import generate_phase6_data, load_phase6_matrix
from .spw_ccg import ScenarioPoolState, build_warm_initial_scenarios


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _state_from_dict(payload: dict[str, Any] | None) -> ScenarioPoolState | None:
    if payload is None:
        return None
    return ScenarioPoolState(
        budget=float(payload["budget"]),
        final_scenario_set=tuple(
            str(value) for value in payload["final_scenario_set"]
        ),
        active_scenarios=tuple(
            str(value) for value in payload["active_scenarios"]
        ),
        historical_adversarial_scenarios=tuple(
            str(value)
            for value in payload["historical_adversarial_scenarios"]
        ),
    )


def execute_worker_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute one cold or warm C&CG solve and retain diagnostic state."""

    started = perf_counter()
    stage = "request_validation"
    mode = str(request["algorithm"])
    if mode not in {"cold", "warm"}:
        raise ValueError("algorithm must be cold or warm")
    matrix_path = Path(request["matrix_path"])
    try:
        stage = "matrix_load"
        matrix = load_phase6_matrix(matrix_path)
        stage = "data_generation"
        generated = generate_phase6_data(
            matrix,
            matrix_path=matrix_path,
            tier_id=str(request["tier_id"]),
            seed=int(request["seed"]),
            budget=float(request["budget"]),
        )
        stage = "initial_pool"
        pool_started = perf_counter()
        if mode == "cold":
            initial = select_initial_scenarios(generated.data)
        else:
            initial = build_warm_initial_scenarios(
                generated.data,
                _state_from_dict(request.get("previous_state")),
            )
        pool_seconds = perf_counter() - pool_started

        stage = "ccg"
        solver = request["solver"]
        algorithm = request["ccg"]
        result = run_standard_ccg(
            generated.data,
            initial_scenarios=initial,
            absolute_tolerance=float(algorithm["absolute_tolerance"]),
            relative_tolerance=float(algorithm["relative_tolerance"]),
            max_iterations=int(algorithm["max_iterations"]),
            solver_preference=tuple(
                str(value) for value in solver["preference"]
            ),
            time_limit_seconds=float(solver["call_time_limit_seconds"]),
            solver_threads=int(solver["threads"]),
            feasibility_tolerance=float(solver["feasibility_tolerance"]),
            optimality_tolerance=float(solver["optimality_tolerance"]),
            tee=bool(solver.get("tee", False)),
        )
        return {
            "status": (
                "optimal"
                if result.converged and result.termination_status == "optimal"
                else result.termination_status
            ),
            "algorithm": mode,
            "tier_id": generated.tier.id,
            "seed": generated.seed,
            "budget": generated.budget,
            "budget_factor": generated.budget_factor,
            "reference_budget": generated.reference_budget,
            "generator_protocol_id": generated.generator_protocol_id,
            "scenario_count": len(generated.data.scenarios),
            "initial_scenarios": list(initial),
            "pool_build_seconds": pool_seconds,
            "worker_wall_seconds": perf_counter() - started,
            "ccg_result": result.as_dict(),
            "failure": None,
        }
    except Exception as exc:
        return {
            "status": "worker_exception",
            "algorithm": mode,
            "tier_id": request.get("tier_id"),
            "seed": request.get("seed"),
            "budget": request.get("budget"),
            "budget_factor": None,
            "reference_budget": None,
            "generator_protocol_id": None,
            "scenario_count": None,
            "initial_scenarios": [],
            "pool_build_seconds": None,
            "worker_wall_seconds": perf_counter() - started,
            "ccg_result": None,
            "failure": {
                "stage": stage,
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads(args.request.read_text(encoding="utf-8"))
    payload = execute_worker_request(request)
    _atomic_write_json(args.result, payload)
    if payload["status"] != "optimal":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

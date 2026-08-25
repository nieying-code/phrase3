"""Isolated worker for one frozen M2 algorithm-performance solve."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from .ccg import select_initial_scenarios
from .phase6_io import atomic_write_json
from .phase6_m2 import (
    run_m2_standard_ccg,
    solve_m2_endogenous_extensive,
)
from .phase6_m2_formal_extension import (
    _confirmation_config,
    _formal_matrix,
    _native_failure_status,
    _science_config_for_formal,
    _validate_formal_baseline_before_generation,
)
from .phase6_m2c2_confirmation import (
    apply_m2c2_supply_disruption,
    reconstruct_frozen_demand_latent,
)
from .phase6_protocol import generate_phase6_data, load_phase6_matrix
from .spw_ccg import ScenarioPoolState, build_warm_initial_scenarios


def _canonical_sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _state(payload: dict[str, Any] | None) -> ScenarioPoolState | None:
    if payload is None:
        return None
    return ScenarioPoolState(
        budget=float(payload["budget"]),
        final_scenario_set=tuple(payload["final_scenario_set"]),
        active_scenarios=tuple(payload["active_scenarios"]),
        historical_adversarial_scenarios=tuple(
            payload["historical_adversarial_scenarios"]
        ),
    )


def _formal_like(design: dict[str, Any]) -> dict[str, Any]:
    betas = design["budget_sequence"]["betas"]
    budgets = design["budget_sequence"]["budgets"]
    return {
        "scientific_model": design["scientific_model"],
        "profiles": design["profiles"],
        "mechanism_experiment": {
            "primary_track": {"beta": betas[0], "budget": budgets[0]},
            "secondary_track": {"beta": betas[1], "budget": budgets[1]},
        },
    }


def _generated(request: dict[str, Any]):
    root = Path(request["project_root"])
    matrix_path = Path(request["matrix_path"])
    design = yaml.safe_load(Path(request["design_path"]).read_text(encoding="utf-8"))
    matrix = load_phase6_matrix(matrix_path)
    formal = _formal_like(design)
    confirmation = _confirmation_config(root)
    frozen, reference, budget, capacity = _validate_formal_baseline_before_generation(
        matrix, formal, confirmation, beta=float(request["beta"]),
        scenario_count=int(request["scenario_count"]),
    )
    base = generate_phase6_data(
        frozen, matrix_path=matrix_path, tier_id="M2F2",
        seed=int(request["seed"]), budget=budget,
    )
    if any(
        not math.isclose(float(actual), float(expected), rel_tol=0.0, abs_tol=1.0e-9)
        for actual, expected in zip(base.data.storage_capacity, capacity, strict=True)
    ):
        raise ValueError("generated storage capacity differs from frozen M2AP2 baseline")
    latent = reconstruct_frozen_demand_latent(frozen, base)
    config = _science_config_for_formal(root, formal)
    from .phase6_m2 import resolve_supply_disruption_profile
    profile = resolve_supply_disruption_profile(config, str(request["profile_id"]))
    generated = apply_m2c2_supply_disruption(
        base,
        profile=profile,
        demand_latent=latent,
        item_vulnerability_multiplier={"relief_food_1": 0.8, "relief_food_2": 1.2},
    )
    return generated, reference, profile


def execute_worker_request(request: dict[str, Any]) -> dict[str, Any]:
    """Execute exactly one EF, cold C&CG, or SPW-C&CG repetition."""
    started = perf_counter()
    stage = "request_validation"
    algorithm = str(request["algorithm"])
    if algorithm not in {"extensive", "cold", "warm"}:
        raise ValueError("algorithm must be extensive, cold, or warm")
    try:
        stage = "scenario_generation"
        generated, reference, profile = _generated(request)
        data = generated.data
        solver = request["solver"]
        ccg = request["ccg"]
        common = {
            "solver_preference": tuple(solver["preference"]),
            "time_limit_seconds": float(solver["call_time_limit_seconds"]),
            "solver_threads": int(solver["threads"]),
            "feasibility_tolerance": float(solver["feasibility_tolerance"]),
            "optimality_tolerance": float(solver["optimality_tolerance"]),
            "tee": False,
        }
        pool_seconds = 0.0
        initial: tuple[str, ...] = ()
        if algorithm == "extensive":
            stage = "complete_extensive_model"
            solution = solve_m2_endogenous_extensive(
                data,
                consistency_tolerance=float(
                    request["objective_consistency"]["absolute_tolerance"]
                ),
                **common,
            )
            status = str(_native_failure_status(solution))
            objective = solution.objective
            evidence = solution.as_dict()
        else:
            stage = "initial_scenario_pool"
            pool_started = perf_counter()
            initial = (
                select_initial_scenarios(data)
                if algorithm == "cold"
                else build_warm_initial_scenarios(data, _state(request.get("previous_state")))
            )
            pool_seconds = perf_counter() - pool_started
            stage = "standard_ccg"
            solution = run_m2_standard_ccg(
                data,
                initial_scenarios=initial,
                absolute_tolerance=float(ccg["absolute_tolerance"]),
                relative_tolerance=float(ccg["relative_tolerance"]),
                max_iterations=int(ccg["max_iterations"]),
                **common,
            )
            visible_status = (
                "optimal" if solution.converged and solution.termination_status == "optimal"
                else str(solution.termination_status)
            )
            native_status = str(_native_failure_status(solution))
            status = native_status if native_status in {"time_limit", "master_time_limit"} else visible_status
            objective = solution.objective
            evidence = solution.as_dict()
        components = dict(generated.component_set_sha256)
        components["scenario_order_sha256"] = _canonical_sha(list(data.scenarios))
        previous_state = request.get("previous_state")
        transferred = []
        if previous_state is not None:
            reusable = set(previous_state["active_scenarios"]) | set(
                previous_state["historical_adversarial_scenarios"]
            )
            transferred = [name for name in initial if name in reusable]
        active_or_worst: list[str] = []
        if algorithm in {"cold", "warm"}:
            costs = evidence["exact_scenario_costs"]
            worst_cost = max(float(value) for value in costs.values())
            active = {
                name for name, value in costs.items()
                if worst_cost - float(value) <= float(ccg["active_scenario_tolerance"])
            }
            worst = evidence.get("worst_scenario")
            active_or_worst = [
                name for name in transferred if name in active or name == worst
            ]
        return {
            "status": status,
            "algorithm": algorithm,
            "seed": int(request["seed"]),
            "profile_id": str(request["profile_id"]),
            "beta": float(request["beta"]),
            "budget": float(data.budget),
            "reference_budget": float(reference),
            "scenario_count": len(data.scenarios),
            "joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
            "component_set_sha256": components,
            "initial_scenarios": list(initial),
            "initial_scenario_pool_size": len(initial),
            "transfer_source_state_sha256": (
                None if previous_state is None else _canonical_sha(previous_state)
            ),
            "transfer_source_budget": (
                None if previous_state is None else float(previous_state["budget"])
            ),
            "transferred_exact_scenarios": transferred,
            "transferred_exact_scenario_count": len(transferred),
            "transferred_scenario_reuse_rate": (
                0.0 if previous_state is None or not initial
                else len(transferred) / len(initial)
            ),
            "transferred_scenarios_becoming_active_or_worst": active_or_worst,
            "transferred_scenarios_becoming_active_or_worst_count": len(active_or_worst),
            "pool_build_seconds": pool_seconds,
            "objective": None if objective is None else float(objective),
            "scientific_result": evidence,
            "ccg_result": evidence if algorithm in {"cold", "warm"} else None,
            "worker_wall_seconds": perf_counter() - started,
            "solver_status": status,
            "failure": None,
        }
    except Exception as exc:
        return {
            "status": "worker_exception",
            "algorithm": algorithm,
            "seed": request.get("seed"),
            "profile_id": request.get("profile_id"),
            "beta": request.get("beta"),
            "worker_wall_seconds": perf_counter() - started,
            "solver_status": None,
            "failure": {
                "stage": stage,
                "exception_type": type(exc).__name__,
                "message": str(exc)[:4096],
            },
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    payload = execute_worker_request(json.loads(args.request.read_text(encoding="utf-8")))
    atomic_write_json(args.result, payload)
    if payload["status"] != "optimal":
        raise SystemExit(2)


if __name__ == "__main__":
    main()

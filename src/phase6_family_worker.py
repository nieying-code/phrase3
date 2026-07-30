"""Isolated worker for one Phase 6 E1, E2, E4, or E5 plan."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

from .ccg import run_standard_ccg
from .evaluation import evaluate_first_stage
from .extensive_model import solve_endogenous_extensive
from .inventory_model import (
    build_deterministic_model,
    build_fixed_reserve_model,
    solve_model,
)
from .phase6_families import (
    POLICY_RATIOS,
    _atomic_write_json,
    aggregate_oos_evaluation,
    apply_sensitivity_overrides,
    generate_oos_data,
)
from .phase6_protocol import generate_phase6_data, load_phase6_matrix


def _solver_kwargs(
    solver: Mapping[str, Any],
    *,
    time_limit_seconds: float,
) -> dict[str, Any]:
    return {
        "solver_preference": tuple(
            str(value) for value in solver["preference"]
        ),
        "time_limit_seconds": float(time_limit_seconds),
        "solver_threads": int(solver["threads"]),
        "feasibility_tolerance": float(solver["feasibility_tolerance"]),
        "optimality_tolerance": float(solver["optimality_tolerance"]),
        "tee": bool(solver.get("tee", False)),
    }


def _evaluation_summary(evaluation: Any) -> dict[str, Any]:
    return {
        "status": evaluation.status,
        "regular_cost": evaluation.regular_cost,
        "robust_objective": evaluation.robust_objective,
        "worst_scenario": evaluation.worst_scenario,
        "worst_recourse_cost": evaluation.worst_recourse_cost,
        "optimal_scenario_count": sum(
            result.status == "optimal"
            for result in evaluation.scenario_results.values()
        ),
        "infeasible_scenario_count": len(
            evaluation.infeasible_scenarios
        ),
        "solver_failure_count": len(evaluation.failed_scenarios),
        "runtime_seconds": evaluation.runtime_seconds,
    }


def _generate_training(
    request: Mapping[str, Any],
    *,
    matrix: Mapping[str, Any] | None = None,
) -> Any:
    plan = request["plan"]
    matrix_path = Path(request["matrix_path"])
    resolved = (
        load_phase6_matrix(matrix_path) if matrix is None else matrix
    )
    return generate_phase6_data(
        resolved,
        matrix_path=matrix_path,
        tier_id=str(plan["tier_id"]),
        seed=int(plan["training_seed"]),
        budget=float(plan["budget"]),
    )


def _run_e1(request: Mapping[str, Any]) -> dict[str, Any]:
    plan = request["plan"]
    matrix = load_phase6_matrix(request["matrix_path"])
    generated = _generate_training(request, matrix=matrix)
    progress_path = (
        Path(request["progress_path"])
        if request.get("progress_path")
        else None
    )
    if progress_path is not None:
        _atomic_write_json(
            progress_path,
            {
                "status": "running",
                "stage": "extensive",
                "plan_id": plan["plan_id"],
                "iteration": 0,
                "iteration_log": [],
            },
        )
    solver = _solver_kwargs(
        request["solver"],
        time_limit_seconds=generated.tier.solver_call_seconds,
    )
    extensive = solve_endogenous_extensive(
        generated.data,
        consistency_tolerance=float(
            matrix["exactness_gates"]["extensive_vs_standard_ccg"][
                "objective_absolute_tolerance"
            ]
        ),
        **solver,
    )
    if extensive.status != "optimal" or extensive.objective is None:
        return {
            "status": extensive.status,
            "failure": {
                "stage": "e1_extensive",
                "message": "full extensive model did not solve consistently",
            },
        }
    algorithm = request["ccg"]
    if progress_path is not None:
        _atomic_write_json(
            progress_path,
            {
                "status": "running",
                "stage": "standard_ccg",
                "plan_id": plan["plan_id"],
                "iteration": 0,
                "iteration_log": [],
                "extensive_objective": extensive.objective,
            },
        )

    def write_progress(progress: dict[str, Any]) -> None:
        if progress_path is None:
            return
        _atomic_write_json(
            progress_path,
            {
                **progress,
                "stage": "standard_ccg",
                "plan_id": plan["plan_id"],
                "extensive_objective": extensive.objective,
            },
        )

    ccg = run_standard_ccg(
        generated.data,
        absolute_tolerance=float(algorithm["absolute_tolerance"]),
        relative_tolerance=float(algorithm["relative_tolerance"]),
        max_iterations=int(algorithm["max_iterations"]),
        progress_callback=write_progress,
        **solver,
    )
    if (
        not ccg.converged
        or ccg.termination_status != "optimal"
        or ccg.objective is None
    ):
        return {
            "status": ccg.termination_status,
            "failure": {
                "stage": "e1_standard_ccg",
                "message": "standard C&CG did not converge optimally",
            },
        }
    absolute = float(
        matrix["exactness_gates"]["extensive_vs_standard_ccg"][
            "objective_absolute_tolerance"
        ]
    )
    relative = float(
        matrix["exactness_gates"]["extensive_vs_standard_ccg"][
            "objective_relative_tolerance"
        ]
    )
    difference = abs(float(extensive.objective) - float(ccg.objective))
    limit = absolute + relative * max(
        1.0,
        abs(float(extensive.objective)),
        abs(float(ccg.objective)),
    )
    if difference > limit:
        return {
            "status": "objective_mismatch",
            "failure": {
                "stage": "e1_exactness_gate",
                "message": (
                    f"extensive/CCG objective difference {difference} "
                    f"exceeds {limit}"
                ),
            },
        }
    extensive_evaluation = extensive.evaluation
    ccg_evaluation = ccg.incumbent_evaluation
    if (
        extensive_evaluation is None
        or extensive_evaluation.status != "optimal"
        or ccg_evaluation is None
        or ccg_evaluation.status != "optimal"
    ):
        return {
            "status": "exact_recourse_failure",
            "failure": {
                "stage": "e1_exact_recourse",
                "message": "at least one exact all-scenario evaluation failed",
            },
        }
    payload = {
        "status": "optimal",
        "plan_id": plan["plan_id"],
        "tier_id": generated.tier.id,
        "training_seed": generated.seed,
        "budget": generated.budget,
        "extensive_objective": extensive.objective,
        "standard_ccg_objective": ccg.objective,
        "objective_difference": difference,
        "objective_tolerance": limit,
        "extensive_reserve": extensive.reserve,
        "standard_ccg_reserve": ccg.reserve,
        "standard_ccg_iterations": ccg.iterations,
        "standard_ccg_final_scenario_count": len(
            ccg.final_scenario_set
        ),
        "extensive_exact_evaluation": _evaluation_summary(
            extensive_evaluation
        ),
        "standard_ccg_exact_evaluation": _evaluation_summary(
            ccg_evaluation
        ),
        "solver": ccg.solver,
    }
    if progress_path is not None:
        _atomic_write_json(
            progress_path,
            {
                "status": "completed",
                "stage": "complete",
                "plan_id": plan["plan_id"],
                "iteration": ccg.iterations,
                "lower_bound": ccg.lower_bound,
                "upper_bound": ccg.upper_bound,
                "gap": ccg.gap,
                "current_scenario_set": list(ccg.final_scenario_set),
                "worst_scenario": ccg.worst_scenario,
                "iteration_log": [
                    row.as_dict() for row in ccg.iteration_log
                ],
                "extensive_objective": extensive.objective,
                "standard_ccg_objective": ccg.objective,
            },
        )
    return payload


def _solve_policy(
    request: Mapping[str, Any],
    generated: Any,
) -> tuple[dict[str, Any], float, float, Any, str]:
    plan = request["plan"]
    policy = str(plan["policy"])
    solver = _solver_kwargs(
        request["solver"],
        time_limit_seconds=generated.tier.solver_call_seconds,
    )
    if policy == "deterministic_mean":
        native = solve_model(
            build_deterministic_model(generated.data),
            **solver,
        )
        regular_purchase = native.regular_purchase
        reserve = native.reserve
        native_objective = native.objective
        native_model = native.model_name
        evaluation = None
    elif policy in POLICY_RATIOS:
        native = solve_model(
            build_fixed_reserve_model(
                generated.data,
                POLICY_RATIOS[policy],
            ),
            **solver,
        )
        regular_purchase = native.regular_purchase
        reserve = native.reserve
        native_objective = native.objective
        native_model = native.model_name
        evaluation = None
    elif policy == "endogenous_reserve":
        extensive = solve_endogenous_extensive(
            generated.data,
            consistency_tolerance=1.0e-5,
            **solver,
        )
        if extensive.status != "optimal":
            raise RuntimeError(
                f"endogenous extensive model status={extensive.status}"
            )
        regular_purchase = extensive.master.regular_purchase
        reserve = float(extensive.reserve)
        native_objective = float(extensive.master.objective)
        native_model = "EndogenousReserveExtensiveModel"
        evaluation = extensive.evaluation
    else:
        raise ValueError(f"unsupported policy: {policy}")
    if evaluation is None:
        evaluation = evaluate_first_stage(
            generated.data,
            regular_purchase,
            reserve,
            **solver,
        )
    if evaluation.status != "optimal" or evaluation.robust_objective is None:
        raise RuntimeError(
            f"exact training evaluation status={evaluation.status}"
        )
    return (
        regular_purchase,
        reserve,
        native_objective,
        evaluation,
        native_model,
    )


def _run_e2(request: Mapping[str, Any]) -> dict[str, Any]:
    plan = request["plan"]
    generated = _generate_training(request)
    (
        regular_purchase,
        reserve,
        native_objective,
        evaluation,
        native_model,
    ) = _solve_policy(request, generated)
    return {
        "status": "optimal",
        "plan_id": plan["plan_id"],
        "family": "E2",
        "tier_id": generated.tier.id,
        "training_seed": generated.seed,
        "budget_index": plan["budget_index"],
        "budget": generated.budget,
        "policy": plan["policy"],
        "native_model": native_model,
        "native_objective": native_objective,
        "robust_objective": evaluation.robust_objective,
        "reserve": reserve,
        "reserve_ratio": (
            reserve / generated.data.budget
            if generated.data.budget > 0.0
            else 0.0
        ),
        "regular_purchase": regular_purchase,
        "exact_training_evaluation": _evaluation_summary(evaluation),
    }


def _run_e4(request: Mapping[str, Any]) -> dict[str, Any]:
    plan = request["plan"]
    source_path = Path(request["source_plan_path"])
    source = json.loads(source_path.read_text(encoding="utf-8"))
    if (
        source.get("status") != "optimal"
        or source.get("plan_id") != plan["source_e2_plan_id"]
    ):
        raise ValueError("E4 source E2 artifact is not the requested optimum")
    matrix_path = Path(request["matrix_path"])
    matrix = load_phase6_matrix(matrix_path)
    generated = generate_oos_data(
        matrix,
        matrix_path=matrix_path,
        tier_id=str(plan["tier_id"]),
        test_seed=int(plan["test_seed"]),
        budget=float(plan["budget"]),
    )
    evaluation = evaluate_first_stage(
        generated.data,
        source["regular_purchase"],
        float(source["reserve"]),
        **_solver_kwargs(
            request["solver"],
            time_limit_seconds=generated.tier.solver_call_seconds,
        ),
    )
    metrics = aggregate_oos_evaluation(
        generated.data,
        evaluation,
        reserve=float(source["reserve"]),
    )
    status = (
        "oos_solver_failure"
        if metrics["solver_failure_count"]
        else "optimal"
    )
    return {
        "status": status,
        "plan_id": plan["plan_id"],
        "family": "E4",
        "tier_id": generated.tier.id,
        "training_seed": plan["training_seed"],
        "test_seed": plan["test_seed"],
        "budget_index": plan["budget_index"],
        "budget": generated.budget,
        "policy": plan["policy"],
        "source_e2_plan_id": plan["source_e2_plan_id"],
        "source_e2_result_sha256": hashlib.sha256(
            source_path.read_bytes()
        ).hexdigest(),
        "metrics": metrics,
        "failure": (
            None
            if status == "optimal"
            else {
                "stage": "e4_exact_oos_evaluation",
                "message": metrics["plan_oos_status"],
            }
        ),
    }


def _run_e5(request: Mapping[str, Any]) -> dict[str, Any]:
    plan = request["plan"]
    matrix = load_phase6_matrix(request["matrix_path"])
    resolved = apply_sensitivity_overrides(matrix, plan["overrides"])
    generated = _generate_training(request, matrix=resolved)
    extensive = solve_endogenous_extensive(
        generated.data,
        consistency_tolerance=1.0e-5,
        **_solver_kwargs(
            request["solver"],
            time_limit_seconds=generated.tier.solver_call_seconds,
        ),
    )
    if extensive.status != "optimal" or extensive.objective is None:
        return {
            "status": extensive.status,
            "failure": {
                "stage": "e5_endogenous_extensive",
                "message": "sensitivity model did not solve consistently",
            },
        }
    return {
        "status": "optimal",
        "plan_id": plan["plan_id"],
        "family": "E5",
        "tier_id": generated.tier.id,
        "training_seed": generated.seed,
        "budget": generated.budget,
        "configuration_id": plan["configuration_id"],
        "design": plan["design"],
        "factor": plan["factor"],
        "value": plan["value"],
        "overrides": plan["overrides"],
        "robust_objective": extensive.objective,
        "reserve": extensive.reserve,
        "reserve_ratio": extensive.reserve_ratio,
        "regular_cost": extensive.master.regular_cost,
        "worst_scenario": (
            extensive.evaluation.worst_scenario
            if extensive.evaluation is not None
            else None
        ),
        "solver": extensive.master.solver,
    }


def execute_family_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Execute one bounded family work unit and return a compact artifact."""

    started = perf_counter()
    plan = request["plan"]
    family = str(plan["family"]).upper()
    dispatch = {
        "E1": _run_e1,
        "E2": _run_e2,
        "E4": _run_e4,
        "E5": _run_e5,
    }
    if family not in dispatch:
        raise ValueError(f"unsupported family: {family}")
    progress_path = (
        Path(request["progress_path"])
        if request.get("progress_path")
        else None
    )
    if progress_path is not None and family != "E1":
        _atomic_write_json(
            progress_path,
            {
                "status": "running",
                "stage": "family_plan",
                "family": family,
                "plan_id": plan["plan_id"],
            },
        )
    payload = dispatch[family](request)
    payload["worker_runtime_seconds"] = perf_counter() - started
    if progress_path is not None and family != "E1":
        _atomic_write_json(
            progress_path,
            {
                "status": "completed",
                "stage": "complete",
                "family": family,
                "plan_id": plan["plan_id"],
            },
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    try:
        request = json.loads(args.request.read_text(encoding="utf-8"))
        payload = execute_family_request(request)
    except Exception as exc:
        payload = {
            "status": "worker_exception",
            "failure": {
                "stage": "family_worker",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }
    _atomic_write_json(args.result, payload)
    return 0 if payload.get("status") == "optimal" else 1


if __name__ == "__main__":
    raise SystemExit(main())

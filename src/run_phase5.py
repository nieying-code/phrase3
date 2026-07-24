"""Run the phase-5 cross-budget SPW-C&CG experiment."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .scenario_generator import generate_synthetic_data, load_config
from .spw_ccg import SPWCCGResult, run_spw_ccg_budget_sequence


BUDGET_FIELDS = (
    "budget",
    "status",
    "failure_stage",
    "failure_message",
    "execution_order",
    "objectives_consistent",
    "objective_difference",
    "cold_termination_status",
    "warm_termination_status",
    "cold_objective",
    "warm_objective",
    "cold_iterations",
    "warm_iterations",
    "iteration_reduction",
    "cold_initial_pool_size",
    "warm_initial_pool_size",
    "cold_final_pool_size",
    "warm_final_pool_size",
    "active_scenario_count",
    "historical_adversarial_count",
    "cold_master_seconds",
    "warm_master_seconds",
    "cold_oracle_seconds",
    "warm_oracle_seconds",
    "cold_total_seconds",
    "warm_total_seconds",
    "runtime_reduction_seconds",
    "cold_reserve",
    "warm_reserve",
    "cold_worst_scenario",
    "warm_worst_scenario",
)
POOL_FIELDS = (
    "budget",
    "scenario",
    "in_cold_initial_pool",
    "in_warm_initial_pool",
    "in_warm_final_pool",
    "active_after_budget",
    "historical_adversarial_after_budget",
    "exact_recourse_cost",
)
ITERATION_FIELDS = (
    "budget",
    "mode",
    "iteration",
    "scenario_count",
    "added_scenario",
    "added_type",
    "LB",
    "candidate_UB",
    "global_UB",
    "gap",
    "regular_cost",
    "R",
    "R/B",
    "master_time",
    "oracle_time",
    "infeasible_scenario_count",
    "worst_recourse_cost",
    "worst_scenario",
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_rows(
    path: Path,
    fieldnames: Iterable[str],
    rows: Iterable[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(fieldnames))
        writer.writeheader()
        writer.writerows(rows)


def _budget_rows(result: SPWCCGResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for comparison in result.comparisons:
        rows.append(
            {
                "budget": comparison.budget,
                "status": "optimal",
                "failure_stage": None,
                "failure_message": None,
                "execution_order": "->".join(comparison.execution_order),
                "objectives_consistent": comparison.objectives_consistent,
                "objective_difference": comparison.objective_difference,
                "cold_termination_status": (
                    comparison.cold_result.termination_status
                ),
                "warm_termination_status": (
                    comparison.warm_result.termination_status
                ),
                "cold_objective": comparison.cold_result.objective,
                "warm_objective": comparison.warm_result.objective,
                "cold_iterations": comparison.cold_result.iterations,
                "warm_iterations": comparison.warm_result.iterations,
                "iteration_reduction": comparison.iteration_reduction,
                "cold_initial_pool_size": len(
                    comparison.cold_initial_scenarios
                ),
                "warm_initial_pool_size": len(
                    comparison.warm_initial_scenarios
                ),
                "cold_final_pool_size": len(
                    comparison.cold_result.final_scenario_set
                ),
                "warm_final_pool_size": len(
                    comparison.warm_result.final_scenario_set
                ),
                "active_scenario_count": len(
                    comparison.transferred_state.active_scenarios
                ),
                "historical_adversarial_count": len(
                    comparison.transferred_state.historical_adversarial_scenarios
                ),
                "cold_master_seconds": (
                    comparison.cold_result.master_runtime_seconds
                ),
                "warm_master_seconds": (
                    comparison.warm_result.master_runtime_seconds
                ),
                "cold_oracle_seconds": (
                    comparison.cold_result.oracle_runtime_seconds
                ),
                "warm_oracle_seconds": (
                    comparison.warm_result.oracle_runtime_seconds
                ),
                "cold_total_seconds": comparison.cold_total_seconds,
                "warm_total_seconds": comparison.warm_total_seconds,
                "runtime_reduction_seconds": (
                    comparison.runtime_reduction_seconds
                ),
                "cold_reserve": comparison.cold_result.reserve,
                "warm_reserve": comparison.warm_result.reserve,
                "cold_worst_scenario": comparison.cold_result.worst_scenario,
                "warm_worst_scenario": comparison.warm_result.worst_scenario,
            }
        )
    if result.failure is not None:
        failure = result.failure
        cold = failure.cold_result
        warm = failure.warm_result
        objective_difference = None
        if (
            cold is not None
            and warm is not None
            and cold.objective is not None
            and warm.objective is not None
        ):
            objective_difference = abs(cold.objective - warm.objective)
        rows.append(
            {
                "budget": failure.budget,
                "status": failure.status,
                "failure_stage": failure.stage,
                "failure_message": failure.message,
                "execution_order": "->".join(failure.execution_order),
                "objectives_consistent": False,
                "objective_difference": objective_difference,
                "cold_termination_status": (
                    cold.termination_status if cold is not None else None
                ),
                "warm_termination_status": (
                    warm.termination_status if warm is not None else None
                ),
                "cold_objective": (
                    cold.objective if cold is not None else None
                ),
                "warm_objective": (
                    warm.objective if warm is not None else None
                ),
                "cold_iterations": (
                    cold.iterations if cold is not None else None
                ),
                "warm_iterations": (
                    warm.iterations if warm is not None else None
                ),
                "iteration_reduction": (
                    cold.iterations - warm.iterations
                    if cold is not None and warm is not None
                    else None
                ),
                "cold_initial_pool_size": len(
                    failure.cold_initial_scenarios
                ),
                "warm_initial_pool_size": len(
                    failure.warm_initial_scenarios
                ),
                "cold_final_pool_size": (
                    len(cold.final_scenario_set)
                    if cold is not None
                    else None
                ),
                "warm_final_pool_size": (
                    len(warm.final_scenario_set)
                    if warm is not None
                    else None
                ),
                "active_scenario_count": None,
                "historical_adversarial_count": None,
                "cold_master_seconds": (
                    cold.master_runtime_seconds
                    if cold is not None
                    else None
                ),
                "warm_master_seconds": (
                    warm.master_runtime_seconds
                    if warm is not None
                    else None
                ),
                "cold_oracle_seconds": (
                    cold.oracle_runtime_seconds
                    if cold is not None
                    else None
                ),
                "warm_oracle_seconds": (
                    warm.oracle_runtime_seconds
                    if warm is not None
                    else None
                ),
                "cold_total_seconds": (
                    failure.cold_pool_build_seconds
                    + cold.total_runtime_seconds
                    if cold is not None
                    else None
                ),
                "warm_total_seconds": (
                    failure.warm_pool_build_seconds
                    + warm.total_runtime_seconds
                    if warm is not None
                    else None
                ),
                "runtime_reduction_seconds": None,
                "cold_reserve": cold.reserve if cold is not None else None,
                "warm_reserve": warm.reserve if warm is not None else None,
                "cold_worst_scenario": (
                    cold.worst_scenario if cold is not None else None
                ),
                "warm_worst_scenario": (
                    warm.worst_scenario if warm is not None else None
                ),
            }
        )
    return rows


def _pool_rows(result: SPWCCGResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for comparison in result.comparisons:
        state = comparison.transferred_state
        all_scenarios = comparison.warm_result.exact_scenario_costs
        for scenario in all_scenarios:
            rows.append(
                {
                    "budget": comparison.budget,
                    "scenario": scenario,
                    "in_cold_initial_pool": (
                        scenario in comparison.cold_initial_scenarios
                    ),
                    "in_warm_initial_pool": (
                        scenario in comparison.warm_initial_scenarios
                    ),
                    "in_warm_final_pool": (
                        scenario in state.final_scenario_set
                    ),
                    "active_after_budget": (
                        scenario in state.active_scenarios
                    ),
                    "historical_adversarial_after_budget": (
                        scenario in state.historical_adversarial_scenarios
                    ),
                    "exact_recourse_cost": all_scenarios[scenario],
                }
            )
    return rows


def _iteration_rows(result: SPWCCGResult) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    result_groups = [
        (
            comparison.budget,
            comparison.cold_result,
            comparison.warm_result,
        )
        for comparison in result.comparisons
    ]
    if result.failure is not None:
        result_groups.append(
            (
                result.failure.budget,
                result.failure.cold_result,
                result.failure.warm_result,
            )
        )
    for budget, cold_result, warm_result in result_groups:
        for mode, ccg_result in (
            ("cold", cold_result),
            ("warm", warm_result),
        ):
            if ccg_result is None:
                continue
            for iteration in ccg_result.iteration_log:
                rows.append(
                    {
                        "budget": budget,
                        "mode": mode,
                        **iteration.as_dict(),
                    }
                )
    return rows


def run(config_path: Path, output_root: Path) -> dict[str, Any]:
    config = load_config(config_path)
    data = generate_synthetic_data(config)
    solver_config = config["solver"]
    ccg_config = config["ccg"]
    phase5 = config["phase5"]
    preference = tuple(str(name) for name in solver_config["preference"])
    feasibility_tolerance = float(solver_config["feasibility_tolerance"])
    optimality_tolerance = float(solver_config["optimality_tolerance"])

    metadata = {
        "config": str(config_path),
        "seed": int(config["project"]["seed"]),
        "solver_preference": list(preference),
        "solver_tolerances": {
            "feasibility": feasibility_tolerance,
            "optimality": optimality_tolerance,
        },
    }
    try:
        result = run_spw_ccg_budget_sequence(
            data,
            tuple(float(value) for value in phase5["budgets"]),
            active_scenario_tolerance=float(
                phase5["active_scenario_tolerance"]
            ),
            objective_absolute_tolerance=float(
                phase5["objective_absolute_tolerance"]
            ),
            objective_relative_tolerance=float(
                phase5["objective_relative_tolerance"]
            ),
            ccg_absolute_tolerance=float(ccg_config["absolute_tolerance"]),
            ccg_relative_tolerance=float(ccg_config["relative_tolerance"]),
            max_iterations=int(ccg_config["max_iterations"]),
            solver_preference=preference,
            time_limit_seconds=float(solver_config["time_limit_seconds"]),
            feasibility_tolerance=feasibility_tolerance,
            optimality_tolerance=optimality_tolerance,
            alternate_execution_order=bool(
                phase5["alternate_execution_order"]
            ),
        )
        payload = {**metadata, **result.as_dict()}
        budget_rows = _budget_rows(result)
        pool_rows = _pool_rows(result)
        iteration_rows = _iteration_rows(result)
    except Exception as exc:
        result = None
        payload = {
            **metadata,
            "status": "runner_exception",
            "budgets": [
                float(value) for value in phase5.get("budgets", ())
            ],
            "completed_budget_count": 0,
            "total_cold_seconds": 0.0,
            "total_warm_seconds": 0.0,
            "total_iteration_reduction": 0,
            "comparisons": [],
            "failure": {
                "stage": "runner",
                "exception_type": type(exc).__name__,
                "message": str(exc),
            },
        }
        budget_rows = []
        pool_rows = []
        iteration_rows = []
    _write_json(
        output_root / "solutions" / "phase5" / "spw_ccg_results.json",
        payload,
    )
    _write_rows(
        output_root / "tables" / "phase5" / "budget_comparison.csv",
        BUDGET_FIELDS,
        budget_rows,
    )
    _write_rows(
        output_root / "tables" / "phase5" / "scenario_pool_transfer.csv",
        POOL_FIELDS,
        pool_rows,
    )
    _write_rows(
        output_root / "logs" / "phase5" / "ccg_iterations.csv",
        ITERATION_FIELDS,
        iteration_rows,
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/phase5.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "budgets": result["budgets"],
                "total_cold_seconds": result.get("total_cold_seconds", 0.0),
                "total_warm_seconds": result.get("total_warm_seconds", 0.0),
                "total_iteration_reduction": (
                    result.get("total_iteration_reduction", 0)
                ),
                "max_objective_difference": max(
                    (
                        row["objective_difference"]
                        for row in result["comparisons"]
                        if row["objective_difference"] is not None
                    ),
                    default=None,
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result["status"] != "optimal":
        raise SystemExit(f"phase 5 failed with status: {result['status']}")


if __name__ == "__main__":
    main()

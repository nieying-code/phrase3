"""Run the phase-4 cross-budget SPW-C&CG experiment."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .scenario_generator import generate_synthetic_data, load_config
from .spw_ccg import SPWCCGResult, run_spw_ccg_budget_sequence


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
                "execution_order": "->".join(comparison.execution_order),
                "objectives_consistent": comparison.objectives_consistent,
                "objective_difference": comparison.objective_difference,
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
    for comparison in result.comparisons:
        for mode, ccg_result in (
            ("cold", comparison.cold_result),
            ("warm", comparison.warm_result),
        ):
            for iteration in ccg_result.iteration_log:
                rows.append(
                    {
                        "budget": comparison.budget,
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
    phase4 = config["phase4"]
    preference = tuple(str(name) for name in solver_config["preference"])
    feasibility_tolerance = float(solver_config["feasibility_tolerance"])
    optimality_tolerance = float(solver_config["optimality_tolerance"])

    result = run_spw_ccg_budget_sequence(
        data,
        tuple(float(value) for value in phase4["budgets"]),
        active_scenario_tolerance=float(
            phase4["active_scenario_tolerance"]
        ),
        objective_absolute_tolerance=float(
            phase4["objective_absolute_tolerance"]
        ),
        objective_relative_tolerance=float(
            phase4["objective_relative_tolerance"]
        ),
        ccg_absolute_tolerance=float(ccg_config["absolute_tolerance"]),
        ccg_relative_tolerance=float(ccg_config["relative_tolerance"]),
        max_iterations=int(ccg_config["max_iterations"]),
        solver_preference=preference,
        time_limit_seconds=float(solver_config["time_limit_seconds"]),
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        alternate_execution_order=bool(
            phase4["alternate_execution_order"]
        ),
    )

    metadata = {
        "config": str(config_path),
        "seed": int(config["project"]["seed"]),
        "solver_preference": list(preference),
        "solver_tolerances": {
            "feasibility": feasibility_tolerance,
            "optimality": optimality_tolerance,
        },
    }
    payload = {**metadata, **result.as_dict()}
    _write_json(
        output_root / "solutions" / "phase4" / "spw_ccg_results.json",
        payload,
    )
    budget_rows = _budget_rows(result)
    _write_rows(
        output_root / "tables" / "phase4" / "budget_comparison.csv",
        budget_rows[0].keys(),
        budget_rows,
    )
    pool_rows = _pool_rows(result)
    _write_rows(
        output_root / "tables" / "phase4" / "scenario_pool_transfer.csv",
        pool_rows[0].keys(),
        pool_rows,
    )
    iteration_rows = _iteration_rows(result)
    _write_rows(
        output_root / "logs" / "phase4" / "ccg_iterations.csv",
        iteration_rows[0].keys(),
        iteration_rows,
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/phase4.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(
        json.dumps(
            {
                "status": result["status"],
                "budgets": result["budgets"],
                "total_cold_seconds": result["total_cold_seconds"],
                "total_warm_seconds": result["total_warm_seconds"],
                "total_iteration_reduction": (
                    result["total_iteration_reduction"]
                ),
                "max_objective_difference": max(
                    row["objective_difference"]
                    for row in result["comparisons"]
                ),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if result["status"] != "optimal":
        raise SystemExit(f"phase 4 failed with status: {result['status']}")


if __name__ == "__main__":
    main()

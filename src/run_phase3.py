"""Run phase-3 exact recourse, extensive model, and standard C&CG."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Iterable

from .ccg import CCGResult, run_standard_ccg
from .evaluation import EvaluationResult, evaluate_first_stage
from .extensive_model import ExtensiveSolution, solve_endogenous_extensive
from .inventory_model import (
    ModelSolution,
    build_deterministic_model,
    build_fixed_reserve_model,
    solve_model,
)
from .scenario_generator import generate_synthetic_data, load_config


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


def _evaluate_solution(
    data,
    solution: ModelSolution,
    *,
    solver_preference: tuple[str, ...],
    time_limit_seconds: float,
    feasibility_tolerance: float,
    optimality_tolerance: float,
) -> EvaluationResult:
    return evaluate_first_stage(
        data,
        solution.regular_purchase,
        solution.reserve,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )


def run(config_path: Path, output_root: Path) -> dict[str, Any]:
    config = load_config(config_path)
    data = generate_synthetic_data(config)
    solver_config = config["solver"]
    preference = tuple(str(name) for name in solver_config["preference"])
    time_limit = float(solver_config["time_limit_seconds"])
    feasibility_tolerance = float(solver_config["feasibility_tolerance"])
    optimality_tolerance = float(solver_config["optimality_tolerance"])
    solver_kwargs = {
        "solver_preference": preference,
        "time_limit_seconds": time_limit,
        "feasibility_tolerance": feasibility_tolerance,
        "optimality_tolerance": optimality_tolerance,
    }
    ccg_config = config["ccg"]
    consistency_tolerance = float(
        config.get("phase3", {}).get(
            "consistency_tolerance",
            ccg_config["absolute_tolerance"],
        )
    )

    deterministic = solve_model(
        build_deterministic_model(data),
        **solver_kwargs,
    )
    deterministic_eval = _evaluate_solution(
        data,
        deterministic,
        **solver_kwargs,
    )

    fixed: list[tuple[float, ModelSolution, EvaluationResult]] = []
    for raw_ratio in config["budget"]["fixed_reserve_ratios"]:
        ratio = float(raw_ratio)
        solution = solve_model(
            build_fixed_reserve_model(data, ratio),
            **solver_kwargs,
        )
        fixed.append(
            (
                ratio,
                solution,
                _evaluate_solution(
                    data,
                    solution,
                    **solver_kwargs,
                ),
            )
        )

    extensive = solve_endogenous_extensive(
        data,
        **solver_kwargs,
        consistency_tolerance=consistency_tolerance,
    )
    ccg = run_standard_ccg(
        data,
        absolute_tolerance=float(ccg_config["absolute_tolerance"]),
        relative_tolerance=float(ccg_config["relative_tolerance"]),
        max_iterations=int(ccg_config["max_iterations"]),
        **solver_kwargs,
    )

    solutions_root = output_root / "solutions" / "phase3"
    logs_root = output_root / "logs" / "phase3"
    tables_root = output_root / "tables" / "phase3"
    metadata = {
        "config": str(config_path),
        "seed": int(config["project"]["seed"]),
        "solver_preference": list(preference),
        "solver_tolerances": {
            "feasibility": feasibility_tolerance,
            "optimality": optimality_tolerance,
        },
    }
    _write_json(
        solutions_root / "extensive_solution.json",
        {**metadata, **extensive.as_dict()},
    )
    _write_json(
        solutions_root / "ccg_solution.json",
        {**metadata, **ccg.as_dict()},
    )
    _write_rows(
        logs_root / "ccg_iterations.csv",
        (
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
        ),
        (row.as_dict() for row in ccg.iteration_log),
    )

    comparison: list[dict[str, Any]] = []

    def append_comparison(
        name: str,
        reserve: float | None,
        reserve_ratio: float | None,
        evaluation: EvaluationResult | None,
        solver: str,
    ) -> None:
        comparison.append(
            {
                "model": name,
                "status": evaluation.status if evaluation else "unavailable",
                "exact_robust_objective": (
                    evaluation.robust_objective if evaluation else None
                ),
                "regular_cost": (
                    evaluation.regular_cost if evaluation else None
                ),
                "reserve": reserve,
                "reserve_ratio": reserve_ratio,
                "worst_scenario": (
                    evaluation.worst_scenario if evaluation else None
                ),
                "worst_recourse_cost": (
                    evaluation.worst_recourse_cost if evaluation else None
                ),
                "solver": solver,
            }
        )

    append_comparison(
        "deterministic_mean",
        deterministic.reserve,
        deterministic.reserve_ratio,
        deterministic_eval,
        deterministic.solver,
    )
    for ratio, solution, evaluation in fixed:
        append_comparison(
            f"fixed_reserve_{ratio:.2f}",
            solution.reserve,
            solution.reserve_ratio,
            evaluation,
            solution.solver,
        )
    append_comparison(
        "endogenous_extensive",
        extensive.reserve,
        extensive.reserve_ratio,
        extensive.evaluation,
        extensive.master.solver,
    )
    append_comparison(
        "standard_ccg",
        ccg.reserve,
        ccg.reserve_ratio,
        ccg.incumbent_evaluation,
        ccg.solver,
    )
    _write_rows(
        tables_root / "model_comparison.csv",
        (
            "model",
            "status",
            "exact_robust_objective",
            "regular_cost",
            "reserve",
            "reserve_ratio",
            "worst_scenario",
            "worst_recourse_cost",
            "solver",
        ),
        comparison,
    )

    scenario_rows: list[dict[str, Any]] = []
    if ccg.incumbent_evaluation is not None:
        for name, result in ccg.incumbent_evaluation.scenario_results.items():
            scenario_rows.append(
                {
                    "scenario": name,
                    "status": result.status,
                    "recourse_cost": result.objective,
                    "emergency_spend": result.emergency_spend,
                    "emergency_purchase": sum(
                        sum(values)
                        for values in result.emergency_purchase.values()
                    ),
                    "shortage": sum(
                        sum(values) for values in result.shortage.values()
                    ),
                    "waste": sum(
                        sum(values) for values in result.waste.values()
                    ),
                    "solver": result.solver,
                    "runtime_seconds": result.runtime_seconds,
                }
            )
    _write_rows(
        tables_root / "scenario_evaluation.csv",
        (
            "scenario",
            "status",
            "recourse_cost",
            "emergency_spend",
            "emergency_purchase",
            "shortage",
            "waste",
            "solver",
            "runtime_seconds",
        ),
        scenario_rows,
    )
    return {
        **metadata,
        "deterministic": deterministic.as_dict(),
        "deterministic_evaluation": deterministic_eval.as_dict(),
        "fixed_reserve": [
            {
                "ratio": ratio,
                "solution": solution.as_dict(),
                "evaluation": evaluation.as_dict(),
            }
            for ratio, solution, evaluation in fixed
        ],
        "extensive": extensive.as_dict(),
        "ccg": ccg.as_dict(),
        "comparison": comparison,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("configs/phase3.yaml"),
    )
    parser.add_argument("--output", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(
        json.dumps(
            {
                "extensive_status": result["extensive"]["status"],
                "extensive_objective": result["extensive"]["objective"],
                "ccg_status": result["ccg"]["termination_status"],
                "ccg_objective": result["ccg"]["objective"],
                "ccg_iterations": result["ccg"]["iterations"],
                "reserve": result["ccg"]["reserve"],
                "reserve_ratio": result["ccg"]["reserve_ratio"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

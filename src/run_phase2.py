"""Command-line entry point for the phase-2 minimum runnable models."""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from .inventory_model import (
    build_deterministic_model,
    build_fixed_reserve_model,
    solve_model,
)
from .scenario_generator import generate_synthetic_data, load_config, write_scenarios_csv


def run(config_path: Path, output_root: Path) -> dict[str, Any]:
    config = load_config(config_path)
    data = generate_synthetic_data(config)
    output_root.mkdir(parents=True, exist_ok=True)
    write_scenarios_csv(data, output_root / "generated_scenarios.csv")

    solver_config = config["solver"]
    preference = tuple(str(name) for name in solver_config["preference"])
    time_limit = float(solver_config["time_limit_seconds"])
    feasibility_tolerance = float(solver_config["feasibility_tolerance"])
    optimality_tolerance = float(solver_config["optimality_tolerance"])

    deterministic = solve_model(
        build_deterministic_model(data),
        solver_preference=preference,
        time_limit_seconds=time_limit,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )

    fixed_solutions = []
    for ratio in config["budget"]["fixed_reserve_ratios"]:
        fixed_solutions.append(
            solve_model(
                build_fixed_reserve_model(data, float(ratio)),
                solver_preference=preference,
                time_limit_seconds=time_limit,
                feasibility_tolerance=feasibility_tolerance,
                optimality_tolerance=optimality_tolerance,
            )
        )

    payload = {
        "config": str(config_path),
        "seed": int(config["project"]["seed"]),
        "deterministic": deterministic.as_dict(),
        "fixed_reserve": [solution.as_dict() for solution in fixed_solutions],
    }

    solutions_path = output_root / "phase2_solutions.json"
    solutions_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    summary_path = output_root / "phase2_summary.csv"
    with summary_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "model",
                "objective",
                "regular_cost",
                "reserve",
                "reserve_ratio",
                "worst_recourse_cost",
                "solver",
            ]
        )
        for solution in [deterministic, *fixed_solutions]:
            writer.writerow(
                [
                    solution.model_name,
                    solution.objective,
                    solution.regular_cost,
                    solution.reserve,
                    solution.reserve_ratio,
                    solution.theta,
                    solution.solver,
                ]
            )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("configs/base.yaml"))
    parser.add_argument("--output", type=Path, default=Path("outputs/solutions/phase2"))
    args = parser.parse_args()
    result = run(args.config, args.output)
    print(
        json.dumps(
            {
                "deterministic_objective": result["deterministic"]["objective"],
                "fixed_models": len(result["fixed_reserve"]),
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()

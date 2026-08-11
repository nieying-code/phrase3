"""Small, pre-specified diagnostic for zero endogenous emergency reserve."""

from __future__ import annotations

import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping

import yaml

from .evaluation import EvaluationResult, evaluate_first_stage
from .extensive_model import ExtensiveSolution, solve_endogenous_extensive
from .inventory_model import build_fixed_reserve_model, solve_model
from .model_data import ProcurementData
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_json, sha256_lf_text_file
from .phase6_protocol import (
    compute_reference_budget,
    generate_phase6_data,
    load_phase6_matrix,
)
from .reproducibility import validate_execution_source


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "configs/phase6_reserve_activation_diagnostic.yaml"
SOLVER_PREFERENCE = ("gurobi",)


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def procurement_data_sha256(data: ProcurementData) -> str:
    """Hash the complete finite scenario instance in canonical JSON form."""

    return _canonical_sha256(asdict(data))


def scaled_economic_data(
    data: ProcurementData,
    *,
    emergency_price_scale: float,
    waste_penalty_multiplier: float,
) -> ProcurementData:
    """Change only recourse prices and disposal penalties for diagnosis."""

    if emergency_price_scale <= 0.0:
        raise ValueError("emergency_price_scale must be positive")
    if waste_penalty_multiplier <= 0.0:
        raise ValueError("waste_penalty_multiplier must be positive")
    result = replace(
        data,
        emergency_price={
            scenario: {
                item: tuple(
                    emergency_price_scale * value
                    for value in data.emergency_price[scenario][item]
                )
                for item in data.items
            }
            for scenario in data.scenarios
        },
        waste_penalty={
            item: waste_penalty_multiplier * data.waste_penalty[item]
            for item in data.items
        },
    )
    result.validate()
    return result


def _evaluation_summary(evaluation: EvaluationResult) -> dict[str, Any]:
    results = tuple(evaluation.scenario_results.values())
    optimal = tuple(row for row in results if row.status == "optimal")

    def total_nested(mapping: Mapping[str, Any]) -> float:
        total = 0.0
        for values in mapping.values():
            for value in values:
                if isinstance(value, list):
                    total += sum(float(item) for item in value)
                else:
                    total += float(value)
        return total

    return {
        "status": evaluation.status,
        "scenario_count": len(results),
        "optimal_scenario_count": len(optimal),
        "infeasible_scenario_count": len(evaluation.infeasible_scenarios),
        "failed_scenario_count": len(evaluation.failed_scenarios),
        "worst_scenario": evaluation.worst_scenario,
        "worst_recourse_cost": evaluation.worst_recourse_cost,
        "maximum_emergency_spend": max(
            (float(row.emergency_spend or 0.0) for row in optimal),
            default=0.0,
        ),
        "maximum_total_emergency_purchase": max(
            (total_nested(row.emergency_purchase) for row in optimal),
            default=0.0,
        ),
        "maximum_total_shortage": max(
            (total_nested(row.shortage) for row in optimal),
            default=0.0,
        ),
        "maximum_total_disposal": max(
            (total_nested(row.total_disposal) for row in optimal),
            default=0.0,
        ),
    }


def _solver_kwargs(config: Mapping[str, Any]) -> dict[str, Any]:
    design = config["design"]
    return {
        "solver_preference": SOLVER_PREFERENCE,
        "time_limit_seconds": float(
            design["solver_call_time_limit_seconds"]
        ),
        "solver_threads": int(design["solver_threads"]),
        "feasibility_tolerance": 1.0e-7,
        "optimality_tolerance": 1.0e-7,
    }


def _solve_endogenous(
    case_id: str,
    data: ProcurementData,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    solution: ExtensiveSolution = solve_endogenous_extensive(
        data,
        consistency_tolerance=float(
            config["design"]["consistency_tolerance"]
        ),
        **_solver_kwargs(config),
    )
    if (
        solution.status != "optimal"
        or solution.objective is None
        or solution.reserve is None
        or solution.evaluation is None
    ):
        raise RuntimeError(
            f"endogenous diagnostic case {case_id} failed: {solution.status}"
        )
    return {
        "case_id": case_id,
        "status": solution.status,
        "data_sha256": procurement_data_sha256(data),
        "objective": float(solution.objective),
        "regular_cost": float(solution.master.regular_cost or 0.0),
        "reserve": float(solution.reserve),
        "reserve_ratio": float(solution.reserve_ratio or 0.0),
        "theta": float(solution.master.theta or 0.0),
        "consistency_difference": solution.consistency_difference,
        "regular_purchase_sha256": _canonical_sha256(
            solution.master.regular_purchase
        ),
        "evaluation": _evaluation_summary(solution.evaluation),
        "solver": solution.master.solver,
        "wall_seconds": perf_counter() - started,
    }


def _solve_fixed_ratio(
    ratio: float,
    data: ProcurementData,
    config: Mapping[str, Any],
) -> dict[str, Any]:
    started = perf_counter()
    solution = solve_model(
        build_fixed_reserve_model(data, ratio),
        **_solver_kwargs(config),
    )
    evaluation = evaluate_first_stage(
        data,
        solution.regular_purchase,
        solution.reserve,
        **_solver_kwargs(config),
    )
    if evaluation.status != "optimal" or evaluation.robust_objective is None:
        raise RuntimeError(
            f"fixed reserve diagnostic ratio {ratio} failed: "
            f"{evaluation.status}"
        )
    return {
        "reserve_ratio": ratio,
        "status": evaluation.status,
        "master_objective": solution.objective,
        "exact_objective": evaluation.robust_objective,
        "master_exact_difference": abs(
            solution.objective - evaluation.robust_objective
        ),
        "regular_cost": solution.regular_cost,
        "reserve": solution.reserve,
        "theta": solution.theta,
        "regular_purchase_sha256": _canonical_sha256(
            solution.regular_purchase
        ),
        "evaluation": _evaluation_summary(evaluation),
        "solver": solution.solver,
        "wall_seconds": perf_counter() - started,
    }


def _matrix_with_markup(
    matrix: Mapping[str, Any], markup_mean: float
) -> dict[str, Any]:
    result = json.loads(json.dumps(matrix))
    result["controlled_synthetic_baseline"][
        "emergency_price_markup_mean"
    ] = float(markup_mean)
    return result


def run_diagnostic(
    config_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if config.get("status") != "exploratory_diagnostic_only":
        raise ValueError("diagnostic config must remain exploratory only")
    if config["claim_boundary"].get("formal_evidence") is not False:
        raise ValueError("diagnostic must not be labelled formal evidence")

    matrix_path = PROJECT_ROOT / str(config["source_matrix"])
    matrix = load_phase6_matrix(matrix_path)
    environment = validate_locked_environment(PROJECT_ROOT)
    source = validate_execution_source(
        PROJECT_ROOT,
        required_tracked_paths=(
            config_path,
            matrix_path,
            Path(__file__).resolve(),
            PROJECT_ROOT / "requirements-gurobi-lock.txt",
        ),
    )
    if output_path.exists():
        raise FileExistsError(
            f"diagnostic result is immutable; choose a new path: {output_path}"
        )

    design = config["design"]
    tier_id = str(design["tier_id"])
    seed = int(design["seed"])
    reference_budget = compute_reference_budget(
        matrix,
        tier_id,
        matrix_path=matrix_path,
    )
    budget = float(design["budget_factor"]) * reference_budget
    baseline_generated = generate_phase6_data(
        matrix,
        matrix_path=matrix_path,
        tier_id=tier_id,
        seed=seed,
        budget=budget,
    )
    baseline_data = baseline_generated.data

    frontier = [
        _solve_fixed_ratio(float(ratio), baseline_data, config)
        for ratio in config["reserve_frontier_ratios"]
    ]

    surface: list[dict[str, Any]] = []
    for price_scale in config["mechanism_surface"][
        "emergency_price_scales"
    ]:
        for waste_multiplier in config["mechanism_surface"][
            "waste_penalty_multipliers"
        ]:
            data = scaled_economic_data(
                baseline_data,
                emergency_price_scale=float(price_scale),
                waste_penalty_multiplier=float(waste_multiplier),
            )
            row = _solve_endogenous(
                (
                    f"price_scale_{float(price_scale):g}__"
                    f"waste_multiplier_{float(waste_multiplier):g}"
                ),
                data,
                config,
            )
            row["emergency_price_scale"] = float(price_scale)
            row["waste_penalty_multiplier"] = float(waste_multiplier)
            row["positive_control"] = float(price_scale) < 1.0
            surface.append(row)

    attribution: list[dict[str, Any]] = []
    for markup_mean in config["markup_attribution"]["markup_means"]:
        changed_matrix = _matrix_with_markup(matrix, float(markup_mean))
        coupled = generate_phase6_data(
            changed_matrix,
            matrix_path=matrix_path,
            tier_id=tier_id,
            seed=seed,
            budget=budget,
        ).data
        pure_price = replace(
            coupled,
            shortage_penalty=baseline_data.shortage_penalty,
        )
        pure_price.validate()
        for mode, data in (
            ("pure_price_fixed_shortage_penalty", pure_price),
            ("coupled_price_and_shortage_penalty", coupled),
        ):
            row = _solve_endogenous(
                f"markup_{float(markup_mean):g}__{mode}",
                data,
                config,
            )
            row["markup_mean"] = float(markup_mean)
            row["mode"] = mode
            row["shortage_penalty"] = dict(data.shortage_penalty)
            attribution.append(row)

    activation_tolerance = float(design["reserve_activation_tolerance"])
    activated_surface = [
        row["case_id"]
        for row in surface
        if float(row["reserve"]) > activation_tolerance
    ]
    baseline_surface = next(
        row
        for row in surface
        if row["emergency_price_scale"] == 1.0
        and row["waste_penalty_multiplier"] == 1.0
    )
    result = {
        "schema": "phase6_reserve_activation_diagnostic_v1",
        "status": "complete",
        "claim_boundary": config["claim_boundary"],
        "source": source,
        "environment": environment,
        "environment_sha256": environment_sha256(environment),
        "config_path": config_path.relative_to(PROJECT_ROOT).as_posix(),
        "config_sha256": sha256_lf_text_file(config_path),
        "matrix_path": matrix_path.relative_to(PROJECT_ROOT).as_posix(),
        "matrix_sha256": sha256_lf_text_file(matrix_path),
        "design": {
            "tier_id": tier_id,
            "seed": seed,
            "scenario_count": len(baseline_data.scenarios),
            "periods": baseline_data.periods,
            "items": list(baseline_data.items),
            "reference_budget": reference_budget,
            "budget_factor": float(design["budget_factor"]),
            "budget": budget,
            "baseline_data_sha256": procurement_data_sha256(
                baseline_data
            ),
        },
        "baseline_endogenous": baseline_surface,
        "reserve_frontier": frontier,
        "mechanism_surface": surface,
        "markup_attribution": attribution,
        "diagnostic_summary": {
            "baseline_reserve": baseline_surface["reserve"],
            "baseline_reserve_ratio": baseline_surface["reserve_ratio"],
            "minimum_positive_fixed_ratio_tested": min(
                ratio
                for ratio in config["reserve_frontier_ratios"]
                if float(ratio) > 0.0
            ),
            "activated_surface_case_ids": activated_surface,
            "model_can_activate_reserve_in_positive_control": any(
                row["positive_control"]
                and float(row["reserve"]) > activation_tolerance
                for row in surface
            ),
        },
    }
    atomic_write_json(output_path, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    config_path = args.config.resolve()
    output_path = args.output.resolve()
    try:
        result = run_diagnostic(config_path, output_path)
    except Exception as exc:
        if not output_path.exists():
            atomic_write_json(
                output_path,
                {
                    "schema": "phase6_reserve_activation_diagnostic_v1",
                    "status": "failed",
                    "failure": {
                        "stage": "diagnostic_runner",
                        "type": type(exc).__name__,
                        "message": str(exc)[:2000],
                    },
                },
            )
        raise
    print(
        json.dumps(
            {
                "status": result["status"],
                "output": str(output_path),
                **result["diagnostic_summary"],
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

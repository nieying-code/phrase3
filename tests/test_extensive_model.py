from __future__ import annotations

import math

from src.evaluation import evaluate_first_stage
from src.extensive_model import solve_endogenous_extensive
from src.inventory_model import build_fixed_reserve_model, solve_model
from src.model_data import ProcurementData


def unique_two_scenario_data() -> ProcurementData:
    data = ProcurementData(
        items=("food",),
        periods=1,
        scenarios=("low", "high"),
        budget=10.0,
        shelf_life={"food": 1},
        initial_inventory={"food": (0.0,)},
        storage_capacity=(100.0,),
        regular_price={"food": (1.0,)},
        demand={
            "low": {"food": (4.0,)},
            "high": {"food": (8.0,)},
        },
        emergency_price={
            "low": {"food": (2.0,)},
            "high": {"food": (2.0,)},
        },
        emergency_supply={
            "low": {"food": (0.0,)},
            "high": {"food": (0.0,)},
        },
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def test_extensive_objective_equals_regular_plus_max_exact_recourse() -> None:
    data = unique_two_scenario_data()
    solution = solve_endogenous_extensive(
        data,
        solver_preference=("highs",),
        consistency_tolerance=1.0e-7,
    )
    assert solution.status == "optimal"
    assert solution.evaluation is not None
    assert solution.master.objective is not None
    assert solution.objective is not None
    expected = (
        float(solution.master.regular_cost)
        + max(solution.evaluation.exact_scenario_costs.values())
    )
    assert math.isclose(solution.objective, expected, abs_tol=1.0e-7)
    assert math.isclose(
        float(solution.master.objective),
        solution.objective,
        abs_tol=1.0e-7,
    )
    assert float(solution.consistency_difference) <= 1.0e-7


def test_endogenous_model_not_worse_than_tested_fixed_ratios() -> None:
    data = unique_two_scenario_data()
    endogenous = solve_endogenous_extensive(
        data,
        solver_preference=("highs",),
        consistency_tolerance=1.0e-7,
    )
    assert endogenous.status == "optimal"
    fixed_objectives: list[float] = []
    for ratio in (0.0, 0.2, 0.5, 0.8):
        fixed = solve_model(
            build_fixed_reserve_model(data, ratio),
            solver_preference=("highs",),
        )
        evaluation = evaluate_first_stage(
            data,
            fixed.regular_purchase,
            fixed.reserve,
            solver_preference=("highs",),
        )
        assert evaluation.status == "optimal"
        fixed_objectives.append(float(evaluation.robust_objective))
    assert float(endogenous.objective) <= min(fixed_objectives) + 1.0e-7

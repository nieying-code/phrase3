from __future__ import annotations

import math

import pyomo.environ as pyo

from src.inventory_model import (
    build_deterministic_model,
    build_fixed_reserve_model,
    solve_model,
)
from src.model_data import ProcurementData


def tiny_data(
    *,
    periods: int = 2,
    shelf_life: int = 2,
    demand: tuple[float, ...] = (5.0, 5.0),
    initial_inventory: tuple[float, ...] | None = None,
) -> ProcurementData:
    if initial_inventory is None:
        initial_inventory = tuple(0.0 for _ in range(shelf_life))
    data = ProcurementData(
        items=("food",),
        periods=periods,
        scenarios=("base", "stress"),
        budget=20.0,
        shelf_life={"food": shelf_life},
        initial_inventory={"food": initial_inventory},
        storage_capacity=tuple(100.0 for _ in range(periods)),
        regular_price={"food": tuple(1.0 for _ in range(periods))},
        demand={
            "base": {"food": demand},
            "stress": {"food": tuple(value * 1.2 for value in demand)},
        },
        emergency_price={
            "base": {"food": tuple(2.0 for _ in range(periods))},
            "stress": {"food": tuple(3.0 for _ in range(periods))},
        },
        emergency_supply={
            "base": {"food": tuple(20.0 for _ in range(periods))},
            "stress": {"food": tuple(20.0 for _ in range(periods))},
        },
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 0.5},
    )
    data.validate()
    return data


def test_deterministic_model_is_optimal_and_budget_balances() -> None:
    data = tiny_data()
    model = build_deterministic_model(data)
    solution = solve_model(model, solver_preference=("highs",))
    assert math.isfinite(solution.objective)
    assert abs(solution.regular_cost + solution.reserve - data.budget) <= 1.0e-6
    assert sum(solution.shortage["mean"]["food"]) <= 1.0e-7


def test_fixed_reserve_ratio_is_enforced() -> None:
    data = tiny_data()
    solution = solve_model(
        build_fixed_reserve_model(data, 0.25),
        solver_preference=("highs",),
    )
    assert abs(solution.reserve - 5.0) <= 1.0e-7
    assert solution.regular_cost <= 15.0 + 1.0e-7


def test_zero_reserve_forces_zero_emergency_purchase() -> None:
    data = tiny_data()
    solution = solve_model(
        build_fixed_reserve_model(data, 0.0),
        solver_preference=("highs",),
    )
    for scenario in data.scenarios:
        assert sum(solution.emergency_purchase[scenario]["food"]) <= 1.0e-7


def test_shelf_life_one_expires_leftover_without_carrying_inventory() -> None:
    data = tiny_data(
        periods=1,
        shelf_life=1,
        demand=(0.0,),
        initial_inventory=(5.0,),
    )
    model = build_fixed_reserve_model(data, 1.0)
    solution = solve_model(model, solver_preference=("highs",))
    assert abs(solution.waste["base"]["food"][0] - 5.0) <= 1.0e-7
    assert abs(pyo.value(model.inventory["base", "food", 0, 0])) <= 1.0e-7


def test_age_flow_conservation() -> None:
    data = tiny_data()
    model = build_fixed_reserve_model(data, 0.5)
    solve_model(model, solver_preference=("highs",))
    for scenario in data.scenarios:
        for t in range(data.periods):
            for age in range(data.shelf_life["food"]):
                available = pyo.value(model.available[scenario, "food", t, age])
                consumed = pyo.value(model.consume[scenario, "food", t, age])
                if age == data.shelf_life["food"] - 1:
                    remainder = pyo.value(model.waste[scenario, "food", t])
                else:
                    remainder = pyo.value(model.inventory[scenario, "food", t, age])
                assert abs(available - consumed - remainder) <= 1.0e-7

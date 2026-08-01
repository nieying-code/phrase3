from __future__ import annotations

import math

import pyomo.environ as pyo

from src.model_data import ProcurementData
from src.recourse_model import build_recourse_model, solve_recourse_model


def one_scenario_data(
    *,
    periods: int = 1,
    shelf_life: int = 1,
    demand: tuple[float, ...] = (5.0,),
    emergency_price: tuple[float, ...] = (2.0,),
    emergency_supply: tuple[float, ...] = (10.0,),
    storage_capacity: tuple[float, ...] = (100.0,),
    initial_inventory: tuple[float, ...] | None = None,
) -> ProcurementData:
    if initial_inventory is None:
        initial_inventory = tuple(0.0 for _ in range(shelf_life))
    data = ProcurementData(
        items=("food",),
        periods=periods,
        scenarios=("s0",),
        budget=20.0,
        shelf_life={"food": shelf_life},
        initial_inventory={"food": initial_inventory},
        storage_capacity=storage_capacity,
        regular_price={"food": tuple(1.0 for _ in range(periods))},
        demand={"s0": {"food": demand}},
        emergency_price={"s0": {"food": emergency_price}},
        emergency_supply={"s0": {"food": emergency_supply}},
        shortage_penalty={"food": 10.0},
        waste_penalty={"food": 0.5},
    )
    data.validate()
    return data


def test_exact_recourse_manual_objective_and_balances() -> None:
    data = one_scenario_data()
    model = build_recourse_model(
        data,
        "s0",
        {"food": [2.0]},
        reserve=4.0,
    )
    result = solve_recourse_model(model, solver_preference=("gurobi",))
    assert result.status == "optimal"
    assert math.isclose(float(result.objective), 14.0, abs_tol=1.0e-7)
    assert math.isclose(float(result.emergency_spend), 4.0, abs_tol=1.0e-7)
    assert math.isclose(result.emergency_purchase["food"][0], 2.0, abs_tol=1.0e-7)
    assert math.isclose(result.shortage["food"][0], 1.0, abs_tol=1.0e-7)
    assert result.emergency_spend <= 4.0 + 1.0e-7

    available = pyo.value(model.available["s0", "food", 0, 0])
    consumed = pyo.value(model.consume["s0", "food", 0, 0])
    waste = pyo.value(model.waste["s0", "food", 0])
    assert math.isclose(available, consumed + waste, abs_tol=1.0e-7)
    assert math.isclose(
        consumed + pyo.value(model.shortage["s0", "food", 0]),
        data.demand["s0"]["food"][0],
        abs_tol=1.0e-7,
    )


def test_zero_reserve_forces_zero_emergency_purchase() -> None:
    data = one_scenario_data()
    result = solve_recourse_model(
        build_recourse_model(data, "s0", {"food": [0.0]}, reserve=0.0),
        solver_preference=("gurobi",),
    )
    assert result.status == "optimal"
    assert sum(result.emergency_purchase["food"]) <= 1.0e-8
    assert math.isclose(result.shortage["food"][0], 5.0, abs_tol=1.0e-7)


def test_shelf_life_one_cannot_carry_inventory() -> None:
    data = one_scenario_data(
        demand=(0.0,),
        initial_inventory=(5.0,),
    )
    model = build_recourse_model(
        data,
        "s0",
        {"food": [0.0]},
        reserve=0.0,
    )
    result = solve_recourse_model(model, solver_preference=("gurobi",))
    assert result.status == "optimal"
    assert math.isclose(result.waste["food"][0], 5.0, abs_tol=1.0e-7)
    assert math.isclose(
        result.ending_inventory["food"][0][0],
        0.0,
        abs_tol=1.0e-7,
    )


def test_recourse_reports_true_infeasibility() -> None:
    data = one_scenario_data(
        shelf_life=2,
        demand=(0.0,),
        storage_capacity=(0.0,),
        initial_inventory=(0.0, 0.0),
    )
    model = build_recourse_model(data, "s0", {"food": [1.0]}, reserve=0.0)
    model.test_contradiction = pyo.Constraint(
        expr=model.shortage["s0", "food", 0] <= -1.0
    )
    result = solve_recourse_model(model, solver_preference=("gurobi",))
    assert result.status == "infeasible"
    assert result.objective is None

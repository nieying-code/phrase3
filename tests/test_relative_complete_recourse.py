from __future__ import annotations

import math

import pyomo.environ as pyo
import pytest

from src.extensive_model import build_endogenous_extensive_model
from src.model_data import ProcurementData
from src.recourse_model import build_recourse_model, solve_recourse_model


def _data(
    *,
    items: tuple[str, ...] = ("food",),
    periods: int = 2,
    shelf_lives: tuple[int, ...] = (3,),
    demands: tuple[tuple[float, ...], ...] = ((1.0, 1.0),),
    capacities: tuple[float, ...] = (0.0, 0.0),
    waste_penalties: tuple[float, ...] = (2.0,),
) -> ProcurementData:
    data = ProcurementData(
        items=items,
        periods=periods,
        scenarios=("s0",),
        budget=100.0,
        shelf_life=dict(zip(items, shelf_lives, strict=True)),
        initial_inventory={
            item: tuple(0.0 for _ in range(life))
            for item, life in zip(items, shelf_lives, strict=True)
        },
        storage_capacity=capacities,
        regular_price={item: (1.0,) * periods for item in items},
        demand={
            "s0": {
                item: demand
                for item, demand in zip(items, demands, strict=True)
            }
        },
        emergency_price={
            "s0": {item: (3.0,) * periods for item in items}
        },
        emergency_supply={
            "s0": {item: (100.0,) * periods for item in items}
        },
        shortage_penalty={item: 10.0 for item in items},
        waste_penalty=dict(zip(items, waste_penalties, strict=True)),
    )
    data.validate()
    return data


def _solve(
    data: ProcurementData,
    purchase: dict[str, list[float]],
):
    return solve_recourse_model(
        build_recourse_model(data, "s0", purchase, reserve=0.0),
        solver_preference=("gurobi",),
        solver_threads=1,
    )


def test_zero_demand_positive_purchase_zero_capacity_is_feasible() -> None:
    data = _data(demands=((0.0, 0.0),))
    result = _solve(data, {"food": [7.0, 4.0]})
    assert result.status == "optimal"
    assert math.isclose(sum(result.total_disposal["food"]), 11.0, abs_tol=1e-7)
    assert math.isclose(
        sum(sum(values) for values in result.early_disposal["food"]),
        11.0,
        abs_tol=1e-7,
    )
    assert sum(result.expired_waste["food"]) <= 1e-7


def test_low_demand_positive_purchase_tight_capacity_is_feasible() -> None:
    data = _data(demands=((0.1, 0.2),), capacities=(0.05, 0.05))
    result = _solve(data, {"food": [8.0, 6.0]})
    assert result.status == "optimal"
    assert result.objective is not None
    assert sum(result.early_disposal["food"][0]) >= 7.85


def test_normal_demand_and_capacity_remain_feasible() -> None:
    data = _data(demands=((4.0, 4.0),), capacities=(20.0, 20.0))
    result = _solve(data, {"food": [3.0, 3.0]})
    assert result.status == "optimal"


def test_shelf_life_one_uses_expired_waste_not_early_disposal() -> None:
    data = _data(
        periods=1,
        shelf_lives=(1,),
        demands=((0.0,),),
        capacities=(0.0,),
    )
    result = _solve(data, {"food": [5.0]})
    assert result.status == "optimal"
    assert result.early_disposal["food"] == [[0.0]]
    assert math.isclose(result.expired_waste["food"][0], 5.0, abs_tol=1e-7)
    assert math.isclose(result.total_disposal["food"][0], 5.0, abs_tol=1e-7)


def test_multi_item_multi_period_relative_complete_recourse() -> None:
    data = _data(
        items=("food", "medicine"),
        periods=3,
        shelf_lives=(2, 4),
        demands=((0.0, 0.5, 0.0), (0.1, 0.0, 0.2)),
        capacities=(0.0, 0.0, 0.0),
        waste_penalties=(2.0, 4.0),
    )
    result = _solve(
        data,
        {"food": [4.0, 3.0, 2.0], "medicine": [2.0, 2.0, 2.0]},
    )
    assert result.status == "optimal"
    assert set(result.early_disposal) == {"food", "medicine"}
    assert all(
        abs(value) <= 1e-7
        for item in data.items
        for period in result.ending_inventory[item]
        for value in period
    )


def test_disposal_cost_and_components_do_not_double_count() -> None:
    data = _data(
        periods=1,
        shelf_lives=(2,),
        demands=((0.0,),),
        capacities=(0.0,),
        waste_penalties=(2.5,),
    )
    result = _solve(data, {"food": [4.0]})
    early = sum(result.early_disposal["food"][0])
    expired = result.expired_waste["food"][0]
    total = result.total_disposal["food"][0]
    assert math.isclose(total, early + expired, abs_tol=1e-7)
    assert math.isclose(result.waste["food"][0], total, abs_tol=1e-7)
    assert math.isclose(float(result.objective), 2.5 * total, abs_tol=1e-7)


def test_recourse_and_extensive_share_disposal_constraints() -> None:
    data = _data()
    recourse = build_recourse_model(
        data, "s0", {"food": [2.0, 2.0]}, reserve=0.0
    )
    extensive = build_endogenous_extensive_model(data)
    for model in (recourse, extensive):
        assert hasattr(model, "early_disposal")
        assert hasattr(model, "expired_waste")
        assert hasattr(model, "total_disposal")
        body = str(model.age_flow["s0", "food", 0, 0].body)
        assert "early_disposal" in body


def test_serialization_exposes_explicit_and_legacy_disposal_fields() -> None:
    data = _data(demands=((0.0, 0.0),))
    result = _solve(data, {"food": [2.0, 1.0]})
    payload = result.as_dict()
    assert payload["waste"] == payload["total_disposal"]
    assert set(payload) >= {
        "expired_waste",
        "early_disposal",
        "total_disposal",
        "waste",
    }


def test_true_infeasibility_and_solver_failure_remain_distinct() -> None:
    data = _data()
    model = build_recourse_model(
        data, "s0", {"food": [1.0, 1.0]}, reserve=0.0
    )
    model.contradiction = pyo.Constraint(
        expr=model.shortage["s0", "food", 0] <= -1.0
    )
    infeasible = solve_recourse_model(
        model, solver_preference=("gurobi",), solver_threads=1
    )
    solver_failure = solve_recourse_model(
        build_recourse_model(
            data, "s0", {"food": [1.0, 1.0]}, reserve=0.0
        ),
        solver_preference=("highs",),
        solver_threads=1,
    )
    assert infeasible.status == "infeasible"
    assert solver_failure.status == "solver_error"


def test_zero_disposal_penalty_is_rejected() -> None:
    with pytest.raises(ValueError, match="waste penalties must be positive"):
        _data(waste_penalties=(0.0,))

"""Deterministic and fixed-reserve models backed by shared phase-3 rules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import pyomo.environ as pyo

from .model_common import (
    build_inventory_model,
    extract_item_time,
    extract_regular_purchase,
    solve_with_status,
)
from .model_data import ProcurementData


@dataclass(frozen=True)
class ModelSolution:
    model_name: str
    solver: str
    objective: float
    regular_cost: float
    reserve: float
    reserve_ratio: float
    theta: float
    regular_purchase: dict[str, list[float]]
    scenario_cost: dict[str, float]
    emergency_purchase: dict[str, dict[str, list[float]]]
    shortage: dict[str, dict[str, list[float]]]
    waste: dict[str, dict[str, list[float]]]
    runtime_seconds: float = 0.0
    status: str = "optimal"

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "solver": self.solver,
            "status": self.status,
            "objective": self.objective,
            "regular_cost": self.regular_cost,
            "reserve": self.reserve,
            "reserve_ratio": self.reserve_ratio,
            "theta": self.theta,
            "regular_purchase": self.regular_purchase,
            "scenario_cost": self.scenario_cost,
            "emergency_purchase": self.emergency_purchase,
            "shortage": self.shortage,
            "waste": self.waste,
            "runtime_seconds": self.runtime_seconds,
        }


def build_deterministic_model(data: ProcurementData) -> pyo.ConcreteModel:
    """Mean-scenario model with residual budget allocated to reserve."""

    mean_data = data.mean_scenario()
    return build_inventory_model(
        mean_data,
        model_name="DeterministicModel",
        reserve_policy="endogenous",
        objective_kind="robust",
    )


def build_fixed_reserve_model(
    data: ProcurementData,
    reserve_ratio: float,
) -> pyo.ConcreteModel:
    """Finite-scenario robust model with an exogenous reserve share."""

    return build_inventory_model(
        data,
        model_name=f"FixedReserveModel[rho={reserve_ratio:.4f}]",
        reserve_policy="fixed_ratio",
        fixed_reserve_ratio=reserve_ratio,
        objective_kind="robust",
    )


def solve_model(
    model: pyo.ConcreteModel,
    *,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = None,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    tee: bool = False,
) -> ModelSolution:
    """Solve a phase-2-compatible model and extract its master variables."""

    record = solve_with_status(
        model,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        tee=tee,
    )
    if record.status != "optimal":
        detail = f": {record.message}" if record.message else ""
        raise RuntimeError(
            f"model did not solve to optimality ({record.status}, "
            f"{record.termination_condition}){detail}"
        )

    data: ProcurementData = model._procurement_data
    scenarios = tuple(str(s) for s in model.S)
    emergency_purchase = {
        scenario: {
            item: extract_item_time(
                model.q,
                data=data,
                prefix=(scenario, item),
            )
            for item in data.items
        }
        for scenario in scenarios
    }
    shortage = {
        scenario: {
            item: extract_item_time(
                model.shortage,
                data=data,
                prefix=(scenario, item),
            )
            for item in data.items
        }
        for scenario in scenarios
    }
    waste = {
        scenario: {
            item: extract_item_time(
                model.waste,
                data=data,
                prefix=(scenario, item),
            )
            for item in data.items
        }
        for scenario in scenarios
    }
    reserve = float(pyo.value(model.R))
    return ModelSolution(
        model_name=str(model._model_name),
        solver=record.solver,
        status=record.status,
        objective=float(pyo.value(model.objective)),
        regular_cost=float(pyo.value(model.regular_cost)),
        reserve=reserve,
        reserve_ratio=reserve / data.budget if data.budget > 0 else 0.0,
        theta=float(pyo.value(model.theta)),
        regular_purchase=extract_regular_purchase(model, data),
        scenario_cost={
            scenario: float(pyo.value(model.scenario_cost[scenario]))
            for scenario in scenarios
        },
        emergency_purchase=emergency_purchase,
        shortage=shortage,
        waste=waste,
        runtime_seconds=record.runtime_seconds,
    )

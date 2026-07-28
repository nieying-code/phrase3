"""Independent exact single-scenario recourse models."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

import pyomo.environ as pyo

from .model_common import build_inventory_model, solve_with_status
from .model_data import ProcurementData


@dataclass(frozen=True)
class RecourseResult:
    scenario: str
    status: str
    objective: float | None
    emergency_purchase: dict[str, list[float]]
    emergency_spend: float | None
    shortage: dict[str, list[float]]
    waste: dict[str, list[float]]
    ending_inventory: dict[str, list[list[float]]]
    solver: str
    runtime_seconds: float
    termination_condition: str
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "scenario": self.scenario,
            "status": self.status,
            "objective": self.objective,
            "emergency_purchase": self.emergency_purchase,
            "emergency_spend": self.emergency_spend,
            "shortage": self.shortage,
            "waste": self.waste,
            "ending_inventory": self.ending_inventory,
            "solver": self.solver,
            "runtime_seconds": self.runtime_seconds,
            "termination_condition": self.termination_condition,
            "message": self.message,
        }


def build_recourse_model(
    data: ProcurementData,
    scenario_name: str,
    regular_purchase: Mapping[str, Sequence[float]],
    reserve: float,
) -> pyo.ConcreteModel:
    """Fix ``y`` and ``R`` and minimize exact recourse cost for one scenario."""

    return build_inventory_model(
        data,
        scenario_names=(scenario_name,),
        model_name=f"RecourseModel[{scenario_name}]",
        reserve_policy="fixed_first_stage",
        regular_purchase=regular_purchase,
        reserve=reserve,
        objective_kind="recourse",
    )


def solve_recourse_model(
    model: pyo.ConcreteModel,
    *,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = None,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    tee: bool = False,
) -> RecourseResult:
    """Solve and extract a normalized exact-recourse result."""

    scenario = str(model._scenario_names[0])
    data: ProcurementData = model._procurement_data
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
        return RecourseResult(
            scenario=scenario,
            status=record.status,
            objective=None,
            emergency_purchase={},
            emergency_spend=None,
            shortage={},
            waste={},
            ending_inventory={},
            solver=record.solver,
            runtime_seconds=record.runtime_seconds,
            termination_condition=record.termination_condition,
            message=record.message,
        )

    emergency_purchase = {
        item: [
            float(pyo.value(model.q[scenario, item, t]))
            for t in range(data.periods)
        ]
        for item in data.items
    }
    shortage = {
        item: [
            float(pyo.value(model.shortage[scenario, item, t]))
            for t in range(data.periods)
        ]
        for item in data.items
    }
    waste = {
        item: [
            float(pyo.value(model.waste[scenario, item, t]))
            for t in range(data.periods)
        ]
        for item in data.items
    }
    ending_inventory = {
        item: [
            [
                float(
                    pyo.value(model.inventory[scenario, item, t, age])
                )
                for age in range(data.shelf_life[item])
            ]
            for t in range(data.periods)
        ]
        for item in data.items
    }
    return RecourseResult(
        scenario=scenario,
        status=record.status,
        objective=float(pyo.value(model.scenario_cost[scenario])),
        emergency_purchase=emergency_purchase,
        emergency_spend=float(pyo.value(model.emergency_spend[scenario])),
        shortage=shortage,
        waste=waste,
        ending_inventory=ending_inventory,
        solver=record.solver,
        runtime_seconds=record.runtime_seconds,
        termination_condition=record.termination_condition,
        message=record.message,
    )


def solve_recourse(
    data: ProcurementData,
    scenario_name: str,
    regular_purchase: Mapping[str, Sequence[float]],
    reserve: float,
    *,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = None,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    tee: bool = False,
) -> RecourseResult:
    """Convenience wrapper for building and solving one exact recourse LP."""

    model = build_recourse_model(
        data,
        scenario_name,
        regular_purchase,
        reserve,
    )
    return solve_recourse_model(
        model,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        tee=tee,
    )

"""Endogenous-reserve restricted masters and full extensive model."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Sequence

import pyomo.environ as pyo

from .evaluation import EvaluationResult, evaluate_first_stage
from .model_common import (
    build_inventory_model,
    extract_regular_purchase,
    solve_with_status,
)
from .model_data import ProcurementData


@dataclass(frozen=True)
class MasterSolution:
    status: str
    objective: float | None
    regular_cost: float | None
    reserve: float | None
    reserve_ratio: float | None
    theta: float | None
    regular_purchase: dict[str, list[float]]
    master_scenario_costs: dict[str, float]
    scenario_names: tuple[str, ...]
    solver: str
    runtime_seconds: float
    termination_condition: str
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "regular_cost": self.regular_cost,
            "reserve": self.reserve,
            "reserve_ratio": self.reserve_ratio,
            "theta": self.theta,
            "regular_purchase": self.regular_purchase,
            "master_scenario_costs": self.master_scenario_costs,
            "scenario_names": list(self.scenario_names),
            "solver": self.solver,
            "runtime_seconds": self.runtime_seconds,
            "termination_condition": self.termination_condition,
            "message": self.message,
        }


@dataclass(frozen=True)
class ExtensiveSolution:
    status: str
    master: MasterSolution
    evaluation: EvaluationResult | None
    consistency_difference: float | None
    tolerance: float

    @property
    def objective(self) -> float | None:
        if self.evaluation is None:
            return None
        return self.evaluation.robust_objective

    @property
    def reserve(self) -> float | None:
        return self.master.reserve

    @property
    def reserve_ratio(self) -> float | None:
        return self.master.reserve_ratio

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "objective": self.objective,
            "consistency_difference": self.consistency_difference,
            "tolerance": self.tolerance,
            "master": self.master.as_dict(),
            "evaluation": (
                self.evaluation.as_dict()
                if self.evaluation is not None
                else None
            ),
        }


def build_restricted_master(
    data: ProcurementData,
    scenario_names: Sequence[str],
) -> pyo.ConcreteModel:
    """Build the endogenous-reserve master for an ordered scenario subset."""

    return build_inventory_model(
        data,
        scenario_names=tuple(scenario_names),
        model_name="RestrictedMaster",
        reserve_policy="endogenous",
        objective_kind="robust",
    )


def build_endogenous_extensive_model(
    data: ProcurementData,
) -> pyo.ConcreteModel:
    """Build the full finite-scenario extensive model."""

    model = build_restricted_master(data, data.scenarios)
    model._model_name = "EndogenousReserveExtensiveModel"
    return model


def solve_master(
    model: pyo.ConcreteModel,
    *,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    tee: bool = False,
) -> MasterSolution:
    """Solve a restricted master and extract only first-stage/master values."""

    record = solve_with_status(
        model,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        tee=tee,
    )
    scenarios = tuple(str(s) for s in model.S)
    if record.status != "optimal":
        return MasterSolution(
            status=record.status,
            objective=None,
            regular_cost=None,
            reserve=None,
            reserve_ratio=None,
            theta=None,
            regular_purchase={},
            master_scenario_costs={},
            scenario_names=scenarios,
            solver=record.solver,
            runtime_seconds=record.runtime_seconds,
            termination_condition=record.termination_condition,
            message=record.message,
        )

    data: ProcurementData = model._procurement_data
    reserve = float(pyo.value(model.R))
    return MasterSolution(
        status=record.status,
        objective=float(pyo.value(model.objective)),
        regular_cost=float(pyo.value(model.regular_cost)),
        reserve=reserve,
        reserve_ratio=reserve / data.budget if data.budget > 0 else 0.0,
        theta=float(pyo.value(model.theta)),
        regular_purchase=extract_regular_purchase(model, data),
        master_scenario_costs={
            scenario: float(pyo.value(model.scenario_cost[scenario]))
            for scenario in scenarios
        },
        scenario_names=scenarios,
        solver=record.solver,
        runtime_seconds=record.runtime_seconds,
        termination_condition=record.termination_condition,
        message=record.message,
    )


def solve_endogenous_extensive(
    data: ProcurementData,
    *,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    consistency_tolerance: float = 1.0e-6,
    tee: bool = False,
) -> ExtensiveSolution:
    """Solve the full model, then independently re-evaluate all scenarios."""

    master = solve_master(
        build_endogenous_extensive_model(data),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        tee=tee,
    )
    if master.status != "optimal":
        return ExtensiveSolution(
            status=f"master_{master.status}",
            master=master,
            evaluation=None,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    evaluation = evaluate_first_stage(
        data,
        master.regular_purchase,
        float(master.reserve),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        tee=tee,
    )
    if evaluation.status != "optimal" or evaluation.robust_objective is None:
        return ExtensiveSolution(
            status=evaluation.status,
            master=master,
            evaluation=evaluation,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    difference = abs(float(master.objective) - evaluation.robust_objective)
    status = (
        "optimal"
        if difference <= consistency_tolerance
        else "inconsistent_exact_recourse"
    )
    return ExtensiveSolution(
        status=status,
        master=master,
        evaluation=evaluation,
        consistency_difference=difference,
        tolerance=consistency_tolerance,
    )

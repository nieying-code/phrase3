"""Exact out-of-master evaluation for first-stage decisions."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

from .model_data import ProcurementData
from .recourse_model import RecourseResult, solve_recourse


@dataclass(frozen=True)
class EvaluationResult:
    status: str
    regular_cost: float
    robust_objective: float | None
    worst_scenario: str | None
    worst_recourse_cost: float | None
    scenario_results: dict[str, RecourseResult]
    infeasible_scenarios: tuple[str, ...]
    failed_scenarios: tuple[str, ...]
    runtime_seconds: float

    @property
    def exact_scenario_costs(self) -> dict[str, float]:
        return {
            name: float(result.objective)
            for name, result in self.scenario_results.items()
            if result.status == "optimal" and result.objective is not None
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "regular_cost": self.regular_cost,
            "robust_objective": self.robust_objective,
            "worst_scenario": self.worst_scenario,
            "worst_recourse_cost": self.worst_recourse_cost,
            "exact_scenario_costs": self.exact_scenario_costs,
            "infeasible_scenarios": list(self.infeasible_scenarios),
            "failed_scenarios": list(self.failed_scenarios),
            "runtime_seconds": self.runtime_seconds,
            "scenario_results": {
                name: result.as_dict()
                for name, result in self.scenario_results.items()
            },
        }


def regular_cost(
    data: ProcurementData,
    regular_purchase: Mapping[str, Sequence[float]],
) -> float:
    return sum(
        data.regular_price[item][t] * float(regular_purchase[item][t])
        for item in data.items
        for t in range(data.periods)
    )


def evaluate_first_stage(
    data: ProcurementData,
    regular_purchase: Mapping[str, Sequence[float]],
    reserve: float,
    *,
    scenario_names: Sequence[str] | None = None,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    tee: bool = False,
) -> EvaluationResult:
    """Independently re-solve every requested recourse scenario."""

    started = perf_counter()
    selected = tuple(data.scenarios if scenario_names is None else scenario_names)
    results: dict[str, RecourseResult] = {}
    for scenario in selected:
        results[scenario] = solve_recourse(
            data,
            scenario,
            regular_purchase,
            reserve,
            solver_preference=solver_preference,
            time_limit_seconds=time_limit_seconds,
            tee=tee,
        )

    infeasible = tuple(
        name for name, result in results.items()
        if result.status == "infeasible"
    )
    failed = tuple(
        name for name, result in results.items()
        if result.status not in {"optimal", "infeasible"}
    )
    first_stage_cost = regular_cost(data, regular_purchase)
    if failed:
        return EvaluationResult(
            status="oracle_failure",
            regular_cost=first_stage_cost,
            robust_objective=None,
            worst_scenario=None,
            worst_recourse_cost=None,
            scenario_results=results,
            infeasible_scenarios=infeasible,
            failed_scenarios=failed,
            runtime_seconds=perf_counter() - started,
        )
    if infeasible:
        return EvaluationResult(
            status="infeasible_recourse",
            regular_cost=first_stage_cost,
            robust_objective=None,
            worst_scenario=None,
            worst_recourse_cost=None,
            scenario_results=results,
            infeasible_scenarios=infeasible,
            failed_scenarios=(),
            runtime_seconds=perf_counter() - started,
        )

    costs = {
        name: float(result.objective)
        for name, result in results.items()
        if result.objective is not None
    }
    worst = max(selected, key=lambda name: costs[name])
    worst_cost = costs[worst]
    return EvaluationResult(
        status="optimal",
        regular_cost=first_stage_cost,
        robust_objective=first_stage_cost + worst_cost,
        worst_scenario=worst,
        worst_recourse_cost=worst_cost,
        scenario_results=results,
        infeasible_scenarios=(),
        failed_scenarios=(),
        runtime_seconds=perf_counter() - started,
    )

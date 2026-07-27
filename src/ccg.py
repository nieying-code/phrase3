"""Standard finite-scenario column-and-constraint generation."""

from __future__ import annotations

from dataclasses import dataclass
from math import inf, isfinite, sqrt
from time import perf_counter
from typing import Any, Callable, Iterable, Sequence

from .evaluation import EvaluationResult, evaluate_first_stage
from .extensive_model import MasterSolution, build_restricted_master, solve_master
from .model_data import ProcurementData


@dataclass(frozen=True)
class CCGIteration:
    iteration: int
    scenario_count: int
    added_scenario: str | None
    added_type: str | None
    lower_bound: float
    candidate_upper_bound: float | None
    global_upper_bound: float | None
    gap: float | None
    regular_cost: float
    reserve: float
    reserve_ratio: float
    master_time: float
    oracle_time: float
    infeasible_scenario_count: int
    worst_recourse_cost: float | None
    worst_scenario: str | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "iteration": self.iteration,
            "scenario_count": self.scenario_count,
            "added_scenario": self.added_scenario,
            "added_type": self.added_type,
            "LB": self.lower_bound,
            "candidate_UB": self.candidate_upper_bound,
            "global_UB": self.global_upper_bound,
            "gap": self.gap,
            "regular_cost": self.regular_cost,
            "R": self.reserve,
            "R/B": self.reserve_ratio,
            "master_time": self.master_time,
            "oracle_time": self.oracle_time,
            "infeasible_scenario_count": self.infeasible_scenario_count,
            "worst_recourse_cost": self.worst_recourse_cost,
            "worst_scenario": self.worst_scenario,
        }


@dataclass(frozen=True)
class CCGResult:
    termination_status: str
    converged: bool
    objective: float | None
    lower_bound: float | None
    upper_bound: float | None
    gap: float | None
    iterations: int
    initial_scenario_set: tuple[str, ...]
    final_scenario_set: tuple[str, ...]
    regular_purchase: dict[str, list[float]]
    reserve: float | None
    reserve_ratio: float | None
    worst_scenario: str | None
    exact_scenario_costs: dict[str, float]
    total_runtime_seconds: float
    master_runtime_seconds: float
    oracle_runtime_seconds: float
    solver: str
    iteration_log: tuple[CCGIteration, ...]
    incumbent_evaluation: EvaluationResult | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "termination_status": self.termination_status,
            "converged": self.converged,
            "objective": self.objective,
            "lower_bound": self.lower_bound,
            "upper_bound": self.upper_bound,
            "gap": self.gap,
            "iterations": self.iterations,
            "initial_scenario_set": list(self.initial_scenario_set),
            "final_scenario_set": list(self.final_scenario_set),
            "regular_purchase": self.regular_purchase,
            "reserve": self.reserve,
            "reserve_ratio": self.reserve_ratio,
            "worst_scenario": self.worst_scenario,
            "exact_scenario_costs": self.exact_scenario_costs,
            "total_runtime_seconds": self.total_runtime_seconds,
            "master_runtime_seconds": self.master_runtime_seconds,
            "oracle_runtime_seconds": self.oracle_runtime_seconds,
            "solver": self.solver,
            "iteration_log": [row.as_dict() for row in self.iteration_log],
            "incumbent_evaluation": (
                self.incumbent_evaluation.as_dict()
                if self.incumbent_evaluation is not None
                else None
            ),
        }


def _argmax(
    scenario_names: Sequence[str],
    values: dict[str, float],
) -> str:
    return max(
        scenario_names,
        key=lambda name: (values[name], -scenario_names.index(name)),
    )


def _argmin(
    scenario_names: Sequence[str],
    values: dict[str, float],
) -> str:
    return min(
        scenario_names,
        key=lambda name: (values[name], scenario_names.index(name)),
    )


def select_initial_scenarios(data: ProcurementData) -> tuple[str, ...]:
    """Select mean-nearest and three transparent stress representatives."""

    scenarios = tuple(data.scenarios)
    demand_total = {
        s: sum(
            data.demand[s][item][t]
            for item in data.items
            for t in range(data.periods)
        )
        for s in scenarios
    }
    price_average = {
        s: sum(
            data.emergency_price[s][item][t]
            for item in data.items
            for t in range(data.periods)
        )
        / (len(data.items) * data.periods)
        for s in scenarios
    }
    supply_total = {
        s: sum(
            data.emergency_supply[s][item][t]
            for item in data.items
            for t in range(data.periods)
        )
        for s in scenarios
    }

    vectors: dict[str, list[float]] = {s: [] for s in scenarios}
    for source in (data.demand, data.emergency_price, data.emergency_supply):
        for item in data.items:
            for t in range(data.periods):
                mean = sum(source[s][item][t] for s in scenarios) / len(scenarios)
                scale = max(1.0, abs(mean))
                for s in scenarios:
                    vectors[s].append((source[s][item][t] - mean) / scale)
    distance = {
        s: sqrt(sum(value * value for value in vectors[s]))
        for s in scenarios
    }
    candidates = (
        _argmin(scenarios, distance),
        _argmax(scenarios, demand_total),
        _argmax(scenarios, price_average),
        _argmin(scenarios, supply_total),
    )
    return tuple(dict.fromkeys(candidates))


def run_standard_ccg(
    data: ProcurementData,
    *,
    initial_scenarios: Sequence[str] | None = None,
    absolute_tolerance: float = 1.0e-6,
    relative_tolerance: float = 1.0e-6,
    max_iterations: int = 200,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = None,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    tee: bool = False,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> CCGResult:
    """Run serial finite-scenario C&CG with exact recourse enumeration."""

    if absolute_tolerance < 0.0 or relative_tolerance < 0.0:
        raise ValueError("C&CG tolerances must be nonnegative")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    solver_preference = tuple(solver_preference)
    if not solver_preference:
        raise ValueError("solver_preference must not be empty")
    initial = tuple(
        select_initial_scenarios(data)
        if initial_scenarios is None
        else dict.fromkeys(initial_scenarios)
    )
    if not initial:
        raise ValueError("initial_scenarios must not be empty")
    unknown = set(initial) - set(data.scenarios)
    if unknown:
        raise KeyError(f"unknown initial scenarios: {sorted(unknown)}")

    started = perf_counter()
    selected = list(initial)
    log: list[CCGIteration] = []
    global_lb = -inf
    global_ub = inf
    incumbent_master: MasterSolution | None = None
    incumbent_evaluation: EvaluationResult | None = None
    total_master_time = 0.0
    total_oracle_time = 0.0
    solver_name = "unavailable"
    termination_status = "max_iterations"
    converged = False
    effective_limit = min(max_iterations, len(data.scenarios) + 1)

    for iteration in range(1, effective_limit + 1):
        master = solve_master(
            build_restricted_master(data, selected),
            solver_preference=solver_preference,
            time_limit_seconds=time_limit_seconds,
            solver_threads=solver_threads,
            feasibility_tolerance=feasibility_tolerance,
            optimality_tolerance=optimality_tolerance,
            tee=tee,
        )
        total_master_time += master.runtime_seconds
        solver_name = master.solver
        if master.status != "optimal":
            termination_status = f"master_{master.status}"
            break

        global_lb = max(global_lb, float(master.objective))
        evaluation = evaluate_first_stage(
            data,
            master.regular_purchase,
            float(master.reserve),
            solver_preference=solver_preference,
            time_limit_seconds=time_limit_seconds,
            solver_threads=solver_threads,
            feasibility_tolerance=feasibility_tolerance,
            optimality_tolerance=optimality_tolerance,
            tee=tee,
        )
        total_oracle_time += evaluation.runtime_seconds
        added: str | None = None
        added_type: str | None = None
        candidate_ub: float | None = None
        gap: float | None = None
        worst_cost: float | None = None
        worst_scenario: str | None = None

        if evaluation.failed_scenarios:
            termination_status = "oracle_failure"
        elif evaluation.infeasible_scenarios:
            unselected = [
                name for name in evaluation.infeasible_scenarios
                if name not in selected
            ]
            if unselected:
                added = unselected[0]
                added_type = "infeasible"
                selected.append(added)
            else:
                termination_status = "inconsistent_infeasible_recourse"
        else:
            candidate_ub = float(evaluation.robust_objective)
            worst_cost = float(evaluation.worst_recourse_cost)
            worst_scenario = str(evaluation.worst_scenario)
            if candidate_ub < global_ub:
                global_ub = candidate_ub
                incumbent_master = master
                incumbent_evaluation = evaluation
            gap = global_ub - global_lb
            tolerance = (
                absolute_tolerance
                + relative_tolerance * max(1.0, abs(global_ub))
            )
            if gap <= tolerance:
                termination_status = "optimal"
                converged = True
            elif worst_scenario not in selected:
                added = worst_scenario
                added_type = "worst_cost"
                selected.append(added)
            else:
                termination_status = "inconsistent_repeated_worst_scenario"

        log.append(
            CCGIteration(
                iteration=iteration,
                scenario_count=len(selected) - (1 if added else 0),
                added_scenario=added,
                added_type=added_type,
                lower_bound=global_lb,
                candidate_upper_bound=candidate_ub,
                global_upper_bound=global_ub if isfinite(global_ub) else None,
                gap=gap,
                regular_cost=float(master.regular_cost),
                reserve=float(master.reserve),
                reserve_ratio=float(master.reserve_ratio),
                master_time=master.runtime_seconds,
                oracle_time=evaluation.runtime_seconds,
                infeasible_scenario_count=len(
                    evaluation.infeasible_scenarios
                ),
                worst_recourse_cost=worst_cost,
                worst_scenario=worst_scenario,
            )
        )
        if progress_callback is not None:
            progress_callback(
                {
                    "status": "running",
                    "iteration": iteration,
                    "termination_status": termination_status,
                    "converged": converged,
                    "initial_scenario_set": list(initial),
                    "current_scenario_set": list(selected),
                    "lower_bound": (
                        global_lb if isfinite(global_lb) else None
                    ),
                    "upper_bound": (
                        global_ub if isfinite(global_ub) else None
                    ),
                    "gap": gap,
                    "worst_scenario": worst_scenario,
                    "iteration_log": [row.as_dict() for row in log],
                }
            )
        if converged or termination_status not in {
            "max_iterations",
        }:
            if added is None:
                break
            if (
                termination_status.startswith("inconsistent")
                or termination_status == "oracle_failure"
            ):
                break

    if incumbent_master is None or incumbent_evaluation is None:
        objective = None
        upper_bound = None
        final_gap = None
        purchase: dict[str, list[float]] = {}
        reserve = None
        reserve_ratio = None
        worst_scenario = None
        exact_costs: dict[str, float] = {}
    else:
        objective = global_ub
        upper_bound = global_ub
        final_gap = global_ub - global_lb
        purchase = incumbent_master.regular_purchase
        reserve = incumbent_master.reserve
        reserve_ratio = incumbent_master.reserve_ratio
        worst_scenario = incumbent_evaluation.worst_scenario
        exact_costs = incumbent_evaluation.exact_scenario_costs

    return CCGResult(
        termination_status=termination_status,
        converged=converged,
        objective=objective,
        lower_bound=global_lb if isfinite(global_lb) else None,
        upper_bound=upper_bound,
        gap=final_gap,
        iterations=len(log),
        initial_scenario_set=initial,
        final_scenario_set=tuple(selected),
        regular_purchase=purchase,
        reserve=reserve,
        reserve_ratio=reserve_ratio,
        worst_scenario=worst_scenario,
        exact_scenario_costs=exact_costs,
        total_runtime_seconds=perf_counter() - started,
        master_runtime_seconds=total_master_time,
        oracle_runtime_seconds=total_oracle_time,
        solver=solver_name,
        iteration_log=tuple(log),
        incumbent_evaluation=incumbent_evaluation,
    )

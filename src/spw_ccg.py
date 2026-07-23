"""Scenario-pool warm-started C&CG across an ordered budget sequence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from time import perf_counter
from typing import Any, Iterable, Sequence

from .ccg import CCGResult, run_standard_ccg, select_initial_scenarios
from .model_data import ProcurementData


@dataclass(frozen=True)
class ScenarioPoolState:
    """Transferable scenario information produced after one warm solve."""

    budget: float
    final_scenario_set: tuple[str, ...]
    active_scenarios: tuple[str, ...]
    historical_adversarial_scenarios: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "final_scenario_set": list(self.final_scenario_set),
            "active_scenarios": list(self.active_scenarios),
            "historical_adversarial_scenarios": list(
                self.historical_adversarial_scenarios
            ),
        }


@dataclass(frozen=True)
class BudgetComparison:
    """Cold and scenario-pool-warm results for one budget."""

    budget: float
    execution_order: tuple[str, str]
    cold_initial_scenarios: tuple[str, ...]
    warm_initial_scenarios: tuple[str, ...]
    cold_pool_build_seconds: float
    warm_pool_build_seconds: float
    cold_result: CCGResult
    warm_result: CCGResult
    objective_difference: float
    objectives_consistent: bool
    transferred_state: ScenarioPoolState

    @property
    def cold_total_seconds(self) -> float:
        return self.cold_pool_build_seconds + self.cold_result.total_runtime_seconds

    @property
    def warm_total_seconds(self) -> float:
        return self.warm_pool_build_seconds + self.warm_result.total_runtime_seconds

    @property
    def iteration_reduction(self) -> int:
        return self.cold_result.iterations - self.warm_result.iterations

    @property
    def runtime_reduction_seconds(self) -> float:
        return self.cold_total_seconds - self.warm_total_seconds

    def as_dict(self) -> dict[str, Any]:
        return {
            "budget": self.budget,
            "execution_order": list(self.execution_order),
            "cold_initial_scenarios": list(self.cold_initial_scenarios),
            "warm_initial_scenarios": list(self.warm_initial_scenarios),
            "cold_pool_build_seconds": self.cold_pool_build_seconds,
            "warm_pool_build_seconds": self.warm_pool_build_seconds,
            "cold_total_seconds": self.cold_total_seconds,
            "warm_total_seconds": self.warm_total_seconds,
            "iteration_reduction": self.iteration_reduction,
            "runtime_reduction_seconds": self.runtime_reduction_seconds,
            "objective_difference": self.objective_difference,
            "objectives_consistent": self.objectives_consistent,
            "cold_result": self.cold_result.as_dict(),
            "warm_result": self.warm_result.as_dict(),
            "transferred_state": self.transferred_state.as_dict(),
        }


@dataclass(frozen=True)
class SPWCCGResult:
    """Complete cross-budget cold-versus-warm experiment."""

    status: str
    budgets: tuple[float, ...]
    comparisons: tuple[BudgetComparison, ...]
    active_scenario_tolerance: float
    objective_absolute_tolerance: float
    objective_relative_tolerance: float
    alternate_execution_order: bool

    @property
    def total_cold_seconds(self) -> float:
        return sum(row.cold_total_seconds for row in self.comparisons)

    @property
    def total_warm_seconds(self) -> float:
        return sum(row.warm_total_seconds for row in self.comparisons)

    @property
    def total_iteration_reduction(self) -> int:
        return sum(row.iteration_reduction for row in self.comparisons)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "budgets": list(self.budgets),
            "active_scenario_tolerance": self.active_scenario_tolerance,
            "objective_absolute_tolerance": self.objective_absolute_tolerance,
            "objective_relative_tolerance": self.objective_relative_tolerance,
            "alternate_execution_order": self.alternate_execution_order,
            "total_cold_seconds": self.total_cold_seconds,
            "total_warm_seconds": self.total_warm_seconds,
            "total_iteration_reduction": self.total_iteration_reduction,
            "comparisons": [row.as_dict() for row in self.comparisons],
        }


def _ordered_union(
    data: ProcurementData,
    *groups: Sequence[str],
) -> tuple[str, ...]:
    requested = {name for group in groups for name in group}
    unknown = requested - set(data.scenarios)
    if unknown:
        raise KeyError(f"unknown scenarios in transferred pool: {sorted(unknown)}")
    return tuple(name for name in data.scenarios if name in requested)


def identify_active_scenarios(
    data: ProcurementData,
    result: CCGResult,
    *,
    tolerance: float,
) -> tuple[str, ...]:
    """Return scenarios whose exact recourse cost is near the worst cost."""

    if tolerance < 0.0:
        raise ValueError("active-scenario tolerance must be nonnegative")
    if not result.converged or result.incumbent_evaluation is None:
        raise ValueError("active scenarios require a converged C&CG result")
    costs = result.exact_scenario_costs
    if set(costs) != set(data.scenarios):
        raise ValueError("active-scenario detection requires exact costs for all scenarios")
    worst_cost = max(costs.values())
    return tuple(
        scenario
        for scenario in data.scenarios
        if worst_cost - costs[scenario] <= tolerance
    )


def build_warm_initial_scenarios(
    data: ProcurementData,
    previous_state: ScenarioPoolState | None,
) -> tuple[str, ...]:
    """Build the exact warm pool without pruning the full oracle."""

    base = select_initial_scenarios(data)
    if previous_state is None:
        return base
    return _ordered_union(
        data,
        base,
        previous_state.active_scenarios,
        previous_state.historical_adversarial_scenarios,
    )


def build_transferred_state(
    data: ProcurementData,
    *,
    budget: float,
    result: CCGResult,
    previous_state: ScenarioPoolState | None,
    active_scenario_tolerance: float,
) -> ScenarioPoolState:
    """Record final, active, and cumulative adversarial scenario sets."""

    active = identify_active_scenarios(
        data,
        result,
        tolerance=active_scenario_tolerance,
    )
    newly_adversarial = tuple(
        row.added_scenario
        for row in result.iteration_log
        if row.added_scenario is not None
        and row.added_type in {"infeasible", "worst_cost"}
    )
    if result.worst_scenario is not None:
        newly_adversarial = (*newly_adversarial, result.worst_scenario)
    previous_history = (
        ()
        if previous_state is None
        else previous_state.historical_adversarial_scenarios
    )
    history = _ordered_union(data, previous_history, newly_adversarial)
    return ScenarioPoolState(
        budget=float(budget),
        final_scenario_set=tuple(result.final_scenario_set),
        active_scenarios=active,
        historical_adversarial_scenarios=history,
    )


def run_spw_ccg_budget_sequence(
    data: ProcurementData,
    budgets: Sequence[float],
    *,
    active_scenario_tolerance: float = 1.0e-6,
    objective_absolute_tolerance: float = 1.0e-6,
    objective_relative_tolerance: float = 1.0e-6,
    ccg_absolute_tolerance: float = 1.0e-6,
    ccg_relative_tolerance: float = 1.0e-6,
    max_iterations: int = 200,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    alternate_execution_order: bool = True,
    tee: bool = False,
) -> SPWCCGResult:
    """Compare cold and scenario-pool-warm C&CG for increasing budgets."""

    ordered_budgets = tuple(float(value) for value in budgets)
    if not ordered_budgets:
        raise ValueError("at least one budget is required")
    if any(value <= 0.0 for value in ordered_budgets):
        raise ValueError("budgets must be positive")
    if any(
        current <= previous
        for previous, current in zip(ordered_budgets, ordered_budgets[1:])
    ):
        raise ValueError("budgets must be strictly increasing")
    if active_scenario_tolerance < 0.0:
        raise ValueError("active_scenario_tolerance must be nonnegative")
    if objective_absolute_tolerance < 0.0 or objective_relative_tolerance < 0.0:
        raise ValueError("objective consistency tolerances must be nonnegative")

    solver_kwargs = {
        "absolute_tolerance": ccg_absolute_tolerance,
        "relative_tolerance": ccg_relative_tolerance,
        "max_iterations": max_iterations,
        "solver_preference": solver_preference,
        "time_limit_seconds": time_limit_seconds,
        "feasibility_tolerance": feasibility_tolerance,
        "optimality_tolerance": optimality_tolerance,
        "tee": tee,
    }
    comparisons: list[BudgetComparison] = []
    previous_state: ScenarioPoolState | None = None
    overall_status = "optimal"

    for index, budget in enumerate(ordered_budgets):
        budget_data = replace(data, budget=budget)
        budget_data.validate()

        cold_pool_started = perf_counter()
        cold_initial = select_initial_scenarios(budget_data)
        cold_pool_seconds = perf_counter() - cold_pool_started

        warm_pool_started = perf_counter()
        warm_initial = build_warm_initial_scenarios(
            budget_data,
            previous_state,
        )
        warm_pool_seconds = perf_counter() - warm_pool_started

        def solve(initial: Sequence[str]) -> CCGResult:
            return run_standard_ccg(
                budget_data,
                initial_scenarios=initial,
                **solver_kwargs,
            )

        if not alternate_execution_order or index % 2 == 0:
            execution_order = ("cold", "warm")
            cold = solve(cold_initial)
            warm = solve(warm_initial)
        else:
            execution_order = ("warm", "cold")
            warm = solve(warm_initial)
            cold = solve(cold_initial)

        if not cold.converged or not warm.converged:
            raise RuntimeError(
                f"C&CG did not converge at budget {budget}: "
                f"cold={cold.termination_status}, warm={warm.termination_status}"
            )
        if cold.objective is None or warm.objective is None:
            raise RuntimeError(f"missing robust objective at budget {budget}")

        difference = abs(float(cold.objective) - float(warm.objective))
        consistency_limit = (
            objective_absolute_tolerance
            + objective_relative_tolerance
            * max(
                1.0,
                abs(float(cold.objective)),
                abs(float(warm.objective)),
            )
        )
        consistent = difference <= consistency_limit
        if not consistent:
            overall_status = "inconsistent_cold_warm_objectives"

        state = build_transferred_state(
            budget_data,
            budget=budget,
            result=warm,
            previous_state=previous_state,
            active_scenario_tolerance=active_scenario_tolerance,
        )
        comparisons.append(
            BudgetComparison(
                budget=budget,
                execution_order=execution_order,
                cold_initial_scenarios=cold_initial,
                warm_initial_scenarios=warm_initial,
                cold_pool_build_seconds=cold_pool_seconds,
                warm_pool_build_seconds=warm_pool_seconds,
                cold_result=cold,
                warm_result=warm,
                objective_difference=difference,
                objectives_consistent=consistent,
                transferred_state=state,
            )
        )
        previous_state = state

    return SPWCCGResult(
        status=overall_status,
        budgets=ordered_budgets,
        comparisons=tuple(comparisons),
        active_scenario_tolerance=active_scenario_tolerance,
        objective_absolute_tolerance=objective_absolute_tolerance,
        objective_relative_tolerance=objective_relative_tolerance,
        alternate_execution_order=alternate_execution_order,
    )

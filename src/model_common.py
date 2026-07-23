"""Shared Pyomo construction and solver-status utilities for phase 3."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from .model_data import ProcurementData


OPTIMAL_TERMINATIONS = {
    TerminationCondition.optimal,
    TerminationCondition.globallyOptimal,
    TerminationCondition.locallyOptimal,
}
INFEASIBLE_TERMINATIONS = {
    TerminationCondition.infeasible,
}
TIME_LIMIT_TERMINATIONS = {
    TerminationCondition.maxTimeLimit,
    TerminationCondition.maxIterations,
}


@dataclass(frozen=True)
class SolveRecord:
    """Normalized result of one solver invocation."""

    status: str
    solver: str
    runtime_seconds: float
    termination_condition: str
    message: str | None = None


def select_solver(preference: Iterable[str]) -> tuple[str, Any]:
    """Return the first available solver in the requested order."""

    aliases = {
        "highs": ("appsi_highs", "highs"),
        "gurobi": ("gurobi",),
    }
    attempted: list[str] = []
    for requested in preference:
        for name in aliases.get(str(requested), (str(requested),)):
            attempted.append(name)
            solver = pyo.SolverFactory(name)
            try:
                if solver is not None and solver.available(exception_flag=False):
                    return name, solver
            except Exception:
                continue
    raise RuntimeError(f"no requested solver is available; attempted {attempted}")


def solve_with_status(
    model: pyo.ConcreteModel,
    *,
    solver_preference: Iterable[str] = ("gurobi", "highs"),
    time_limit_seconds: float = 600.0,
    feasibility_tolerance: float | None = None,
    optimality_tolerance: float | None = None,
    tee: bool = False,
) -> SolveRecord:
    """Solve a Pyomo model without conflating failures and infeasibility."""

    started = perf_counter()
    for name, value in (
        ("feasibility_tolerance", feasibility_tolerance),
        ("optimality_tolerance", optimality_tolerance),
    ):
        if value is not None and float(value) <= 0.0:
            return SolveRecord(
                status="solver_error",
                solver="unavailable",
                runtime_seconds=perf_counter() - started,
                termination_condition="invalid_solver_option",
                message=f"{name} must be positive",
            )
    try:
        solver_name, solver = select_solver(solver_preference)
    except Exception as exc:
        return SolveRecord(
            status="solver_error",
            solver="unavailable",
            runtime_seconds=perf_counter() - started,
            termination_condition="solver_unavailable",
            message=str(exc),
        )

    if solver_name in {"appsi_highs", "highs"}:
        solver.options["time_limit"] = float(time_limit_seconds)
        if feasibility_tolerance is not None:
            solver.options["primal_feasibility_tolerance"] = float(
                feasibility_tolerance
            )
            solver.options["mip_feasibility_tolerance"] = float(
                feasibility_tolerance
            )
        if optimality_tolerance is not None:
            solver.options["dual_feasibility_tolerance"] = float(
                optimality_tolerance
            )
    elif solver_name == "gurobi":
        solver.options["TimeLimit"] = float(time_limit_seconds)
        if feasibility_tolerance is not None:
            solver.options["FeasibilityTol"] = float(feasibility_tolerance)
        if optimality_tolerance is not None:
            solver.options["OptimalityTol"] = float(optimality_tolerance)

    try:
        # Do not ask Pyomo to load a solution before inspecting termination.
        # In particular, appsi_highs raises NoFeasibleSolutionError for both
        # true infeasibility and time limits with no incumbent when automatic
        # loading is enabled.  The termination condition is the authoritative
        # distinction.
        result = solver.solve(model, tee=tee, load_solutions=False)
    except Exception as exc:
        return SolveRecord(
            status="solver_error",
            solver=solver_name,
            runtime_seconds=perf_counter() - started,
            termination_condition=type(exc).__name__,
            message=str(exc),
        )

    termination = result.solver.termination_condition
    solver_status = result.solver.status
    if termination in OPTIMAL_TERMINATIONS:
        try:
            model.solutions.load_from(result)
        except Exception as exc:
            return SolveRecord(
                status="solver_error",
                solver=solver_name,
                runtime_seconds=perf_counter() - started,
                termination_condition="solution_load_error",
                message=str(exc),
            )
        status = "optimal"
    elif termination in INFEASIBLE_TERMINATIONS:
        status = "infeasible"
    elif termination in TIME_LIMIT_TERMINATIONS:
        status = "time_limit"
    elif solver_status == SolverStatus.error:
        status = "solver_error"
    else:
        status = "unknown"
    return SolveRecord(
        status=status,
        solver=solver_name,
        runtime_seconds=perf_counter() - started,
        termination_condition=str(termination),
        message=None,
    )


def _validate_purchase(
    data: ProcurementData,
    regular_purchase: Mapping[str, Sequence[float]],
) -> None:
    for item in data.items:
        if item not in regular_purchase:
            raise KeyError(f"regular_purchase is missing item {item}")
        values = regular_purchase[item]
        if len(values) != data.periods:
            raise ValueError(f"regular_purchase[{item}] length must equal periods")
        if any(float(value) < 0.0 for value in values):
            raise ValueError("regular_purchase values must be nonnegative")


def build_inventory_model(
    data: ProcurementData,
    *,
    scenario_names: Sequence[str] | None = None,
    model_name: str,
    reserve_policy: str,
    fixed_reserve_ratio: float | None = None,
    regular_purchase: Mapping[str, Sequence[float]] | None = None,
    reserve: float | None = None,
    objective_kind: str = "robust",
) -> pyo.ConcreteModel:
    """Build one canonical age-indexed model for masters and recourse oracles.

    ``reserve_policy`` is one of ``endogenous``, ``fixed_ratio``, or
    ``fixed_first_stage``.  The latter fixes both ``y`` and ``R`` and is used
    by the independent single-scenario recourse model.
    """

    data.validate()
    selected = tuple(data.scenarios if scenario_names is None else scenario_names)
    if not selected:
        raise ValueError("at least one scenario is required")
    unknown = set(selected) - set(data.scenarios)
    if unknown:
        raise KeyError(f"unknown scenarios: {sorted(unknown)}")
    if len(set(selected)) != len(selected):
        raise ValueError("scenario_names must not contain duplicates")
    if reserve_policy not in {"endogenous", "fixed_ratio", "fixed_first_stage"}:
        raise ValueError(f"unknown reserve_policy: {reserve_policy}")
    if objective_kind not in {"robust", "recourse"}:
        raise ValueError(f"unknown objective_kind: {objective_kind}")
    if objective_kind == "recourse" and len(selected) != 1:
        raise ValueError("recourse objective requires exactly one scenario")

    model = pyo.ConcreteModel(name=model_name)
    model.K = pyo.Set(initialize=data.items, ordered=True)
    model.T = pyo.RangeSet(0, data.periods - 1)
    model.S = pyo.Set(initialize=selected, ordered=True)
    model.KTA = pyo.Set(
        dimen=3,
        initialize=[
            (item, t, age)
            for item in data.items
            for t in range(data.periods)
            for age in range(data.shelf_life[item])
        ],
        ordered=True,
    )

    model.y = pyo.Var(model.K, model.T, domain=pyo.NonNegativeReals)
    model.R = pyo.Var(domain=pyo.NonNegativeReals)
    model.theta = pyo.Var(domain=pyo.NonNegativeReals)
    model.q = pyo.Var(model.S, model.K, model.T, domain=pyo.NonNegativeReals)
    model.available = pyo.Var(model.S, model.KTA, domain=pyo.NonNegativeReals)
    model.consume = pyo.Var(model.S, model.KTA, domain=pyo.NonNegativeReals)
    model.inventory = pyo.Var(model.S, model.KTA, domain=pyo.NonNegativeReals)
    model.shortage = pyo.Var(model.S, model.K, model.T, domain=pyo.NonNegativeReals)
    model.waste = pyo.Var(model.S, model.K, model.T, domain=pyo.NonNegativeReals)

    model.regular_cost = pyo.Expression(
        expr=sum(
            data.regular_price[item][t] * model.y[item, t]
            for item in data.items
            for t in range(data.periods)
        )
    )

    if reserve_policy == "endogenous":
        model.reserve_rule = pyo.Constraint(
            expr=model.regular_cost + model.R == data.budget
        )
    elif reserve_policy == "fixed_ratio":
        if fixed_reserve_ratio is None or not 0.0 <= fixed_reserve_ratio <= 1.0:
            raise ValueError("fixed_reserve_ratio must be in [0, 1]")
        reserve_value = float(fixed_reserve_ratio) * data.budget
        model.R.fix(reserve_value)
        model.reserve_rule = pyo.Constraint(
            expr=model.regular_cost <= data.budget - reserve_value
        )
    else:
        if regular_purchase is None or reserve is None:
            raise ValueError(
                "fixed_first_stage requires regular_purchase and reserve"
            )
        _validate_purchase(data, regular_purchase)
        if float(reserve) < 0.0:
            raise ValueError("reserve must be nonnegative")
        committed = sum(
            data.regular_price[item][t] * float(regular_purchase[item][t])
            for item in data.items
            for t in range(data.periods)
        )
        if committed + float(reserve) > data.budget + 1.0e-7:
            raise ValueError(
                "fixed first-stage regular cost plus reserve exceeds budget"
            )
        for item in data.items:
            for t in range(data.periods):
                model.y[item, t].fix(float(regular_purchase[item][t]))
        model.R.fix(float(reserve))

    model.emergency_supply_limit = pyo.Constraint(
        model.S,
        model.K,
        model.T,
        rule=lambda m, scenario, item, t: (
            m.q[scenario, item, t]
            <= data.emergency_supply[scenario][item][t]
        ),
    )

    model.emergency_budget = pyo.Constraint(
        model.S,
        rule=lambda m, scenario: (
            sum(
                data.emergency_price[scenario][item][t]
                * m.q[scenario, item, t]
                for item in data.items
                for t in range(data.periods)
            )
            <= m.R
        ),
    )

    def available_rule(
        m: pyo.ConcreteModel,
        scenario: str,
        item: str,
        t: int,
        age: int,
    ):
        if age == 0:
            initial = data.initial_inventory[item][0] if t == 0 else 0.0
            return (
                m.available[scenario, item, t, age]
                == m.y[item, t] + m.q[scenario, item, t] + initial
            )
        if t == 0:
            return (
                m.available[scenario, item, t, age]
                == data.initial_inventory[item][age]
            )
        return (
            m.available[scenario, item, t, age]
            == m.inventory[scenario, item, t - 1, age - 1]
        )

    model.available_balance = pyo.Constraint(
        model.S, model.KTA, rule=available_rule
    )

    def age_flow_rule(
        m: pyo.ConcreteModel,
        scenario: str,
        item: str,
        t: int,
        age: int,
    ):
        if age == data.shelf_life[item] - 1:
            return (
                m.available[scenario, item, t, age]
                == m.consume[scenario, item, t, age]
                + m.waste[scenario, item, t]
            )
        return (
            m.available[scenario, item, t, age]
            == m.consume[scenario, item, t, age]
            + m.inventory[scenario, item, t, age]
        )

    model.age_flow = pyo.Constraint(model.S, model.KTA, rule=age_flow_rule)
    model.expired_inventory_zero = pyo.Constraint(
        model.S,
        model.K,
        model.T,
        rule=lambda m, scenario, item, t: (
            m.inventory[
                scenario, item, t, data.shelf_life[item] - 1
            ]
            == 0
        ),
    )
    model.demand_balance = pyo.Constraint(
        model.S,
        model.K,
        model.T,
        rule=lambda m, scenario, item, t: (
            sum(
                m.consume[scenario, item, t, age]
                for age in range(data.shelf_life[item])
            )
            + m.shortage[scenario, item, t]
            == data.demand[scenario][item][t]
        ),
    )

    def storage_rule(m: pyo.ConcreteModel, scenario: str, t: int):
        surviving = [
            m.inventory[scenario, item, t, age]
            for item in data.items
            for age in range(data.shelf_life[item] - 1)
        ]
        if not surviving:
            return pyo.Constraint.Feasible
        return sum(surviving) <= data.storage_capacity[t]

    model.storage_capacity = pyo.Constraint(model.S, model.T, rule=storage_rule)
    model.emergency_spend = pyo.Expression(
        model.S,
        rule=lambda m, scenario: sum(
            data.emergency_price[scenario][item][t]
            * m.q[scenario, item, t]
            for item in data.items
            for t in range(data.periods)
        ),
    )
    model.scenario_cost = pyo.Expression(
        model.S,
        rule=lambda m, scenario: sum(
            data.emergency_price[scenario][item][t]
            * m.q[scenario, item, t]
            + data.shortage_penalty[item]
            * m.shortage[scenario, item, t]
            + data.waste_penalty[item] * m.waste[scenario, item, t]
            for item in data.items
            for t in range(data.periods)
        ),
    )

    if objective_kind == "robust":
        model.worst_case_epigraph = pyo.Constraint(
            model.S,
            rule=lambda m, scenario: (
                m.theta >= m.scenario_cost[scenario]
            ),
        )
        model.objective = pyo.Objective(
            expr=model.regular_cost + model.theta,
            sense=pyo.minimize,
        )
    else:
        scenario = selected[0]
        model.theta.fix(0.0)
        model.objective = pyo.Objective(
            expr=model.scenario_cost[scenario],
            sense=pyo.minimize,
        )

    model._procurement_data = data
    model._scenario_names = selected
    model._model_name = model_name
    model._reserve_policy = reserve_policy
    model._objective_kind = objective_kind
    return model


def extract_regular_purchase(
    model: pyo.ConcreteModel,
    data: ProcurementData,
) -> dict[str, list[float]]:
    return {
        item: [
            float(pyo.value(model.y[item, t]))
            for t in range(data.periods)
        ]
        for item in data.items
    }


def extract_item_time(
    variable: Any,
    *,
    data: ProcurementData,
    prefix: tuple[Any, ...],
) -> list[float]:
    return [
        float(pyo.value(variable[(*prefix, t)]))
        for t in range(data.periods)
    ]

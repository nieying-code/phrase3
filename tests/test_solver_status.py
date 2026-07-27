from __future__ import annotations

from types import SimpleNamespace

import pyomo.environ as pyo
from pyomo.opt import SolverStatus, TerminationCondition

from src import model_common


def _empty_model() -> pyo.ConcreteModel:
    model = pyo.ConcreteModel()
    model.x = pyo.Var(domain=pyo.NonNegativeReals)
    model.objective = pyo.Objective(expr=model.x)
    return model


def test_highs_infeasibility_uses_termination_condition() -> None:
    model = _empty_model()
    model.lower = pyo.Constraint(expr=model.x >= 1.0)
    model.upper = pyo.Constraint(expr=model.x <= 0.0)

    record = model_common.solve_with_status(
        model,
        solver_preference=("highs",),
    )

    assert record.status == "infeasible"
    assert record.termination_condition == "infeasible"


def test_highs_unbounded_model_is_classified_explicitly() -> None:
    model = _empty_model()
    model.objective.set_value(-model.x)

    record = model_common.solve_with_status(
        model,
        solver_preference=("highs",),
    )

    assert record.status == "unbounded"
    assert record.termination_condition == "unbounded"


def test_infeasible_or_unbounded_is_not_collapsed_to_solver_error(
    monkeypatch,
) -> None:
    class AmbiguousSolver:
        options: dict[str, float] = {}

        def solve(self, model, **kwargs):
            return SimpleNamespace(
                solver=SimpleNamespace(
                    termination_condition=(
                        TerminationCondition.infeasibleOrUnbounded
                    ),
                    status=SolverStatus.warning,
                )
            )

    monkeypatch.setattr(
        model_common,
        "select_solver",
        lambda preference: ("appsi_highs", AmbiguousSolver()),
    )

    record = model_common.solve_with_status(_empty_model())

    assert record.status == "infeasible_or_unbounded"
    assert record.termination_condition == "infeasibleOrUnbounded"


def test_no_feasible_solution_exception_is_not_guessed_infeasible(
    monkeypatch,
) -> None:
    class NoFeasibleSolutionError(Exception):
        pass

    class RaisingSolver:
        options: dict[str, float] = {}

        def solve(self, model, **kwargs):
            raise NoFeasibleSolutionError(
                "A feasible solution was not found, so no solution can be loaded"
            )

    monkeypatch.setattr(
        model_common,
        "select_solver",
        lambda preference: ("appsi_highs", RaisingSolver()),
    )

    record = model_common.solve_with_status(_empty_model())

    assert record.status == "solver_error"
    assert record.termination_condition == "NoFeasibleSolutionError"


def test_time_limit_and_configured_highs_tolerances(monkeypatch) -> None:
    class RecordingSolver:
        def __init__(self) -> None:
            self.options: dict[str, float] = {}
            self.solve_kwargs: dict[str, object] = {}

        def solve(self, model, **kwargs):
            self.solve_kwargs = kwargs
            return SimpleNamespace(
                solver=SimpleNamespace(
                    termination_condition=TerminationCondition.maxTimeLimit,
                    status=SolverStatus.ok,
                )
            )

    solver = RecordingSolver()
    monkeypatch.setattr(
        model_common,
        "select_solver",
        lambda preference: ("appsi_highs", solver),
    )

    record = model_common.solve_with_status(
        _empty_model(),
        time_limit_seconds=12.0,
        solver_threads=1,
        feasibility_tolerance=2.0e-7,
        optimality_tolerance=3.0e-7,
    )

    assert record.status == "time_limit"
    assert solver.solve_kwargs["load_solutions"] is False
    assert solver.options == {
        "time_limit": 12.0,
        "threads": 1,
        "primal_feasibility_tolerance": 2.0e-7,
        "mip_feasibility_tolerance": 2.0e-7,
        "dual_feasibility_tolerance": 3.0e-7,
    }


def test_nonpositive_solver_thread_count_is_rejected() -> None:
    record = model_common.solve_with_status(
        _empty_model(),
        solver_threads=0,
    )

    assert record.status == "solver_error"
    assert record.termination_condition == "invalid_solver_option"
    assert "solver_threads" in record.message

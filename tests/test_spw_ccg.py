from __future__ import annotations

from dataclasses import replace
import math

import pytest

from src.scenario_generator import generate_synthetic_data, load_config
import src.spw_ccg as spw_ccg_module
from src.ccg import run_standard_ccg
from src.spw_ccg import (
    run_spw_ccg_budget_sequence,
)


def _phase3_data():
    return generate_synthetic_data(load_config("configs/phase3.yaml"))


@pytest.fixture(scope="module")
def three_budget_result():
    data = _phase3_data()
    result = run_spw_ccg_budget_sequence(
        data,
        (900.0, 1000.0, 1100.0),
        solver_preference=("gurobi",),
        time_limit_seconds=60.0,
        feasibility_tolerance=1.0e-7,
        optimality_tolerance=1.0e-7,
    )
    return data, result


def test_spw_ccg_matches_cold_start_across_budgets(
    three_budget_result,
) -> None:
    data, result = three_budget_result

    assert result.status == "optimal"
    assert len(result.comparisons) == 3
    assert result.comparisons[0].execution_order == ("cold", "warm")
    assert result.comparisons[1].execution_order == ("warm", "cold")
    assert result.comparisons[2].execution_order == ("cold", "warm")
    for row in result.comparisons:
        assert row.cold_result.converged
        assert row.warm_result.converged
        assert row.objectives_consistent
        assert set(row.cold_result.exact_scenario_costs) == set(data.scenarios)
        assert set(row.warm_result.exact_scenario_costs) == set(data.scenarios)
        assert math.isclose(
            float(row.cold_result.objective),
            float(row.warm_result.objective),
            rel_tol=1.0e-7,
            abs_tol=1.0e-6,
        )
        assert len(row.warm_initial_scenarios) == len(
            set(row.warm_initial_scenarios)
        )


def test_transferred_pool_is_independent_cumulative_union(
    three_budget_result,
) -> None:
    data, result = three_budget_result
    cumulative_history: set[str] = set()

    for index, comparison in enumerate(result.comparisons):
        if index == 0:
            assert (
                comparison.warm_initial_scenarios
                == comparison.cold_initial_scenarios
            )
        else:
            previous = result.comparisons[index - 1].transferred_state
            requested = {
                *comparison.cold_initial_scenarios,
                *previous.active_scenarios,
                *previous.historical_adversarial_scenarios,
            }
            expected_warm = tuple(
                scenario for scenario in data.scenarios if scenario in requested
            )
            assert comparison.warm_initial_scenarios == expected_warm
            assert set(previous.historical_adversarial_scenarios) <= set(
                comparison.transferred_state.historical_adversarial_scenarios
            )

        costs = comparison.warm_result.exact_scenario_costs
        worst_cost = max(costs.values())
        expected_active = tuple(
            scenario
            for scenario in data.scenarios
            if worst_cost - costs[scenario]
            <= result.active_scenario_tolerance
        )
        assert comparison.transferred_state.active_scenarios == expected_active

        cumulative_history.update(
            entry.added_scenario
            for entry in comparison.warm_result.iteration_log
            if entry.added_scenario is not None
            and entry.added_type in {"infeasible", "worst_cost"}
        )
        if comparison.warm_result.worst_scenario is not None:
            cumulative_history.add(comparison.warm_result.worst_scenario)
        expected_history = tuple(
            scenario
            for scenario in data.scenarios
            if scenario in cumulative_history
        )
        assert (
            comparison.transferred_state.historical_adversarial_scenarios
            == expected_history
        )


def test_inconsistent_objectives_cannot_report_optimal(
    three_budget_result,
    monkeypatch,
) -> None:
    data, result = three_budget_result
    template = result.comparisons[0].warm_result
    returned_results = iter(
        (
            replace(template, objective=100.0),
            replace(template, objective=101.0),
        )
    )
    monkeypatch.setattr(
        spw_ccg_module,
        "run_standard_ccg",
        lambda *args, **kwargs: next(returned_results),
    )

    inconsistent = run_spw_ccg_budget_sequence(
        data,
        (900.0,),
        solver_preference=("gurobi",),
        objective_absolute_tolerance=0.0,
        objective_relative_tolerance=0.0,
    )

    assert inconsistent.status == "inconsistent_cold_warm_objectives"
    assert not inconsistent.comparisons
    assert inconsistent.failure is not None
    assert inconsistent.failure.stage == "comparison"
    assert inconsistent.failure.cold_result is not None
    assert inconsistent.failure.warm_result is not None


def test_solver_exception_is_returned_as_failure(monkeypatch) -> None:
    data = _phase3_data()

    def raise_timeout(*args, **kwargs):
        raise TimeoutError("synthetic timeout")

    monkeypatch.setattr(
        spw_ccg_module,
        "run_standard_ccg",
        raise_timeout,
    )

    failed = run_spw_ccg_budget_sequence(
        data,
        (900.0,),
        solver_preference=("gurobi",),
    )

    assert failed.status == "cold_exception"
    assert failed.failure is not None
    assert failed.failure.stage == "cold"
    assert failed.failure.exception_type == "TimeoutError"
    assert "synthetic timeout" in failed.failure.message


def test_budget_sequence_must_be_strictly_increasing() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        run_spw_ccg_budget_sequence(
            _phase3_data(),
            (1000.0, 900.0),
            solver_preference=("gurobi",),
        )


def test_solver_preference_generator_is_reusable() -> None:
    data = _phase3_data()

    standard = run_standard_ccg(
        data,
        solver_preference=(name for name in ("gurobi",)),
        time_limit_seconds=60.0,
    )
    warm_started = run_spw_ccg_budget_sequence(
        data,
        (900.0, 1000.0),
        solver_preference=(name for name in ("gurobi",)),
        time_limit_seconds=60.0,
    )

    assert standard.converged
    assert warm_started.status == "optimal"
    assert len(warm_started.comparisons) == 2

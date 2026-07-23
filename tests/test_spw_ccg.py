from __future__ import annotations

import math

import pytest

from src.scenario_generator import generate_synthetic_data, load_config
from src.spw_ccg import (
    build_warm_initial_scenarios,
    run_spw_ccg_budget_sequence,
)


def _phase3_data():
    return generate_synthetic_data(load_config("configs/phase3.yaml"))


def test_spw_ccg_matches_cold_start_across_budgets() -> None:
    data = _phase3_data()
    result = run_spw_ccg_budget_sequence(
        data,
        (900.0, 1000.0),
        solver_preference=("highs",),
        time_limit_seconds=60.0,
        feasibility_tolerance=1.0e-7,
        optimality_tolerance=1.0e-7,
    )

    assert result.status == "optimal"
    assert len(result.comparisons) == 2
    assert result.comparisons[0].execution_order == ("cold", "warm")
    assert result.comparisons[1].execution_order == ("warm", "cold")
    for row in result.comparisons:
        assert row.cold_result.converged
        assert row.warm_result.converged
        assert row.objectives_consistent
        assert math.isclose(
            float(row.cold_result.objective),
            float(row.warm_result.objective),
            rel_tol=1.0e-7,
            abs_tol=1.0e-6,
        )
        assert len(row.warm_initial_scenarios) == len(
            set(row.warm_initial_scenarios)
        )


def test_transferred_pool_contains_base_active_and_history() -> None:
    data = _phase3_data()
    result = run_spw_ccg_budget_sequence(
        data,
        (900.0, 1000.0),
        solver_preference=("highs",),
        time_limit_seconds=60.0,
    )
    first_state = result.comparisons[0].transferred_state
    expected = build_warm_initial_scenarios(data, first_state)
    second = result.comparisons[1]

    assert second.warm_initial_scenarios == expected
    assert set(first_state.active_scenarios) <= set(expected)
    assert set(first_state.historical_adversarial_scenarios) <= set(expected)
    assert set(first_state.active_scenarios) <= set(data.scenarios)
    assert set(first_state.historical_adversarial_scenarios) <= set(
        data.scenarios
    )


def test_budget_sequence_must_be_strictly_increasing() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        run_spw_ccg_budget_sequence(
            _phase3_data(),
            (1000.0, 900.0),
            solver_preference=("highs",),
        )

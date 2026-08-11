from __future__ import annotations

from dataclasses import fields, replace
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.extensive_model import solve_endogenous_extensive
from src.model_data import ProcurementData
import src.phase6_m1 as m1
from src.phase6_m1 import (
    CappedProcurementData,
    M1ProtocolError,
    RegularProcurementCap,
    analyze_reserve_interval,
    apply_regular_procurement_cap,
    build_fixed_autonomous_reserve_model,
    fixed_autonomous_reserve_amount,
    generate_m1_data,
    load_m1_config,
    resolve_regular_procurement_cap,
    solve_fixed_autonomous_reserve,
    solve_m1_endogenous_extensive,
    solve_minimum_feasible_reserve,
    run_m1_spw_ccg_budget_sequence,
    run_m1_standard_ccg,
)


ROOT = Path(__file__).resolve().parents[1]


def base_data(*, budget: float = 10.0) -> ProcurementData:
    data = ProcurementData(
        items=("food",),
        periods=1,
        scenarios=("low", "high"),
        budget=budget,
        shelf_life={"food": 1},
        initial_inventory={"food": (0.0,)},
        storage_capacity=(100.0,),
        regular_price={"food": (1.0,)},
        demand={
            "low": {"food": (4.0,)},
            "high": {"food": (8.0,)},
        },
        emergency_price={
            "low": {"food": (2.0,)},
            "high": {"food": (2.0,)},
        },
        emergency_supply={
            "low": {"food": (10.0,)},
            "high": {"food": (10.0,)},
        },
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def capped_data(
    *,
    budget: float = 10.0,
    capacity: float = 4.0,
) -> CappedProcurementData:
    original = base_data(budget=budget)
    values = {
        field.name: getattr(original, field.name)
        for field in fields(ProcurementData)
    }
    result = CappedProcurementData(
        **values,
        regular_procurement_capacity={"food": (capacity,)},
        regular_procurement_cap_kappa=1.0,
    )
    result.validate()
    return result


def degenerate_data() -> ProcurementData:
    data = ProcurementData(
        items=("food",),
        periods=1,
        scenarios=("only",),
        budget=10.0,
        shelf_life={"food": 1},
        initial_inventory={"food": (0.0,)},
        storage_capacity=(100.0,),
        regular_price={"food": (1.0,)},
        demand={"only": {"food": (10.0,)}},
        emergency_price={"only": {"food": (1.0,)}},
        emergency_supply={"only": {"food": (10.0,)}},
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def test_development_config_is_preregistered_and_frozen() -> None:
    config = load_m1_config(ROOT / "configs/phase6_m1_procurement_cap.yaml")
    development = config["development_preregistration"]
    assert config["status"] == "frozen_for_development_execution"
    assert config["runner_namespace"] == "phase6_m1_procurement_cap"
    assert config["output_root"] == "outputs/phase6_m1_procurement_cap_v1"
    # This historical flag records that the design-only PR ran no matrix;
    # execution now requires both the frozen status and the separate CLI gate.
    assert development["execution_allowed_in_this_revision"] is False
    assert len(development["seeds"]) * len(development["beta"]) * len(
        development["kappa"]
    ) == development["configuration_count"] == 63


@pytest.mark.parametrize(
    "raw",
    (
        {"enabled": True, "kappa": None},
        {"enabled": True, "kappa": 0.0},
        {"enabled": True, "kappa": -1.0},
        {"enabled": True, "kappa": float("inf")},
        {"enabled": False, "kappa": 1.0},
        {"enabled": False},
        {},
    ),
)
def test_invalid_cap_configuration_is_rejected(raw) -> None:
    with pytest.raises(M1ProtocolError):
        resolve_regular_procurement_cap(raw)


def test_invalid_cap_fails_before_scenario_generation(monkeypatch) -> None:
    called = False

    def forbidden_generator(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("scenario generation must not be reached")

    monkeypatch.setattr(m1, "generate_phase6_data", forbidden_generator)
    with pytest.raises(M1ProtocolError):
        generate_m1_data(
            {},
            matrix_path="unused.yaml",
            tier_id="V1",
            seed=1,
            budget=10.0,
            cap_config={"enabled": True, "kappa": None},
        )
    assert called is False


def test_disabled_cap_returns_exact_m0_data_and_solution() -> None:
    data = base_data()
    generated = SimpleNamespace(
        data=data,
        theoretical_mean_demand={"food": (6.0,)},
    )
    disabled = apply_regular_procurement_cap(
        generated,
        RegularProcurementCap(enabled=False, kappa=None),
    )
    assert disabled is data
    m0 = solve_endogenous_extensive(
        data,
        solver_threads=1,
        consistency_tolerance=1.0e-7,
    )
    control = solve_endogenous_extensive(
        disabled,
        solver_threads=1,
        consistency_tolerance=1.0e-7,
    )
    assert m0.status == control.status == "optimal"
    assert math.isclose(float(m0.objective), float(control.objective), abs_tol=1.0e-7)
    assert math.isclose(float(m0.reserve), float(control.reserve), abs_tol=1.0e-7)
    assert m0.master.regular_purchase == control.master.regular_purchase


def test_cap_uses_theoretical_demand_and_is_strictly_satisfied() -> None:
    data = base_data()
    generated = SimpleNamespace(
        data=data,
        theoretical_mean_demand={"food": (5.0,)},
    )
    capped = apply_regular_procurement_cap(
        generated,
        RegularProcurementCap(enabled=True, kappa=0.8),
    )
    assert isinstance(capped, CappedProcurementData)
    assert capped.regular_procurement_capacity == {"food": (4.0,)}
    solution = solve_m1_endogenous_extensive(
        capped,
        solver_threads=1,
        consistency_tolerance=1.0e-7,
    )
    assert solution.status == "optimal"
    assert solution.master.regular_purchase["food"][0] <= 4.0 + 1.0e-7
    assert math.isclose(
        float(solution.master.regular_cost) + float(solution.master.reserve),
        capped.budget,
        abs_tol=1.0e-7,
    )


def test_minimum_feasible_reserve_matches_closed_form() -> None:
    data = capped_data(capacity=4.0)
    floor = solve_minimum_feasible_reserve(data)
    assert floor.status == "optimal"
    assert math.isclose(float(floor.reserve), 6.0, abs_tol=1.0e-7)
    assert math.isclose(float(floor.closed_form_reserve), 6.0, abs_tol=1.0e-7)
    assert float(floor.closed_form_difference) <= 1.0e-7


def test_tolerance_optimal_interval_prevents_false_activation() -> None:
    analysis = analyze_reserve_interval(
        degenerate_data(),
        absolute_tolerance=1.0e-7,
        relative_tolerance=0.0,
        solver_threads=1,
    )
    assert analysis.status == "optimal"
    assert analysis.minimum_tolerance_optimal is not None
    assert analysis.maximum_tolerance_optimal is not None
    assert analysis.minimum_tolerance_optimal.evaluation is not None
    assert analysis.maximum_tolerance_optimal.evaluation is not None
    assert analysis.minimum_tolerance_optimal.evaluation.status == "optimal"
    assert analysis.maximum_tolerance_optimal.evaluation.status == "optimal"
    assert float(analysis.minimum_feasible.reserve) <= 1.0e-7
    assert float(analysis.minimum_tolerance_optimal.reserve) <= 1.0e-6
    assert float(analysis.maximum_tolerance_optimal.reserve) >= 9.999
    assert float(analysis.robust_discretionary_reserve) <= 1.0e-6
    assert analysis.numerical_activation is False
    assert analysis.substantive_activation is False


def test_fixed_autonomous_reserve_reoptimizes_with_budget_equality() -> None:
    data = capped_data(capacity=8.0)
    floor = solve_minimum_feasible_reserve(data)
    assert floor.status == "optimal"
    solutions = [
        solve_fixed_autonomous_reserve(
            data,
            rho=rho,
            minimum_feasible_reserve=float(floor.reserve),
            solver_threads=1,
            consistency_tolerance=1.0e-7,
        )
        for rho in (0.0, 0.1, 0.3, 0.5)
    ]
    assert all(solution.status == "optimal" for solution in solutions)
    expected_reserves = [
        fixed_autonomous_reserve_amount(
            budget=data.budget,
            minimum_feasible_reserve=float(floor.reserve),
            rho=rho,
        )
        for rho in (0.0, 0.1, 0.3, 0.5)
    ]
    assert [round(float(solution.reserve), 8) for solution in solutions] == [
        round(value, 8) for value in expected_reserves
    ]
    purchases = [
        solution.master.regular_purchase["food"][0] for solution in solutions
    ]
    assert len(set(round(value, 8) for value in purchases)) == 4
    for solution in solutions:
        assert math.isclose(
            float(solution.master.regular_cost) + float(solution.reserve),
            data.budget,
            abs_tol=1.0e-7,
        )


def test_disabled_cap_fixed_policy_recovers_rho_times_budget() -> None:
    data = base_data()
    model = build_fixed_autonomous_reserve_model(
        data,
        rho=0.3,
        minimum_feasible_reserve=0.0,
    )
    assert math.isclose(float(model.R.value), 3.0, abs_tol=1.0e-12)


def test_capped_extensive_ccg_and_spw_objectives_are_consistent() -> None:
    data = capped_data(budget=10.0, capacity=4.0)
    extensive = solve_m1_endogenous_extensive(
        data,
        solver_threads=1,
        consistency_tolerance=1.0e-6,
    )
    ccg = run_m1_standard_ccg(
        data,
        solver_threads=1,
        absolute_tolerance=1.0e-6,
        relative_tolerance=1.0e-7,
    )
    spw = run_m1_spw_ccg_budget_sequence(
        data,
        (10.0, 11.0),
        solver_threads=1,
        objective_absolute_tolerance=1.0e-6,
        objective_relative_tolerance=1.0e-7,
        ccg_absolute_tolerance=1.0e-6,
        ccg_relative_tolerance=1.0e-7,
    )
    assert extensive.status == "optimal"
    assert ccg.termination_status == "optimal"
    assert ccg.converged
    assert math.isclose(
        float(extensive.objective), float(ccg.objective), abs_tol=1.0e-6
    )
    assert spw.status == "optimal"
    assert len(spw.comparisons) == 2
    for comparison in spw.comparisons:
        assert comparison.objectives_consistent
        assert math.isclose(
            float(comparison.cold_result.objective),
            float(comparison.warm_result.objective),
            abs_tol=1.0e-6,
        )


def test_each_fixed_policy_builds_a_fresh_unfixed_purchase_model() -> None:
    data = capped_data(capacity=8.0)
    first = build_fixed_autonomous_reserve_model(
        data, rho=0.1, minimum_feasible_reserve=2.0
    )
    second = build_fixed_autonomous_reserve_model(
        data, rho=0.3, minimum_feasible_reserve=2.0
    )
    assert first is not second
    assert first.y["food", 0].fixed is False
    assert second.y["food", 0].fixed is False
    assert first.R.fixed and second.R.fixed

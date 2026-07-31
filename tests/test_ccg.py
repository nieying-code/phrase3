from __future__ import annotations

import math

from src.ccg import run_standard_ccg
from src.extensive_model import solve_endogenous_extensive
from src.model_data import ProcurementData
from src.scenario_generator import generate_synthetic_data, load_config


def unique_two_scenario_data() -> ProcurementData:
    data = ProcurementData(
        items=("food",),
        periods=1,
        scenarios=("low", "high"),
        budget=10.0,
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
            "low": {"food": (0.0,)},
            "high": {"food": (0.0,)},
        },
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def infeasible_oracle_data() -> ProcurementData:
    data = ProcurementData(
        items=("food",),
        periods=1,
        scenarios=("high", "low"),
        budget=10.0,
        shelf_life={"food": 2},
        initial_inventory={"food": (0.0, 0.0)},
        storage_capacity=(0.0,),
        regular_price={"food": (1.0,)},
        demand={
            "high": {"food": (10.0,)},
            "low": {"food": (0.0,)},
        },
        emergency_price={
            "high": {"food": (2.0,)},
            "low": {"food": (2.0,)},
        },
        emergency_supply={
            "high": {"food": (0.0,)},
            "low": {"food": (0.0,)},
        },
        shortage_penalty={"food": 100.0},
        waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def test_ccg_matches_extensive_and_unique_first_stage() -> None:
    data = unique_two_scenario_data()
    extensive = solve_endogenous_extensive(
        data,
        solver_preference=("gurobi",),
        consistency_tolerance=1.0e-7,
    )
    ccg = run_standard_ccg(
        data,
        initial_scenarios=("low",),
        solver_preference=("gurobi",),
        absolute_tolerance=1.0e-7,
        relative_tolerance=1.0e-7,
        max_iterations=10,
    )
    assert extensive.status == "optimal"
    assert ccg.converged
    assert ccg.termination_status == "optimal"
    assert math.isclose(
        float(ccg.objective),
        float(extensive.objective),
        abs_tol=1.0e-7,
    )
    assert math.isclose(
        float(ccg.reserve),
        float(extensive.reserve),
        abs_tol=1.0e-7,
    )
    assert math.isclose(
        ccg.regular_purchase["food"][0],
        extensive.master.regular_purchase["food"][0],
        abs_tol=1.0e-7,
    )
    assert len(ccg.final_scenario_set) == len(set(ccg.final_scenario_set))
    assert ccg.iterations <= len(data.scenarios) + 1


def test_ccg_adds_formerly_infeasible_low_demand_scenario_by_cost() -> None:
    data = infeasible_oracle_data()
    ccg = run_standard_ccg(
        data,
        initial_scenarios=("high",),
        solver_preference=("gurobi",),
        max_iterations=10,
    )
    assert ccg.converged
    assert "low" in ccg.final_scenario_set
    assert any(
        row.added_scenario == "low" and row.added_type == "worst_cost"
        for row in ccg.iteration_log
    )
    assert all(row.infeasible_scenario_count == 0 for row in ccg.iteration_log)
    assert len(ccg.final_scenario_set) == len(set(ccg.final_scenario_set))


def test_ccg_accepts_generator_solver_preference() -> None:
    data = unique_two_scenario_data()

    ccg = run_standard_ccg(
        data,
        initial_scenarios=("low",),
        solver_preference=(name for name in ("gurobi",)),
        max_iterations=10,
    )

    assert ccg.converged
    assert ccg.termination_status == "optimal"
    assert set(ccg.exact_scenario_costs) == set(data.scenarios)


def test_ccg_reports_atomic_progress_payload_after_each_iteration() -> None:
    data = unique_two_scenario_data()
    progress: list[dict[str, object]] = []

    ccg = run_standard_ccg(
        data,
        initial_scenarios=("low",),
        solver_preference=("gurobi",),
        max_iterations=10,
        progress_callback=progress.append,
    )

    assert ccg.converged
    assert len(progress) == ccg.iterations
    assert progress[-1]["iteration"] == ccg.iterations
    assert progress[-1]["termination_status"] == "optimal"
    assert progress[-1]["converged"] is True
    assert progress[-1]["current_scenario_set"] == list(
        ccg.final_scenario_set
    )
    assert len(progress[-1]["iteration_log"]) == ccg.iterations


def test_fixed_seed_reproduces_scenarios() -> None:
    config = load_config("configs/phase3.yaml")
    first = generate_synthetic_data(config)
    second = generate_synthetic_data(config)
    assert first.scenarios == second.scenarios
    assert first.demand == second.demand
    assert first.emergency_price == second.emergency_price
    assert first.emergency_supply == second.emergency_supply

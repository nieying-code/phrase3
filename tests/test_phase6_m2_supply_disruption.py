from __future__ import annotations

from dataclasses import replace
import math
from pathlib import Path

import pyomo.environ as pyo
import pytest

from src.extensive_model import solve_endogenous_extensive
from src.model_data import ProcurementData
from src.phase6_m2 import (
    M2ProtocolError,
    SupplyDisruptionProfile,
    analyze_m2_reserve_interval,
    apply_regular_supply_disruption,
    build_m2_inventory_model,
    contract_flow,
    fulfillment_statistics,
    joint_scenario_identities,
    load_m2_config,
    m2_fingerprints,
    resolve_supply_disruption_profile,
    reconstruct_demand_from_latent,
    reconstruct_frozen_demand_latent,
    run_m2_spw_ccg_budget_sequence,
    run_m2_standard_ccg,
    solve_m2_endogenous_extensive,
    solve_m2_recourse,
)
from src.phase6_protocol import (
    GeneratedPhase6Data, TierSpec, generate_phase6_data, load_phase6_matrix,
)
from src.evaluation import evaluate_first_stage


ROOT = Path(__file__).resolve().parents[1]


def base_data(*, budget: float = 10.0) -> ProcurementData:
    data = ProcurementData(
        items=("food",), periods=2, scenarios=("low", "high"), budget=budget,
        shelf_life={"food": 2}, initial_inventory={"food": (1.0, 0.0)},
        storage_capacity=(20.0, 20.0), regular_price={"food": (1.0, 1.0)},
        demand={"low": {"food": (2.0, 2.0)}, "high": {"food": (5.0, 5.0)}},
        emergency_price={"low": {"food": (2.0, 2.0)}, "high": {"food": (2.0, 2.0)}},
        emergency_supply={"low": {"food": (10.0, 10.0)}, "high": {"food": (10.0, 10.0)}},
        shortage_penalty={"food": 20.0}, waste_penalty={"food": 1.0},
    )
    data.validate()
    return data


def generated() -> GeneratedPhase6Data:
    data = base_data()
    tier = TierSpec("V1", 1, 2, 2, 0, 0, "none", 120.0, 600.0, 1800.0, 1)
    return GeneratedPhase6Data(
        data=data, tier=tier, seed=1, budget=data.budget,
        reference_budget=data.budget, budget_factor=1.0,
        theoretical_mean_demand={"food": (3.5, 3.5)},
        generator_protocol_id="test",
    )


LATENT = {
    "low": {"food": (-1.0, -0.5)},
    "high": {"food": (1.0, 1.5)},
}


def test_m2_design_config_is_isolated_and_not_executable() -> None:
    config = load_m2_config(ROOT / "configs/phase6_m2_supply_disruption.yaml")
    assert config["status"] == "candidate_design_pending_review"
    assert config["runner_namespace"] == "phase6_m2_supply_disruption"
    assert config["output_root"] == "outputs/phase6_m2_supply_disruption_v1"
    assert config["inherit_m0_or_m1_authorization"] is False
    assert config["development_preregistration"]["configuration_count"] == 27
    assert config["development_preregistration"]["seeds"] == [
        2026081201, 2026081202, 2026081203
    ]
    assert not set(config["development_preregistration"]["seeds"]) & {
        2026081101, 2026081102, 2026081103
    }
    assert config["execution_boundaries"] == {
        "development_matrix_started": False,
        "pilot_started": False,
        "formal_started": False,
        "M0_E3_started_by_this_protocol": False,
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"disruption_profiles": {"C1": {"enabled": True, "loss_scale": -1.0, "recovery_fraction": 0.0}}},
        {"disruption_profiles": {"C1": {"enabled": True, "loss_scale": 0.0, "recovery_fraction": 0.0}}},
        {"disruption_profiles": {"C1": {"enabled": True, "loss_scale": 0.2, "recovery_fraction": 1.1}}},
        {"disruption_profiles": {"C1": {"enabled": False, "loss_scale": 0.2, "recovery_fraction": 0.0}}},
    ],
)
def test_invalid_profile_fails_before_generation(raw) -> None:
    with pytest.raises(M2ProtocolError):
        resolve_supply_disruption_profile(raw, "C1")


def test_c0_forces_alpha_one_and_strictly_recovers_m0() -> None:
    original = generated()
    c0 = apply_regular_supply_disruption(
        original, SupplyDisruptionProfile("C0", False, 0.0, 0.0),
        demand_latent=LATENT,
    )
    assert all(
        value == 1.0
        for scenario in c0.data.scenarios
        for value in c0.data.regular_fulfillment_rate[scenario]["food"]
    )
    m0 = solve_endogenous_extensive(original.data, solver_threads=1)
    control = solve_m2_endogenous_extensive(c0.data, solver_threads=1)
    assert m0.status == control.status == "optimal"
    assert math.isclose(float(m0.objective), float(control.objective), abs_tol=1e-7)
    assert math.isclose(float(m0.reserve), float(control.reserve), abs_tol=1e-7)
    assert m0.master.regular_purchase == control.master.regular_purchase
    assert m0.evaluation.exact_scenario_costs == control.evaluation.exact_scenario_costs

    m0_face = analyze_m2_reserve_interval(
        c0.data, absolute_tolerance=1e-6, relative_tolerance=1e-7,
        solver_threads=1,
    )
    # Run the exact same complete-extensive face analysis through the M0 path.
    from src.phase6_m1 import analyze_reserve_interval
    control_face = analyze_reserve_interval(
        original.data, absolute_tolerance=1e-6, relative_tolerance=1e-7,
        solver_threads=1,
    )
    assert m0_face.status == control_face.status == "optimal"
    assert m0_face.minimum_tolerance_optimal.reserve == pytest.approx(
        control_face.minimum_tolerance_optimal.reserve, abs=1e-6
    )
    assert m0_face.maximum_tolerance_optimal.reserve == pytest.approx(
        control_face.maximum_tolerance_optimal.reserve, abs=1e-6
    )

    # Cross-fix both first-stage solutions; vector equality is only an extra
    # deterministic regression, not the equivalence criterion.
    m0_in_c0 = [
        solve_m2_recourse(
            c0.data, scenario, m0.master.regular_purchase,
            float(m0.reserve), solver_threads=1,
        ).recourse
        for scenario in c0.data.scenarios
    ]
    c0_in_m0 = evaluate_first_stage(
        original.data, control.master.regular_purchase,
        float(control.reserve), solver_threads=1,
    )
    assert all(result.status == "optimal" for result in m0_in_c0)
    assert c0_in_m0.status == "optimal"
    assert [result.objective for result in m0_in_c0] == pytest.approx(
        [m0.evaluation.scenario_results[s].objective for s in original.data.scenarios]
    )
    assert c0_in_m0.exact_scenario_costs == control.evaluation.exact_scenario_costs


def test_joint_latent_raises_demand_and_lowers_fulfillment() -> None:
    c2 = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C2", True, 0.6, 0.0),
        demand_latent=LATENT,
    )
    low = c2.data.regular_fulfillment_rate["low"]["food"]
    high = c2.data.regular_fulfillment_rate["high"]["food"]
    assert max(high) < min(low)
    assert c2.statistics.total_demand_weighted_fulfillment_correlation < 0.0
    assert c2.statistics.correlation_status == "defined"


def test_latent_replay_exactly_recovers_frozen_demand() -> None:
    matrix_path = ROOT / "configs/phase6_experiment_matrix.yaml"
    matrix = load_phase6_matrix(matrix_path)
    generated_data = generate_phase6_data(
        matrix, matrix_path=matrix_path, tier_id="V1", seed=2026081201,
        budget=1000.0,
    )
    latent = reconstruct_frozen_demand_latent(matrix, generated_data)
    replayed = reconstruct_demand_from_latent(matrix, generated_data, latent)
    for scenario in generated_data.data.scenarios:
        for item in generated_data.data.items:
            assert replayed[scenario][item] == pytest.approx(
                generated_data.data.demand[scenario][item], rel=0.0, abs=1e-12
            )


def test_joint_scenario_identity_is_atomic_and_mutation_sensitive() -> None:
    m2 = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    )
    base = m2.scenario_identities["low"]
    assert len(m2.joint_scenario_set_sha256) == 64
    changed_demand = replace(
        m2.data,
        demand={**m2.data.demand, "low": {"food": (2.1, 2.0)}},
    )
    changed_fulfillment = replace(
        m2.data,
        regular_fulfillment_rate={
            **m2.data.regular_fulfillment_rate,
            "low": {"food": (0.91, 0.92)},
        },
    )
    changed_price = replace(
        m2.data,
        emergency_price={**m2.data.emergency_price, "low": {"food": (2.1, 2.0)}},
    )
    assert joint_scenario_identities(changed_demand, LATENT)["low"].joint_scenario_sha256 != base.joint_scenario_sha256
    assert joint_scenario_identities(changed_fulfillment, LATENT)["low"].joint_scenario_sha256 != base.joint_scenario_sha256
    assert joint_scenario_identities(changed_price, LATENT)["low"].joint_scenario_sha256 != base.joint_scenario_sha256


@pytest.mark.parametrize(
    ("demand", "rates", "expected_status", "weighted_is_none"),
    [
        ({"low": (0.0, 0.0), "high": (0.0, 0.0)}, {"low": (0.8, 0.8), "high": (0.6, 0.6)}, "zero_total_demand", True),
        ({"low": (2.0, 2.0), "high": (2.0, 2.0)}, {"low": (0.8, 0.7), "high": (0.6, 0.5)}, "constant_demand", False),
        ({"low": (2.0, 2.0), "high": (5.0, 5.0)}, {"low": (0.8, 0.8), "high": (0.8, 0.8)}, "constant_fulfillment", False),
    ],
)
def test_fulfillment_statistics_boundary_statuses(
    demand, rates, expected_status, weighted_is_none
) -> None:
    m2 = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    )
    data = replace(
        m2.data,
        demand={s: {"food": tuple(demand[s])} for s in ("low", "high")},
        regular_fulfillment_rate={s: {"food": tuple(rates[s])} for s in ("low", "high")},
    )
    stats = fulfillment_statistics(data)
    assert stats.correlation_status == expected_status
    assert (stats.demand_weighted_mean is None) is weighted_is_none


def test_fulfillment_statistics_insufficient_variation() -> None:
    m2 = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    )
    stats = fulfillment_statistics(m2.data.subset(("low",)))
    assert stats.correlation_status == "insufficient_variation"


def test_contract_conservation_and_undelivered_is_reporting_only() -> None:
    original = generated()
    rates = {"low": {"food": (0.5, 0.5)}, "high": {"food": (0.5, 0.5)}}
    data = apply_regular_supply_disruption(
        original, SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    ).data
    data = replace(data, regular_fulfillment_rate=rates)
    purchase = {"food": [4.0, 0.0]}
    delivered, lost = contract_flow(data, purchase, "low", "food", 0)
    assert delivered == lost == 2.0
    result = solve_m2_recourse(data, "low", purchase, reserve=6.0, solver_threads=1)
    assert result.recourse.status == "optimal"
    model = build_m2_inventory_model(
        data, scenario_names=("low",), model_name="flow",
        reserve_policy="fixed_first_stage", regular_purchase=purchase,
        reserve=6.0, objective_kind="recourse",
    )
    assert pyo.value(model.delivered_regular_purchase["low", "food", 0]) == pytest.approx(2.0)
    assert pyo.value(model.undelivered_contract_quantity["low", "food", 0]) == pytest.approx(2.0)
    assert result.delivered_regular_purchase["food"][0] == pytest.approx(2.0)
    assert result.undelivered_contract_quantity["food"][0] == pytest.approx(2.0)
    assert result.recourse.expired_waste["food"][0] + result.recourse.early_disposal["food"][0][0] <= 3.0 + 1e-7
    # Initial inventory (1) plus delivered contract (2), never the undelivered 2.
    assert sum(result.recourse.shortage["food"]) <= sum(data.demand["low"]["food"])


def test_budget_and_emergency_reserve_accounting_are_unchanged() -> None:
    base = replace(generated(), data=base_data(budget=4.0), budget=4.0)
    data = apply_regular_supply_disruption(
        base, SupplyDisruptionProfile("C2", True, 1.0, 0.0),
        demand_latent={"low": {"food": (20.0, 20.0)}, "high": {"food": (20.0, 20.0)}},
    ).data
    model = build_m2_inventory_model(
        data, scenario_names=("high",), model_name="accounting",
        reserve_policy="fixed_first_stage", regular_purchase={"food": [2.0, 0.0]},
        reserve=2.0, objective_kind="recourse",
    )
    assert pyo.value(model.regular_cost) == pytest.approx(2.0)
    assert pyo.value(model.undelivered_contract_quantity["high", "food", 0]) == pytest.approx(2.0)
    result = solve_m2_recourse(data, "high", {"food": [2.0, 0.0]}, 2.0, solver_threads=1)
    assert result.recourse.status == "optimal"
    assert result.recourse.emergency_spend <= 2.0 + 1e-7


def test_extensive_standard_ccg_and_spw_match_under_disruption() -> None:
    disrupted = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    ).data
    extensive = solve_m2_endogenous_extensive(disrupted, solver_threads=1)
    ccg = run_m2_standard_ccg(disrupted, solver_threads=1, max_iterations=10)
    assert extensive.status == "optimal"
    assert ccg.converged
    assert float(extensive.objective) == pytest.approx(float(ccg.objective), abs=1e-6)
    spw = run_m2_spw_ccg_budget_sequence(
        disrupted, [9.0, 10.0], solver_threads=1, max_iterations=10
    )
    assert spw.status == "optimal"
    assert all(row.objective_difference <= 1e-6 for row in spw.comparisons)
    assert extensive.joint_scenario_set_sha256 == ccg.joint_scenario_set_sha256
    assert extensive.joint_scenario_set_sha256 == spw.joint_scenario_set_sha256
    scenario = disrupted.scenarios[0]
    recourse = solve_m2_recourse(
        disrupted, scenario, extensive.master.regular_purchase,
        float(extensive.reserve), solver_threads=1,
    )
    assert recourse.joint_scenario_sha256 == extensive.scenario_identities[scenario].joint_scenario_sha256


def test_complete_extensive_optimal_face_still_re_evaluates_endpoints() -> None:
    data = apply_regular_supply_disruption(
        generated(), SupplyDisruptionProfile("C1", True, 0.2, 0.0),
        demand_latent=LATENT,
    ).data
    analysis = analyze_m2_reserve_interval(
        data, absolute_tolerance=1e-6, relative_tolerance=1e-7,
        solver_threads=1,
    )
    assert analysis.status == "optimal"
    assert analysis.minimum_feasible.reserve == pytest.approx(0.0, abs=1e-7)
    assert analysis.minimum_tolerance_optimal.evaluation.status == "optimal"
    assert analysis.maximum_tolerance_optimal.evaluation.status == "optimal"


def test_m2_has_independent_fingerprints() -> None:
    values = m2_fingerprints(
        project_root=ROOT,
        config_path=ROOT / "configs/phase6_m2_supply_disruption.yaml",
        runner_config_path=ROOT / "configs/phase6_m2_runner.yaml",
    )
    assert set(values) == {
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256", "environment_sha256",
    }
    assert all(len(value) == 64 for value in values.values())


def test_m2_context_restores_all_global_builders_after_exception() -> None:
    import src.ccg as ccg
    import src.extensive_model as extensive_model
    import src.phase6_m1 as m1
    import src.recourse_model as recourse_model
    from src.phase6_m2 import m2_model_context

    before = (
        ccg.build_restricted_master, extensive_model.build_inventory_model,
        m1.build_restricted_master, m1.evaluate_first_stage,
        recourse_model.build_inventory_model,
    )
    with pytest.raises(RuntimeError):
        with m2_model_context():
            raise RuntimeError("test restoration")
    after = (
        ccg.build_restricted_master, extensive_model.build_inventory_model,
        m1.build_restricted_master, m1.evaluate_first_stage,
        recourse_model.build_inventory_model,
    )
    assert after == before

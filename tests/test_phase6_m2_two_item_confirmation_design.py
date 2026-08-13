from __future__ import annotations

import itertools
import hashlib
import json
import math
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_two_item_confirmation.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_two_item_confirmation_design_audit.json"
PARENT_AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_grid_audit.json"
PARENT_AUDIT_SHA256 = "886a1657c511e1df13b252bb909b037cfd1d2a3790471b49e219a1d4f345d6ba"
DESIGN_BASELINE_CONFIG_SHA256 = "c3aead6f7c18eb0e74cc0de16803e8f56d15052a8055b56c7a4244ad8ad6847a"
RUNNER_CONFIG_SHA256 = "d6e28d2171aceacd750a74bcc58a01c3c7383ffdab7ce7fca53e7451fe5f39a5"


def test_two_item_confirmation_design_is_exact_and_not_executable() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["protocol_id"] == "phase6_m2c2_confirmation_v1_0"
    assert config["status"] == "frozen_for_confirmation_execution"
    design = config["confirmation_preregistration"]
    assert design["execution_allowed_in_this_revision"] is True
    seeds = tuple(design["seeds"])
    betas = tuple(float(value) for value in design["beta"])
    profiles = tuple(design["profiles"])
    assert seeds == (2026081301, 2026081302, 2026081303, 2026081304, 2026081305)
    assert betas == (1.1, 1.3)
    assert profiles == ("C0", "C1", "T03")
    cases = set(itertools.product(seeds, betas, profiles))
    assert len(cases) == design["configuration_count"] == 30
    assert design["profiles"]["C0"]["enabled"] is False
    assert design["profiles"]["C0"]["loss_scale"] == 0.0
    assert design["profiles"]["C1"]["loss_scale"] == 0.2
    assert design["profiles"]["T03"]["loss_scale"] == 0.3


def test_confirmation_seeds_are_disjoint_from_all_existing_project_seeds() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    selected = {str(value) for value in config["confirmation_preregistration"]["seeds"]}
    observed: set[str] = set()
    for folder in (ROOT / "configs", ROOT / "docs", ROOT / "src", ROOT / "tests"):
        for path in folder.rglob("*"):
            if not path.is_file() or path.resolve() == CONFIG.resolve():
                continue
            if "phase6_m2_two_item_confirmation" in path.name or "phase6_m2c2_confirmation" in path.name:
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json", ".md", ".py"}:
                continue
            observed.update(re.findall(r"\b20\d{8}\b", path.read_text(encoding="utf-8", errors="ignore")))
    assert selected.isdisjoint(observed)


def test_item_heterogeneity_and_shared_pool_evidence_are_frozen() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    model = config["scientific_model"]
    assert model["item_count"] == 2 and model["periods"] == 6
    items = model["items"]
    assert [item["id"] for item in items] == ["relief_food_1", "relief_food_2"]
    assert [item["shelf_life_periods"] for item in items] == [6, 4]
    assert [item["demand_multiplier"] for item in items] == [1.0, 0.75]
    assert [item["regular_price_multiplier"] for item in items] == [1.0, 1.2]
    assert [item["supply_vulnerability_multiplier"] for item in items] == [0.8, 1.2]
    assert model["shared_emergency_reserve_pool"] is True
    gate = config["machine_gates"]
    assert gate["per_beta_confirmation"] == {
        "C0_substantive_activation_seed_count_maximum": 0,
        "T03_substantive_activation_seed_count_minimum": 3,
        "T03_moderate_seed_count_minimum": 3,
        "T03_activation_seed_count_must_be_strictly_greater_than_C1": True,
        "cost_service_or_manual_trend_selection_forbidden": True,
    }
    cross = gate["shared_reserve_cross_item_evidence"]
    assert cross["minimum_seed_count"] == 3
    assert cross["both_items_each_have_positive_emergency_spend_in_at_least_one_scenario"] is True
    assert cross["minimum_scenarios_with_positive_total_emergency_spend"] == 2
    assert cross["minimum_absolute_item1_emergency_spend_share_range"] == 1e-4
    assert gate["overall_confirmation"]["formal_extension_authorized"] is False


def test_M2C2_reference_budget_and_storage_capacity_are_independently_recomputed() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    model = config["scientific_model"]
    baseline = config["two_item_deterministic_baseline"]
    assert model["tier_id"] == "M2C2"
    assert model["inherited_V1_reference_budget_forbidden"] is True
    periods = model["periods"]
    t = tuple(range(periods))
    raw = tuple(
        1.0
        + 0.20 * math.sin(2.0 * math.pi * index / periods)
        + 0.10 * math.cos(4.0 * math.pi * index / periods)
        for index in t
    )
    seasonality = tuple(value / (sum(raw) / periods) for value in raw)
    expected_reference = 0.0
    total_mean_by_period = [0.0] * periods
    for item in model["items"]:
        for index in t:
            mean = 100.0 * float(item["demand_multiplier"]) * seasonality[index]
            price = (
                2.0
                * float(item["regular_price_multiplier"])
                * (
                    1.0
                    + 0.05 * index / (periods - 1)
                    + 0.025 * math.sin(2.0 * math.pi * index / periods)
                )
            )
            expected_reference += mean * price
            total_mean_by_period[index] += mean
    assert math.isclose(
        expected_reference,
        baseline["reference_budget"]["exact_value"],
        rel_tol=0.0,
        abs_tol=1.0e-9,
    )
    assert baseline["reference_budget"]["exact_value"] == 2337.610924158743
    for beta in (1.1, 1.3):
        assert math.isclose(
            baseline["budgets_by_beta"][str(beta)],
            beta * expected_reference,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        )
    expected_capacity = [1.5 * value for value in total_mean_by_period]
    assert all(
        math.isclose(actual, expected, rel_tol=0.0, abs_tol=1.0e-9)
        for actual, expected in zip(
            baseline["storage_capacity"]["values"], expected_capacity, strict=True
        )
    )
    assert baseline["runner_must_recompute_and_reject_mismatch_before_scenario_generation"] is True


def test_cross_item_metric_uses_R_min_opt_endpoint_and_frozen_formulas() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cross = config["machine_gates"]["shared_reserve_cross_item_evidence"]
    assert cross["first_stage_plan_source"] == "complete_extensive_model_R_min_opt_endpoint"
    assert cross["arbitrary_initial_R_star_plan_forbidden"] is True
    assert cross["exact_recourse_evaluation_scenario_count"] == 50
    assert cross["emergency_spend_positive_tolerance"] == 1.0e-7
    assert cross["minimum_scenarios_with_positive_total_emergency_spend"] == 2
    assert cross["minimum_absolute_item1_emergency_spend_share_range"] == 1.0e-4
    assert cross["universal_claim_over_all_optimal_recourse_solutions_forbidden"] is True
    assert cross["item_scenario_emergency_spend_formula"] == "sum_over_periods_of_emergency_price_times_emergency_purchase"
    assert cross["scenario_total_emergency_spend_formula"] == "sum_over_items_of_item_scenario_emergency_spend"


def test_parent_evidence_and_design_config_bytes_are_locked() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    parent = json.loads(PARENT_AUDIT.read_text(encoding="utf-8"))
    assert hashlib.sha256(PARENT_AUDIT.read_bytes()).hexdigest() == PARENT_AUDIT_SHA256
    assert config["parent_evidence"]["threshold_audit_sha256"] == PARENT_AUDIT_SHA256
    assert parent["projection"]["overall_decision"] == "permit_separate_multi_item_design_PR_only"
    assert parent["projection"]["eligible_moderate_combinations"] == [
        {"beta": 1.1, "profile_id": "T03"},
        {"beta": 1.3, "profile_id": "T03"},
    ]
    assert parent["projection"]["formal_extension_authorized"] is False
    assert parent["formal_extension_authorized"] is False
    assert audit["parent_evidence"]["audit_sha256"] == PARENT_AUDIT_SHA256
    assert audit["parent_evidence"]["eligible_combinations"] == config["parent_evidence"]["eligible_parent_combinations"]
    assert audit["design_config"]["sha256"] == DESIGN_BASELINE_CONFIG_SHA256
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest() == RUNNER_CONFIG_SHA256
    assert audit["design_config"] == {
        "path": "configs/phase6_m2_two_item_confirmation.yaml",
        "sha256": DESIGN_BASELINE_CONFIG_SHA256,
    }


def test_C0_equivalence_and_passing_beta_claim_boundaries_are_frozen() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    c0 = config["C0_equivalence_gate"]
    assert c0 == {
        "fulfillment_must_equal_one_elementwise": True,
        "comparison_model": "identical_two_item_model_with_regular_supply_disruption_disabled",
        "robust_objective_difference_within_frozen_tolerance": True,
        "tolerance_optimal_reserve_interval_endpoints_within_frozen_tolerance": True,
        "bidirectional_fixed_first_stage_exact_recourse_evaluation_required": True,
        "all_50_scenario_recourse_objectives_within_frozen_tolerance": True,
        "C0_zero_activation_alone_is_insufficient": True,
    }
    overall = config["machine_gates"]["overall_confirmation"]
    assert overall["minimum_passing_beta_count"] == 1
    assert overall["one_passing_beta_scope"] == "formal_design_may_include_only_that_beta_and_budget_effect_claims_are_forbidden"
    assert overall["two_passing_betas_scope"] == "formal_design_may_compare_beta_1_1_and_1_3_budget_moderation"


def test_design_execution_counts_stay_zero_and_runner_is_now_separate() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    boundaries = config["execution_boundaries"]
    assert boundaries["runner_implemented"] is True
    assert all(value == 0 for key, value in boundaries.items() if key != "runner_implemented")
    assert (ROOT / "src/phase6_m2c2_confirmation.py").is_file()
    assert (ROOT / "src/run_phase6_m2c2_confirmation.py").is_file()

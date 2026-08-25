from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import yaml

from src.phase6_m2c2_confirmation import recompute_m2c2_deterministic_baseline


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_algorithm_performance_design_v1_0.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_design_v1_0_audit.json"
M2_PARENT = ROOT / "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
M0_PARENT = ROOT / "docs/handoffs/2026-08-23_phase6_m0_e3_algorithm_performance_results_v1_0_audit.json"
MATRIX = ROOT / "configs/phase6_experiment_matrix.yaml"
M2C2 = ROOT / "configs/phase6_m2_two_item_confirmation.yaml"

CONFIG_SHA256 = "2c5fda31262af1522a8719044c9b4126e70c920b65ff8f3b8c382b5d6fdf1f49"
M2_PARENT_SHA256 = "bce5b075d352a4679b4371a073f5cc0a931a6b309b401318e9f4c38a8a7489a5"
M0_PARENT_SHA256 = "cec805c4b414a9ebbfd0ebbb80990d85016873dbc974eea2e7f9f0ef172e2e54"
PILOT = tuple(range(2026091001, 2026091004))
FORMAL = tuple(range(2026091101, 2026091111))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_parent_evidence_and_design_bytes_are_locked() -> None:
    config = _config()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    m2 = json.loads(M2_PARENT.read_text(encoding="utf-8"))
    m0 = json.loads(M0_PARENT.read_text(encoding="utf-8"))

    assert _sha256(CONFIG) == CONFIG_SHA256
    assert _sha256(M2_PARENT) == M2_PARENT_SHA256
    assert _sha256(M0_PARENT) == M0_PARENT_SHA256
    assert audit["design_config"] == {
        "path": "configs/phase6_m2_algorithm_performance_design_v1_0.yaml",
        "sha256": CONFIG_SHA256,
    }
    assert config["parent_evidence"]["M2_formal_mechanism_results"]["audit_sha256"] == M2_PARENT_SHA256
    assert config["parent_evidence"]["M0_algorithm_performance_results"]["audit_sha256"] == M0_PARENT_SHA256
    assert m2["aggregate"]["completed_primary_run_count"] == 50
    assert m2["aggregate"]["optimal_primary_run_count"] == 50
    assert m2["fingerprints"] == audit["parent_evidence"]["M2_formal_mechanism_results"]["fingerprints"]
    assert m0["aggregate"]["M0_E3_algorithm_performance_gate_passed"] is True
    assert len(m0["runs"]) == 21
    assert len(m0["pairs"]) == 63
    assert sum(
        len(row["cold_repetitions"]) + len(row["warm_repetitions"])
        for row in m0["technical_repetition_evidence"]
    ) == 246


def test_two_item_budget_and_capacity_are_independently_recomputed() -> None:
    config = _config()
    matrix = yaml.safe_load(MATRIX.read_text(encoding="utf-8"))
    m2c2 = yaml.safe_load(M2C2.read_text(encoding="utf-8"))
    baseline = recompute_m2c2_deterministic_baseline(matrix, m2c2)
    model = config["scientific_model"]

    assert model["tier_id"] == "M2AP2"
    assert (model["item_count"], model["periods"]) == (2, 6)
    assert math.isclose(model["reference_budget"], baseline["reference_budget"], rel_tol=0.0, abs_tol=1e-9)
    assert config["budget_sequence"]["budgets"] == [
        baseline["budgets"]["1.1"], baseline["budgets"]["1.3"]
    ]
    assert len(model["storage_capacity"]) == 6
    assert all(
        math.isclose(actual, expected, rel_tol=0.0, abs_tol=1e-9)
        for actual, expected in zip(model["storage_capacity"], baseline["storage_capacity"], strict=True)
    )
    assert model["runner_must_recompute_budget_capacity_and_identity_before_scenario_generation"] is True


def test_seed_sets_are_exact_disjoint_and_not_reused() -> None:
    seeds = _config()["seed_protocol"]
    assert tuple(seeds["pilot_seeds"]) == PILOT
    assert tuple(seeds["formal_performance_seeds"]) == FORMAL
    assert set(PILOT).isdisjoint(FORMAL)

    selected = {str(value) for value in PILOT + FORMAL}
    observed: set[str] = set()
    marker = "phase6_m2_algorithm_performance_design_v1_0"
    for folder in (ROOT / "configs", ROOT / "docs", ROOT / "src", ROOT / "tests"):
        for path in folder.rglob("*"):
            if not path.is_file() or marker in path.name:
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json", ".md", ".py", ".csv"}:
                continue
            observed.update(re.findall(r"\b20\d{8}\b", path.read_text(encoding="utf-8", errors="ignore")))
    assert selected.isdisjoint(observed)
    assert seeds["formal_seeds_may_not_be_selected_using_pilot_speed_results"] is True


def test_pilot_and_formal_workloads_are_exact_cartesian_products() -> None:
    config = _config()
    pilot = config["pilot_protocol"]
    formal = config["formal_matrix"]

    assert pilot["pilot_primary_sequence_count"] == len(PILOT) * 2 == 6
    assert pilot["planned_algorithm_solve_count"] == len(PILOT) * 2 * 2 * 3 == 36
    assert pilot["speed_direction_may_not_gate_or_modify_formal_matrix"] is True
    assert pilot["pilot_completion_does_not_authorize_formal_execution"] is True

    assert formal["primary_sequence_count"] == len(FORMAL) * 2 == 20
    assert formal["budget_pair_count"] == len(FORMAL) * 2 * 2 == 40
    assert formal["planned_algorithm_execution_count"] == len(FORMAL) * 2 * 2 * 2 * 3 == 240
    assert formal["technical_repetitions_are_not_independent_samples"] is True
    assert formal["execution_order"]["budget_index_0"] == [
        "standard_CCG_cold", "SPW_CCG_cross_budget_warm"
    ]
    assert formal["execution_order"]["budget_index_1"] == [
        "SPW_CCG_cross_budget_warm", "standard_CCG_cold"
    ]


def test_exactness_common_random_numbers_and_claim_boundaries_are_frozen() -> None:
    config = _config()
    budgets = config["budget_sequence"]
    crn = config["common_random_numbers"]
    claims = config["algorithms"]["claim_boundary"]
    gate = config["correctness_gate"]

    assert budgets["betas"] == [1.1, 1.3]
    assert budgets["SPW_CCG_first_budget_has_no_prior_budget_transfer"] is True
    assert budgets["SPW_CCG_second_budget_reuses_only_exact_scenarios_from_first_budget"] is True
    assert budgets["full_exact_oracle_retained_at_every_budget"] is True
    assert crn["required_equal_components_across_C0_and_T03"] == [
        "latent_draw", "demand", "emergency_price", "emergency_supply", "scenario_order"
    ]
    assert crn["cold_and_warm_use_identical_joint_scenario_set_and_order"] is True
    assert claims == {
        "direct_comparison": "standard_CCG_cold_complete_workflow_vs_SPW_CCG_cross_budget_warm_complete_workflow",
        "pure_SPW_structure_effect_identified": False,
        "pure_solver_variable_warm_start_effect_identified": False,
        "M2_speedup_may_not_be_extrapolated_to_unrun_profiles_or_scales": True,
    }
    assert gate["objective_tolerance_source"] == "existing_frozen_M2_objective_consistency_tolerance"
    assert gate["failed_timeout_invalid_duplicate_missing_or_diagnostic_primary_allowed"] == 0
    assert gate["any_failure_stops_entire_batch"] is True


def test_primary_estimator_and_nonselective_reporting_rule_are_frozen() -> None:
    config = _config()
    stats = config["statistical_protocol"]
    interpretation = config["pre_registered_interpretation"]
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))

    assert stats["independent_unit"] == "formal_performance_seed"
    assert stats["per_budget_speedup"]["formula"] == "median_cold_seconds_divided_by_median_warm_seconds"
    assert stats["primary_estimand"] == {
        "name": "T03_beta_1_3_cross_budget_transfer_speedup",
        "formula": "exp_median_across_ten_seeds_of_log_q_seed_T03_beta_1_3",
        "first_budget_beta_1_1_excluded_because_no_prior_budget_transfer": True,
    }
    assert stats["confirmatory_disruption_enhancement_estimand"] == {
        "name": "paired_T03_vs_C0_beta_1_3_speedup_ratio",
        "per_seed_formula": "log_q_seed_T03_beta_1_3_minus_log_q_seed_C0_beta_1_3",
        "aggregate_formula": "exp_median_across_ten_seeds_of_paired_log_speedup_difference",
    }
    assert stats["end_to_end_sequence_speedup"] == {
        "role": "secondary_descriptive",
        "per_seed_profile_formula": "sum_median_cold_seconds_across_two_budgets_divided_by_sum_median_warm_seconds_across_two_budgets",
        "aggregate_formula": "exp_median_across_ten_seeds_of_log_per_seed_end_to_end_speedup",
        "geometric_mean_of_two_budget_speed_ratios_forbidden_as_end_to_end_measure": True,
    }
    assert stats["bootstrap"] == {
        "method": "paired_seed_cluster_percentile",
        "random_number_generator": "numpy_Generator_PCG64DXSM",
        "random_seed": 2026091299,
        "resamples": 10000,
        "confidence_level": 0.95,
        "primary_statistic": "exp_median_resampled_log_q_seed_T03_beta_1_3",
        "confirmatory_disruption_enhancement_statistic": "exp_median_resampled_beta_1_3_T03_minus_C0_log_speedup",
    }
    assert stats["P_values_planned"] is False
    assert interpretation["M0_results_may_not_be_deleted_or_rewritten"] is True
    assert interpretation["M2_results_may_not_be_hidden_if_unfavorable"] is True
    assert interpretation["no_further_parameter_seed_profile_or_scale_search_after_formal_results"] is True
    assert interpretation["claim_M2_is_stronger_than_M0_forbidden"] is True
    assert interpretation["M2_vs_M0_cross_experiment_effect_comparison_preregistered"] is False
    assert audit["primary_estimand"]["name"] == stats["primary_estimand"]["name"]
    assert audit["primary_estimand"]["beta_1_1_excluded_because_no_prior_budget_transfer"] is True
    assert audit["confirmatory_disruption_enhancement_estimand"]["name"] == (
        stats["confirmatory_disruption_enhancement_estimand"]["name"]
    )
    assert audit["secondary_end_to_end_estimand"]["geometric_mean_of_budget_speed_ratios_forbidden"] is True
    assert audit["pre_registered_reporting_rule"] == {
        "reliable_M2_T03_acceleration_requires_correctness_and_S_point_estimate_and_CI_lower_bound_above_one": True,
        "disruption_enhancement_requires_reliable_acceleration_and_D_point_estimate_and_CI_lower_bound_above_one": True,
        "M2_vs_M0_cross_experiment_effect_not_preregistered": True,
        "claim_M2_is_stronger_than_M0_forbidden": True,
        "M0_results_always_retained": True,
        "M2_results_must_be_reported_regardless_of_direction": True,
        "further_parameter_or_seed_search_after_formal_results_forbidden": True,
    }


def test_design_only_state_has_no_execution_authority() -> None:
    config = _config()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    boundaries = config["execution_boundaries"]

    assert boundaries == {
        "runner_implemented": False,
        "pilot_authorized": False,
        "formal_authorized": False,
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
        "pilot_primary_sequences": 0,
        "pilot_algorithm_solves": 0,
        "formal_primary_sequences": 0,
        "formal_algorithm_executions": 0,
        "M0_E3_additional_runs": 0,
        "M2_mechanism_additional_runs": 0,
        "M2_OOS_additional_runs": 0,
        "M2_1_additional_runs": 0,
    }
    assert audit["execution_counts"] == {key: value for key, value in boundaries.items() if key not in {
        "runner_implemented", "pilot_authorized", "formal_authorized"
    }}
    assert audit["authorization"] == {
        "runner_implemented": False,
        "pilot_authorized": False,
        "formal_authorized": False,
    }
    assert not (ROOT / "src/phase6_m2_algorithm_performance.py").exists()
    assert not (ROOT / "src/run_phase6_m2_algorithm_performance.py").exists()
    assert config["execution_sequence_and_stop_boundaries"][
        "no_stage_may_start_before_previous_review_is_merged_and_explicitly_authorized"
    ] is True

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_design_audit.json"
PARENT = ROOT / "docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json"
CONFIG_SHA256 = "b95f741239a0c9269025f293005406827f4cb325115900a03f5ac454961bf5a1"
PARENT_SHA256 = "92f326e30b5f36b10025261382dc37335c7a00b00ee0b409aecac6573b5a24e2"
PILOT = tuple(range(2026081601, 2026081604))
PILOT_TEST = (2026081701,)
TRAIN = tuple(range(2026081401, 2026081411))
TEST = tuple(range(2026081501, 2026081511))


def _config() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def test_parent_confirmation_bytes_and_decision_are_locked() -> None:
    config = _config()
    parent = json.loads(PARENT.read_text(encoding="utf-8"))
    assert hashlib.sha256(PARENT.read_bytes()).hexdigest() == PARENT_SHA256
    assert config["parent_evidence"] == {
        "confirmation_results_pr": 51,
        "confirmation_audit": "docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json",
        "confirmation_audit_sha256": PARENT_SHA256,
        "required_parent_decision": "permit_separate_formal_extension_design_PR_only",
        "passing_betas": [1.1],
        "parent_claim_scope": "single_beta_only_budget_effect_claims_forbidden",
        "parent_formal_extension_authorized": False,
    }
    assert parent["projection"]["overall_decision"] == config["parent_evidence"]["required_parent_decision"]
    assert parent["projection"]["passing_betas"] == [1.1]
    assert parent["projection"]["claim_scope"] == "single_beta_only_budget_effect_claims_forbidden"
    assert parent["formal_extension_authorized"] is False


def test_design_bytes_and_non_executable_state_are_locked() -> None:
    config = _config()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert hashlib.sha256(CONFIG.read_bytes()).hexdigest() == CONFIG_SHA256
    assert audit["design_config"] == {
        "path": "configs/phase6_m2_formal_extension.yaml",
        "sha256": CONFIG_SHA256,
    }
    assert config["protocol_id"] == "phase6_m2_formal_extension_design_v1_0"
    assert config["status"] == "candidate_for_formal_extension_review"
    assert config["runner_namespace"] == "phase6_m2_formal_extension_v1_0"
    assert config["output_root"] == "outputs/phase6_m2_formal_extension_v1_0"
    boundaries = config["execution_boundaries"]
    assert boundaries["runner_implemented"] is False
    assert all(value == 0 for key, value in boundaries.items() if key not in {"runner_implemented", "formal_extension_authorized"})
    assert boundaries["formal_extension_authorized"] is False
    assert audit["formal_extension_authorized"] is False
    assert not (ROOT / "src/phase6_m2_formal_extension.py").exists()
    assert not (ROOT / "src/run_phase6_m2_formal_extension.py").exists()


def test_all_new_seed_sets_are_exact_disjoint_and_unused() -> None:
    config = _config()
    seeds = config["seed_protocol"]
    assert tuple(seeds["pilot_seeds"]) == PILOT
    assert tuple(seeds["pilot_test_seeds"]) == PILOT_TEST
    assert tuple(seeds["formal_training_seeds"]) == TRAIN
    assert tuple(seeds["formal_test_seeds"]) == TEST
    assert set(PILOT).isdisjoint(TRAIN)
    assert set(PILOT).isdisjoint(TEST)
    assert set(PILOT_TEST).isdisjoint(PILOT)
    assert set(PILOT_TEST).isdisjoint(TRAIN)
    assert set(PILOT_TEST).isdisjoint(TEST)
    assert set(TRAIN).isdisjoint(TEST)
    selected = {str(value) for value in PILOT + PILOT_TEST + TRAIN + TEST}
    observed: set[str] = set()
    for folder in (ROOT / "configs", ROOT / "docs", ROOT / "src", ROOT / "tests"):
        for path in folder.rglob("*"):
            if not path.is_file() or "phase6_m2_formal_extension" in path.name:
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json", ".md", ".py"}:
                continue
            observed.update(re.findall(r"\b20\d{8}\b", path.read_text(encoding="utf-8", errors="ignore")))
    assert selected.isdisjoint(observed)
    assert seeds["formal_training_test_pairing"] == "same_list_position_one_to_one"
    assert seeds["all_four_sets_pairwise_disjoint"] is True
    assert list(zip(TRAIN, TEST, strict=True)) == [
        (2026081401 + index, 2026081501 + index) for index in range(10)
    ]


def test_formal_mechanism_matrix_and_claim_scope_are_exact() -> None:
    config = _config()
    model = config["scientific_model"]
    design = config["mechanism_experiment"]
    assert model["tier_id"] == "M2F2"
    assert (model["item_count"], model["periods"], model["training_scenario_count"]) == (2, 6, 100)
    assert math.isclose(model["reference_budget"], 2337.610924158743, abs_tol=1e-12)
    primary = design["primary_track"]
    secondary = design["secondary_track"]
    assert primary == {
        "beta": 1.1,
        "budget": 2571.372016574617,
        "profiles": ["C0", "C1", "T03"],
        "formal_run_count": 30,
        "role": "primary_two_item_endogenous_reserve_validation",
    }
    assert secondary["beta"] == 1.3
    assert secondary["profiles"] == ["C0", "T03"]
    assert secondary["formal_run_count"] == 20
    assert secondary["primary_estimand"] == "paired_T03_minus_C0_robust_autonomous_reserve_ratio"
    assert secondary["budget_effect_claims_forbidden"] is True
    assert len(TRAIN) * len(primary["profiles"]) == 30
    assert len(TRAIN) * len(secondary["profiles"]) == 20
    assert design["total_formal_run_count"] == 50
    assert design["run_all_cases_without_adaptive_stopping"] is True
    assert design["configuration_changes_after_observing_results_forbidden"] is True
    crn = design["common_random_numbers_within_training_seed_across_all_betas_and_profiles"]
    assert crn["required_equal_components"] == [
        "latent_draw", "demand", "emergency_price", "emergency_supply", "scenario_order"
    ]
    scope = config["scope_extension_under_current_review"]
    assert scope == {
        "parent_directly_supports_primary_beta": 1.1,
        "requested_secondary_boundary_beta": 1.3,
        "inherited_parent_authorization_for_secondary_beta": False,
        "secondary_beta_requires_explicit_approval_in_this_design_PR": True,
        "secondary_purpose": "within_beta_T03_minus_C0_disruption_amplification_only",
        "cross_beta_budget_effect_estimation_forbidden": True,
    }


def test_pilot_cannot_select_or_authorize_formal_design() -> None:
    pilot = _config()["pilot_protocol"]
    assert pilot["runner_must_be_approved_in_separate_PR"] is True
    assert pilot["mechanism_run_count"] == len(PILOT) * 5 == 15
    assert pilot["out_of_sample_throughput_probe"] == {
        "pilot_training_seed": 2026081601,
        "pilot_test_seed": 2026081701,
        "training_and_test_seeds_must_differ": True,
        "pilot_test_seed_must_be_disjoint_from_all_pilot_training_and_formal_seeds": True,
        "beta": 1.1,
        "profile": "T03",
        "strategy_count": 5,
        "test_scenario_count": 2000,
    }
    assert pilot["reserve_activation_may_not_change_formal_design"] is True
    assert pilot["pilot_completion_does_not_authorize_formal_execution"] is True


def test_out_of_sample_design_closes_100000_paired_evaluations() -> None:
    oos = _config()["out_of_sample_strategy_experiment"]
    assert oos["core_configuration"] == {"beta": 1.1, "profile": "T03"}
    assert oos["training_seed_count"] == oos["paired_test_seed_count"] == 10
    assert oos["test_scenarios_per_pair"] == 2000
    assert oos["strategies"] == [
        "endogenous_reserve",
        "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10",
        "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    ]
    assert oos["plan_count"] == 10 * 5 == 50
    assert oos["exact_recourse_evaluation_count"] == 10 * 5 * 2000 == 100000
    assert oos["every_strategy_reoptimizes_regular_procurement"] is True
    assert oos["reuse_other_strategy_first_stage_plan_forbidden"] is True
    assert oos["test_scenario_reoptimization_forbidden"] is True
    assert oos["common_test_scenarios_across_strategies_within_training_test_pair"] is True
    assert oos["best_fixed_ratio_selection"] == {
        "candidate_rhos": [0.1, 0.3, 0.5],
        "selection_data": "training_scenarios_only",
        "criterion": "minimum_exact_training_robust_objective",
        "deterministic_tie_break": "smallest_rho",
        "test_scenarios_or_test_metrics_for_selection_forbidden": True,
    }
    assert oos["first_stage_plan_identity"] == {
        "endogenous_reserve": {
            "source": "complete_extensive_model_R_min_opt_endpoint",
            "arbitrary_initial_R_star_plan_forbidden": True,
        },
        "zero_autonomous_reserve": {"reserve_formula": "R_min_feas"},
        "fixed_autonomous_reserve": {
            "reserve_formula": "R_min_feas_plus_rho_times_budget_minus_R_min_feas",
            "rho": [0.1, 0.3, 0.5],
        },
        "every_strategy_fixed_reserve_then_reoptimizes_regular_procurement": True,
        "required_plan_identity_fields": [
            "reserve_amount", "regular_purchase_sha256", "exact_training_objective",
            "training_joint_scenario_set_sha256", "finalized_plan_artifact_sha256",
        ],
        "OOS_worker_reads_finalized_plan_artifact_only": True,
        "OOS_worker_reoptimization_or_plan_substitution_forbidden": True,
    }


def test_statistical_unit_bootstrap_and_wilcoxon_are_fully_frozen() -> None:
    stats = _config()["statistical_protocol"]
    assert stats["independent_unit"] == "formal_training_seed"
    assert stats["technical_repetitions_are_not_independent_samples"] is True
    assert stats["scenario_budget_profile_and_strategy_rows_are_not_independent_samples"] is True
    assert stats["bootstrap"] == {
        "method": "paired_cluster_percentile",
        "cluster_unit": "formal_training_seed",
        "random_seed": 2026081499,
        "resamples": 10000,
        "confidence_level": 0.95,
        "point_estimator": "arithmetic_mean_of_ten_seed_level_paired_differences",
        "paired_difference_direction": "strategy_or_treatment_A_minus_comparator_B",
        "resampling_algorithm": "sample_ten_training_seed_pairs_with_replacement_then_recompute_arithmetic_mean",
        "median_effect_role": "descriptive_supplement_only",
    }
    assert stats["wilcoxon"] == {
        "test": "paired_two_sided_signed_rank",
        "unit": "one_paired_summary_per_formal_training_seed",
        "zero_method": "pratt",
        "method": "approx",
        "correction": False,
        "all_zero_differences_rule": "statistic_zero_p_value_one",
    }
    assert stats["p_values_role"] == "supportive_not_sole_evidence"
    assert stats["effect_sizes_and_confidence_intervals_required"] is True
    assert stats["no_strong_budget_effect_claim"] is True
    assert stats["multiple_testing"] == {
        "familywise_alpha": 0.05,
        "mechanism_primary_family": "holm_two_tests",
        "out_of_sample_primary_family": "holm_five_tests",
        "secondary_estimands": "descriptive_unadjusted_and_explicitly_labeled",
    }


def test_compute_gate_is_numeric_and_initially_closed() -> None:
    gate = _config()["compute_gate"]
    assert gate == {
        "projection_uses_completed_pilot_wall_time_and_sampled_peak_RSS": True,
        "mechanism_formal_projected_wall_hours_maximum": 72.0,
        "out_of_sample_formal_projected_wall_hours_maximum": 72.0,
        "combined_extension_projected_wall_hours_maximum": 168.0,
        "per_solver_call_seconds": 120,
        "mechanism_case_wall_seconds": 900,
        "OOS_plan_wall_seconds": 7200,
        "failed_timeout_invalid_or_missing_pilot_units_allowed": 0,
        "compute_gate_passed_initial": False,
        "formal_extension_authorized_initial": False,
    }


def test_sequence_requires_review_between_every_scientific_batch() -> None:
    config = _config()
    sequence = config["execution_sequence_and_stop_boundaries"]
    assert sequence["sequence"] == [
        "formal_runner_implementation_PR",
        "technical_pilot_15_mechanism_runs_and_one_OOS_probe",
        "pilot_results_PR_and_compute_gate_review",
        "formal_mechanism_50_runs",
        "mechanism_results_PR_review",
        "formal_OOS_100000_exact_recourse_evaluations",
        "OOS_results_PR_review",
        "separate_algorithm_performance_design_and_execution",
        "final_paper_synthesis",
    ]
    assert sequence["no_stage_may_start_before_previous_results_PR_is_reviewed_and_merged"] is True
    safety = config["reproducibility_and_safety"]
    assert safety["python"] == "3.12.10"
    assert safety["gurobipy"] == safety["gurobi_optimizer"] == "13.0.2"
    assert safety["pyomo_interface"] == "gurobi_direct"
    assert safety["threads"] == 1
    assert safety["M0_M1_M2_development_and_confirmation_authorizations_do_not_authorize_this_protocol"] is True


def test_machine_audit_matches_the_frozen_design() -> None:
    config = _config()
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_extension_design_v1_0"
    assert audit["status"] == "candidate_design_pending_review"
    assert audit["base_main_merge_commit"] == "9b3dce465edf38179ccb5d3544835f702a32fb4c"
    assert audit["seed_design"]["pilot"] == list(PILOT)
    assert audit["seed_design"]["pilot_test"] == list(PILOT_TEST)
    assert audit["seed_design"]["formal_training"] == list(TRAIN)
    assert audit["seed_design"]["formal_test"] == list(TEST)
    assert audit["scientific_design"]["total_formal_mechanism_runs"] == 50
    assert audit["out_of_sample_design"]["exact_recourse_evaluations"] == 100000
    assert audit["pilot_design"]["OOS_probe_training_seed"] == 2026081601
    assert audit["pilot_design"]["OOS_probe_test_seed"] == 2026081701
    assert audit["first_stage_plan_identity"] == {
        "endogenous_source": "complete_extensive_model_R_min_opt_endpoint",
        "zero_autonomous_reserve_formula": "R_min_feas",
        "fixed_reserve_formula": "R_min_feas_plus_rho_times_budget_minus_R_min_feas",
        "fixed_rhos": [0.1, 0.3, 0.5],
        "every_strategy_reoptimizes_regular_procurement": True,
        "OOS_worker_reads_finalized_plan_artifact_only": True,
        "OOS_worker_reoptimization_or_substitution_forbidden": True,
    }
    assert audit["statistics"]["bootstrap"]["point_estimator"] == (
        "arithmetic_mean_of_ten_seed_level_paired_differences"
    )
    assert audit["statistics"]["bootstrap"]["resampling_algorithm"] == (
        "sample_ten_training_seed_pairs_with_replacement_then_recompute_arithmetic_mean"
    )
    assert audit["execution_counts"] == {
        "pilot_runs": 0,
        "formal_mechanism_runs": 0,
        "formal_OOS_plans": 0,
        "formal_OOS_recourse_evaluations": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
    }
    assert audit["formal_extension_authorized"] is False

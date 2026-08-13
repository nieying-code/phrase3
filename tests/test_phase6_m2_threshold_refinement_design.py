import hashlib
import itertools
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_threshold_refinement.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_design_audit.json"
PARENT_AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json"

BETAS = [0.9, 1.1, 1.3]
PROFILE_ORDER = ["C1", "T03", "T04", "T05", "C2"]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_threshold_refinement_design_is_frozen_but_not_executable() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    parent = json.loads(PARENT_AUDIT.read_text(encoding="utf-8"))

    assert config["protocol_id"] == "phase6_m2_threshold_refinement_v1_0"
    assert config["status"] == "candidate_design_pending_review"
    assert config["refinement_preregistration"]["execution_allowed_in_this_revision"] is False
    assert config["stop_rules"]["formal_extension_authorized"] is False
    assert set(config["execution_boundaries"].values()) == {0}
    assert set(audit["execution_counts_in_this_pr"].values()) == {0}
    assert audit["design_implementation_commit"] == "dd47401"
    assert audit["draft_pr"] == "https://github.com/nieying-code/phrase3/pull/46"
    assert audit["validation"] == {
        "design_audit_passed": 2,
        "ordinary_regression_passed": 284,
        "phase5_end_to_end_passed": 6,
        "compileall_passed": True,
        "git_diff_check_passed": True,
        "scenario_generation_count": 0,
        "gurobi_call_count": 0,
    }

    assert audit["base_merge_sha"] == "aa3a3aa48e44cc5978afdc08da2d380a1fa4c4b0"
    assert audit["base_tree_sha"] == "6745efb0fa4073355c57f0e0a819340e365fb037"
    assert audit["design_artifacts"]["config_sha256"] == _sha256(CONFIG)
    prereg = ROOT / audit["design_artifacts"]["preregistration_path"]
    assert audit["design_artifacts"]["preregistration_sha256"] == _sha256(prereg)
    assert audit["parent_evidence"]["audit_sha256"] == _sha256(PARENT_AUDIT)
    assert audit["parent_evidence"]["run_artifact_mapping_sha256"] == parent["mapping_hashes"]["run_artifact_mapping_sha256"]
    assert audit["parent_evidence"]["science_evidence_mapping_sha256"] == parent["mapping_hashes"]["science_evidence_mapping_sha256"]

    seeds = config["refinement_preregistration"]["seeds"]
    betas = config["refinement_preregistration"]["beta"]
    profiles = config["refinement_preregistration"]["profiles"]
    assert seeds == [2026081201, 2026081202, 2026081203]
    assert betas == BETAS
    assert profiles == {
        "T03": {"enabled": True, "loss_scale": 0.3, "recovery_fraction": 0.0},
        "T04": {"enabled": True, "loss_scale": 0.4, "recovery_fraction": 0.0},
        "T05": {"enabled": True, "loss_scale": 0.5, "recovery_fraction": 0.0},
    }
    cartesian = list(itertools.product(seeds, betas, profiles))
    assert len(cartesian) == config["refinement_preregistration"]["configuration_count"] == 27
    assert len(set(cartesian)) == 27
    assert config["refinement_preregistration"]["all_profiles_run_without_adaptive_stopping"] is True

    assert config["anchor_profiles"]["C1"]["loss_scale"] == 0.2
    assert config["anchor_profiles"]["C2"]["loss_scale"] == 0.6
    assert config["anchor_profiles"]["anchors_count_toward_new_matrix"] is False
    assert config["anchor_profiles"]["C1"]["substantive_activation_runs"] == 0
    assert config["anchor_profiles"]["C2"]["substantive_activation_runs"] == 9
    expected_lower = {
        str(beta): {"optimal_seed_count": 3, "substantive_activation_seed_count": 0}
        for beta in BETAS
    }
    expected_upper = {
        str(beta): {"optimal_seed_count": 3, "substantive_activation_seed_count": 3}
        for beta in BETAS
    }
    assert config["anchor_profiles"]["C1"]["activation_by_beta"] == expected_lower
    assert config["anchor_profiles"]["C2"]["activation_by_beta"] == expected_upper
    assert audit["parent_evidence"]["lower_anchor"]["activation_by_beta"] == expected_lower
    assert audit["parent_evidence"]["upper_anchor"]["activation_by_beta"] == expected_upper

    reserve = config["reserve_identification"]
    assert reserve["numerical_activation_ratio_strictly_greater_than"] == 1e-4
    assert reserve["substantive_activation_ratio_greater_than_or_equal_to"] == 0.01
    assert reserve["moderate_autonomous_reserve_ratio_interval"] == [0.05, 0.5]
    assert config["machine_gates"]["combination_activation"]["minimum_substantive_activation_seed_count"] == 2
    assert config["machine_gates"]["moderate_activation"]["minimum_seed_count_in_moderate_interval"] == 2
    moderate = config["machine_gates"]["moderate_activation"]
    assert moderate["requires_combination_activation_gate_passed"] is True
    assert moderate["formula"] == "combination_activation_gate_passed_and_moderate_seed_count_greater_than_or_equal_to_2"
    threshold = config["machine_gates"]["threshold_bracket"]
    assert threshold == {
        "evaluated_independently_by_beta": True,
        "ordered_profiles": PROFILE_ORDER,
        "identify_first_ascending_loss_scale_with_combination_activation": True,
        "lower_endpoint_is_previous_tested_scale_or_C1_anchor": True,
        "upper_endpoint_is_first_passing_scale": True,
        "activation_status_must_be_monotone_nondecreasing": True,
        "numerical_reserve_ratio_monotonicity_required": False,
        "nonmonotone_status": "nonmonotone_activation_pattern",
        "nonmonotone_beta_threshold_bracket_allowed": False,
        "nonmonotone_beta_multi_item_candidate_allowed": False,
    }
    assert config["machine_gates"]["selection_metrics_excluded"] == [
        "cost", "service_level", "P95", "CVaR95", "wall_time", "manual_trend"
    ]
    assert config["stop_rules"] == {
        "no_activated_refinement_combination": "no_intermediate_activation_and_stop",
        "activation_without_any_moderate_combination": "boundary_jump_and_stop",
        "activation_and_moderate_combination": "permit_separate_multi_item_design_PR_only",
        "nonmonotone_beta": "exclude_beta_from_threshold_and_multi_item_candidates",
        "parameter_chasing_or_new_loss_scales_after_results": "forbidden",
        "formal_extension_authorized": False,
    }
    assert audit["independent_identity"] == {
        "protocol_id": config["protocol_id"],
        "runner_namespace": config["runner_namespace"],
        "output_root": config["output_root"],
        "inherits_parent_authorization": False,
        "inherits_parent_registry_or_projection": False,
    }
    assert audit["reviewed_design_head"] == "8b859c0f41f438f22db0948818c18071cd71c3f0"
    assert audit["github_actions"] == {
        "run_id": 31664853790,
        "url": "https://github.com/nieying-code/phrase3/actions/runs/31664853790",
        "linux": "success",
        "windows": "success",
    }


def _classify_activation_sequence(statuses: list[bool]) -> tuple[str, int | None]:
    first_active = next((index for index, active in enumerate(statuses) if active), None)
    if first_active is None:
        return "no_activation", None
    if any(not active for active in statuses[first_active:]):
        return "nonmonotone_activation_pattern", None
    return "monotone_activation", first_active


def _moderate_gate(combination_activation_gate_passed: bool, moderate_seed_count: int) -> bool:
    return combination_activation_gate_passed and moderate_seed_count >= 2


def test_threshold_and_moderate_gate_truth_tables_are_unambiguous() -> None:
    assert _classify_activation_sequence([False, False, True, True, True]) == ("monotone_activation", 2)
    assert _classify_activation_sequence([False, True, False, True, True]) == (
        "nonmonotone_activation_pattern", None
    )
    assert _classify_activation_sequence([False] * 5) == ("no_activation", None)

    assert _moderate_gate(False, 3) is False
    assert _moderate_gate(True, 1) is False
    assert _moderate_gate(True, 2) is True

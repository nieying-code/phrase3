from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_grid_audit.json"
SEEDS = (2026081201, 2026081202, 2026081203)
BETAS = (0.9, 1.1, 1.3)
PROFILES = ("T03", "T04", "T05")
FINGERPRINTS = {
    "scientific_config_sha256": "488f86d69c442844471feb37c9a701e2ecda54111ba5a3bc2baa47f2d38462f0",
    "e3_component_sha256": "2daab29a67a41b9bfc6c7f4af0346a278892f0586949cd367f8d88bab9747532",
    "family_component_sha256": "4437be632ef293a38cd229ae8eac693dbbe9739d1656ffeb303d4e5d72824635",
    "runner_config_sha256": "80f51004dd94cd14d8d3536d9facd33ff115cf9c49abc52adfde285e0eff40f5",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def case_id(seed: int, beta: float, profile: str) -> str:
    return f"V1_seed{seed}_beta{beta:.2f}_profile{profile}".replace(".", "p")


def test_threshold_refinement_grid_rebuilds_all_scientific_gates() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "development_grid_complete_pending_review"
    assert audit["execution"] == {
        "branch": "results/phase6-m2-threshold-refinement",
        "run_id_prefix": "m2refine_v1_20260813",
        "git_sha": "516b6eea1af45b9c1df083963f4ce6eace41425c",
        "git_tree_sha": "a489cdaba0932897e2f4eba6686e4778c40c43c7",
        "working_tree_dirty": False,
        "untracked_execution_input_count_at_start": 0,
        "strictly_serial": True,
    }
    assert audit["fingerprints"] == FINGERPRINTS
    runs = audit["runs"]
    expected = {(seed, beta, profile) for seed, beta, profile in itertools.product(SEEDS, BETAS, PROFILES)}
    assert len(runs) == 27
    assert {(row["seed"], row["beta"], row["profile_id"]) for row in runs} == expected
    assert len({row["run_id"] for row in runs}) == 27
    for row in runs:
        assert row["case_id"] == case_id(row["seed"], row["beta"], row["profile_id"])
        assert row["run_id"] == f"m2refine_v1_20260813_{row['case_id']}"
        assert row["status"] == "optimal" and row["parent_run_id"] is None
        assert row["fingerprints"] == FINGERPRINTS
        assert row["git_sha"] == audit["execution"]["git_sha"]
        assert row["git_tree_sha"] == audit["execution"]["git_tree_sha"]
        assert row["scenario_identity_count"] == 50
        assert row["solver"] == "gurobi_direct" and row["threads"] == 1
        assert row["gurobi_optimizer_version"] == row["gurobipy_version"] == "13.0.2"
        assert all(len(value) == 64 for value in row["artifacts"].values())
        robust = max(0.0, row["R_min_opt"] - row["R_min_feas"])
        ratio = robust / row["budget"]
        assert math.isclose(row["R_disc_robust"], robust, abs_tol=1e-9)
        assert math.isclose(row["R_disc_robust_ratio"], ratio, abs_tol=1e-12)
        assert row["numerical_activation"] == (ratio > 1e-4)
        assert row["substantive_activation"] == (ratio >= .01)
        assert row["minimum_endpoint_status"] == row["maximum_endpoint_status"] == "optimal"
        assert abs(row["minimum_endpoint_consistency_difference"]) <= row["objective_tolerance"] + 1e-8
        assert abs(row["maximum_endpoint_consistency_difference"]) <= row["objective_tolerance"] + 1e-8
        assert not any(value for endpoint in row["endpoint_failure_counts"].values() for value in endpoint.values())
        assert [item["rho"] for item in row["fixed_reserve_policies"]] == [0.0, .1, .3, .5]
        assert all(item["status"] == "optimal" and item["regular_purchase_reoptimized"] for item in row["fixed_reserve_policies"])

    artifact_mapping = {row["run_id"]: row["artifacts"] for row in runs}
    fields = ("case_id", "seed", "beta", "profile_id", "budget", "R_star", "R_min_feas", "R_min_opt", "R_max_opt", "R_disc_robust", "R_disc_robust_ratio", "numerical_activation", "substantive_activation", "joint_scenario_set_sha256")
    science_mapping = {row["run_id"]: {field: row[field] for field in fields} for row in runs}
    assert audit["mapping_hashes"] == {
        "run_artifact_mapping_sha256": canonical(artifact_mapping),
        "science_evidence_mapping_sha256": canonical(science_mapping),
    }

    component_fields = ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256")
    for seed, beta in itertools.product(SEEDS, BETAS):
        group = [row for row in runs if row["seed"] == seed and row["beta"] == beta]
        assert len(group) == 3
        for field in component_fields:
            assert len({row["scenario_component_set_sha256"][field] for row in group}) == 1

    recorded = {(row["beta"], row["profile_id"]): row for row in audit["projection"]["combinations"]}
    for beta, profile in itertools.product(BETAS, PROFILES):
        group = [row for row in runs if row["beta"] == beta and row["profile_id"] == profile]
        substantive = sum(row["substantive_activation"] for row in group)
        moderate = sum(.05 <= row["R_disc_robust_ratio"] <= .5 for row in group)
        item = recorded[(beta, profile)]
        assert item["completed_seed_count"] == 3
        assert item["substantive_activation_seed_count"] == substantive
        assert item["moderate_seed_count"] == moderate
        assert item["combination_activation_gate_passed"] == (substantive >= 2)
        assert item["moderate_gate_passed"] == (substantive >= 2 and moderate >= 2)
        assert item["eligible_moderate_combination"] == (profile == "T03" and beta in {1.1, 1.3})
    assert audit["projection"]["common_random_numbers_verified"] is True
    assert all(item["activation_sequence"] == [False, True, True, True, True] for item in audit["projection"]["beta_assessments"])
    assert audit["projection"]["eligible_moderate_combinations"] == [{"beta": 1.1, "profile_id": "T03"}, {"beta": 1.3, "profile_id": "T03"}]
    assert audit["projection"]["overall_decision"] == "permit_separate_multi_item_design_PR_only"
    assert audit["projection"]["development_activation_gate_passed"] is True
    assert audit["projection"]["moderate_activation_gate_passed"] is True
    assert audit["projection"]["formal_extension_authorized"] is False
    assert audit["execution_boundaries"] == {"refinement_development_runs": 27, "diagnostic_runs": 0, "pilot_runs": 0, "formal_extension_runs": 0, "multi_item_confirmation_runs": 0, "M0_E3_runs": 0}

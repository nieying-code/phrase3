from __future__ import annotations

import hashlib
import itertools
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_grid_audit.json"
PARENT_AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json"
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
PARENT_AUDIT_SHA256 = "01e3025566c0701f41b4fde6b51d1e13347068e8b8c025873c2578cfbdb349a2"
PARENT_MAPPING_HASHES = {
    "run_artifact_mapping_sha256": "5e8dedaf26113bf1602bcf9813265a77990b734540e25a2bef314a9940b6275a",
    "science_evidence_mapping_sha256": "619c40b858ca32728f33b2cccb32df150ef957307ab9d62840ab0037f285c4b0",
}
GLOBAL_ARTIFACTS = {
    "registry_sha256": "4c45bb31d6b8c3af44036ca2b8beb98edc48d9bfbfd9fde5c85043f4cf66ef89",
    "projection_sha256": "7de6f348f1f0d38851faf6d8e3a35d5f6e729a204903d6cef1d60938b3f2f3c7",
}


def canonical(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def case_id(seed: int, beta: float, profile: str) -> str:
    return f"V1_seed{seed}_beta{beta:.2f}_profile{profile}".replace(".", "p")


def test_threshold_refinement_grid_rebuilds_all_scientific_gates() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    parent = json.loads(PARENT_AUDIT.read_text(encoding="utf-8"))
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
    assert hashlib.sha256(PARENT_AUDIT.read_bytes()).hexdigest() == PARENT_AUDIT_SHA256
    assert parent["mapping_hashes"] == PARENT_MAPPING_HASHES
    assert audit["parent_evidence"] == {
        "audit_path": "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json",
        "audit_sha256": PARENT_AUDIT_SHA256,
        "draft_pr": "https://github.com/nieying-code/phrase3/pull/45",
        **PARENT_MAPPING_HASHES,
        "C1_record_count": 9,
        "C2_record_count": 9,
    }
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

    parent_rows = {
        (row["seed"], row["beta"], row["profile_id"]): row
        for row in parent["runs"] if row["profile_id"] in {"C1", "C2"}
    }
    assert len(parent_rows) == 18
    component_fields = ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256")
    for seed, beta in itertools.product(SEEDS, BETAS):
        group = [row for row in runs if row["seed"] == seed and row["beta"] == beta]
        assert len(group) == 3
        c1_components = parent_rows[(seed, beta, "C1")]["scenario_component_set_sha256"]
        for field in component_fields:
            assert {row["scenario_component_set_sha256"][field] for row in group} == {c1_components[field]}

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
    rebuilt_assessments = []
    rebuilt_candidates = []
    scales = {"C1": .2, "T03": .3, "T04": .4, "T05": .5, "C2": .6}
    profile_order = ("C1", "T03", "T04", "T05", "C2")
    for beta in BETAS:
        c1_count = sum(parent_rows[(seed, beta, "C1")]["substantive_activation"] for seed in SEEDS)
        c2_count = sum(parent_rows[(seed, beta, "C2")]["substantive_activation"] for seed in SEEDS)
        assert c1_count == 0 and c2_count == 3
        sequence = [False]
        for profile in PROFILES:
            sequence.append(recorded[(beta, profile)]["substantive_activation_seed_count"] >= 2)
        sequence.append(True)
        first = next((index for index, active in enumerate(sequence) if active), None)
        nonmonotone = first is not None and any(not active for active in sequence[first:])
        assert first == 1 and nonmonotone is False
        bracket = {
            "lower_profile": profile_order[first - 1], "upper_profile": profile_order[first],
            "lower_loss_scale": scales[profile_order[first - 1]], "upper_loss_scale": scales[profile_order[first]],
        }
        candidates = [
            {"beta": beta, "profile_id": profile}
            for profile in PROFILES
            if recorded[(beta, profile)]["combination_activation_gate_passed"]
            and recorded[(beta, profile)]["moderate_seed_count"] >= 2
        ]
        rebuilt_candidates.extend(candidates)
        rebuilt_assessments.append((beta, sequence, bracket, candidates))
    actual_assessments = [
        (item["beta"], item["activation_sequence"], item["threshold_bracket"], item["eligible_moderate_combinations"])
        for item in audit["projection"]["beta_assessments"]
    ]
    assert actual_assessments == rebuilt_assessments
    assert rebuilt_candidates == [{"beta": 1.1, "profile_id": "T03"}, {"beta": 1.3, "profile_id": "T03"}]
    assert audit["projection"]["common_random_numbers_verified"] is True
    assert audit["projection"]["eligible_moderate_combinations"] == rebuilt_candidates
    expected_decision = "permit_separate_multi_item_design_PR_only" if rebuilt_candidates else "boundary_jump_and_stop"
    assert audit["projection"]["overall_decision"] == expected_decision
    assert audit["projection"]["development_activation_gate_passed"] is True
    assert audit["projection"]["moderate_activation_gate_passed"] is True
    assert audit["projection"]["formal_extension_authorized"] is False
    assert audit["projection"]["status"] == "complete"
    for field in ("invalid_primary_run_ids", "invalid_diagnostic_run_ids", "diagnostic_run_ids", "duplicate_case_ids", "failed_primary_run_ids", "finalization_failure_run_ids"):
        assert audit["projection"][field] == []
    rebuilt_aggregate = {
        "optimal_run_count": sum(row["status"] == "optimal" for row in runs),
        "numerical_activation_run_count": sum(row["numerical_activation"] for row in runs),
        "substantive_activation_run_count": sum(row["substantive_activation"] for row in runs),
        "max_R_disc_robust_ratio": max(row["R_disc_robust_ratio"] for row in runs),
        "max_endpoint_consistency_difference": max(max(abs(row["minimum_endpoint_consistency_difference"]), abs(row["maximum_endpoint_consistency_difference"])) for row in runs),
        "total_wall_seconds": sum(row["wall_seconds"] for row in runs),
        "peak_memory_mb": max(row["peak_memory_mb"] for row in runs),
    }
    for field, value in rebuilt_aggregate.items():
        assert math.isclose(audit["aggregate"][field], value, abs_tol=1e-12)
    assert audit["global_artifacts"] == GLOBAL_ARTIFACTS
    assert audit["execution_boundaries"] == {"refinement_development_runs": 27, "diagnostic_runs": 0, "pilot_runs": 0, "formal_extension_runs": 0, "multi_item_confirmation_runs": 0, "M0_E3_runs": 0}

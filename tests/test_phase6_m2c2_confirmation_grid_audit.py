from __future__ import annotations

import json
import math
import re
from pathlib import Path

from src.phase6_m2 import _sha256_payload


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
SEEDS = (2026081301, 2026081302, 2026081303, 2026081304, 2026081305)
BETAS = (1.1, 1.3)
PROFILES = ("C0", "C1", "T03")
REFERENCE_BUDGET = 2337.610924158743
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "2c514e6045ad5efaf2e4e9418192b44f12f79db0f0b4a95b6f78056d64a5740d",
    "e3_component_sha256": "6637f7c799a5afedec8a3e782d08ca7a7605246e6ec470779b93537142fb707c",
    "family_component_sha256": "62c114bc26e310db636c6e6505272ff8d24d1725fad69037d44e1ef7e5971159",
    "runner_config_sha256": "c6f82101b05d13fe03e36c07d1de60aef7c226fa26f7ea788d0a76456ed4464c",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _load() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _case_id(seed: int, beta: float, profile: str) -> str:
    beta_token = f"{beta:.2f}".replace(".", "p")
    return f"M2C2_seed{seed}_beta{beta_token}_profile{profile}"


def test_m2c2_confirmation_audit_is_independently_closed() -> None:
    audit = _load()
    runs = audit["runs"]
    assert audit["audit_id"] == "phase6_m2c2_confirmation_grid_v1_0"
    assert audit["status"] == "confirmation_grid_complete_pending_review"
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert audit["execution"] == {
        "branch": "results/phase6-m2c2-confirmation-grid",
        "run_id_prefix": "m2c2_confirm_v1_20260814",
        "git_sha": "0a036571410e86aeb56e0be778c9644405696104",
        "git_tree_sha": "97997bcfab2a7630716b7a8112a72eb93b8bb3ff",
        "working_tree_dirty": False,
        "untracked_execution_input_count_at_start": 0,
        "strictly_serial": True,
    }

    expected_cases = {
        _case_id(seed, beta, profile)
        for seed in SEEDS for beta in BETAS for profile in PROFILES
    }
    expected_runs = {f"m2c2_confirm_v1_20260814_{case}" for case in expected_cases}
    assert len(runs) == 30
    assert {row["case_id"] for row in runs} == expected_cases
    assert {row["run_id"] for row in runs} == expected_runs
    assert len({row["run_id"] for row in runs}) == 30

    by_key = {}
    artifact_mapping = {}
    science_fields = (
        "case_id", "seed", "beta", "profile_id", "budget", "R_star",
        "R_min_feas", "R_min_opt", "R_max_opt", "R_disc_robust",
        "R_disc_robust_ratio", "numerical_activation",
        "substantive_activation", "moderate_activation",
        "joint_scenario_set_sha256",
    )
    science_mapping = {}
    for row in runs:
        key = (row["seed"], row["beta"], row["profile_id"])
        by_key[key] = row
        assert row["case_id"] == _case_id(*key)
        assert row["run_id"] == f"m2c2_confirm_v1_20260814_{row['case_id']}"
        assert row["tier_id"] == "M2C2"
        assert row["parent_run_id"] is None
        assert row["status"] == "optimal"
        assert row["git_sha"] == audit["execution"]["git_sha"]
        assert row["git_tree_sha"] == audit["execution"]["git_tree_sha"]
        assert row["fingerprints"] == EXPECTED_FINGERPRINTS
        assert row["source_working_tree_dirty"] is False
        assert row["untracked_execution_input_count_at_start"] == 0
        assert math.isclose(row["reference_budget"], REFERENCE_BUDGET, abs_tol=1e-12)
        assert math.isclose(row["budget"], row["beta"] * REFERENCE_BUDGET, abs_tol=1e-9)
        assert row["storage_capacity"] == [
            288.75, 294.841333698683, 294.841333698683,
            288.75, 203.908666301317, 203.90866630131694,
        ]
        assert row["scenario_identity_count"] == 50
        assert row["solver"] == "gurobi_direct"
        assert row["gurobi_optimizer_version"] == "13.0.2"
        assert row["gurobipy_version"] == "13.0.2"
        assert row["threads"] == 1
        assert row["minimum_endpoint_status"] == "optimal"
        assert row["maximum_endpoint_status"] == "optimal"
        assert all(
            value == 0
            for endpoint in row["endpoint_failure_counts"].values()
            for value in endpoint.values()
        )

        robust = max(0.0, row["R_min_opt"] - row["R_min_feas"])
        ratio = robust / row["budget"]
        assert math.isclose(row["R_disc_robust"], robust, abs_tol=1e-8)
        assert math.isclose(row["R_disc_robust_ratio"], ratio, abs_tol=1e-12)
        assert row["numerical_activation"] == (ratio > 1e-4)
        assert row["substantive_activation"] == (ratio >= 0.01)
        assert row["moderate_activation"] == (0.05 <= ratio <= 0.50)

        policies = row["fixed_reserve_policies"]
        assert [item["rho"] for item in policies] == [0.0, 0.1, 0.3, 0.5]
        for policy in policies:
            expected_reserve = row["R_min_feas"] + policy["rho"] * (
                row["budget"] - row["R_min_feas"]
            )
            assert math.isclose(policy["reserve"], expected_reserve, abs_tol=1e-8)
            assert policy["status"] == "optimal"
            assert policy["regular_purchase_reoptimized"] is True
            assert SHA256.fullmatch(policy["regular_purchase_sha256"])

        cross = row["cross_item_allocation"]
        assert cross["plan_source"] == "complete_extensive_model_R_min_opt_endpoint"
        assert math.isclose(cross["endpoint_reserve"], row["R_min_opt"], abs_tol=1e-8)
        assert cross["endpoint_regular_purchase_sha256"] == row["minimum_endpoint_regular_purchase_sha256"]
        assert math.isclose(cross["endpoint_exact_objective"], row["minimum_endpoint_exact_objective"], abs_tol=1e-8)
        assert cross["scenario_count"] == 50
        assert SHA256.fullmatch(cross["scenario_item_emergency_spend_sha256"])
        expected_cross_gate = (
            cross["positive_total_emergency_spend_scenario_count"] >= 2
            and cross["both_items_each_positive_in_at_least_one_scenario"]
            and cross["item1_emergency_spend_share_range"] >= 1e-4
        )
        assert cross["gate_passed"] == expected_cross_gate

        if row["profile_id"] == "C0":
            c0 = row["c0_equivalence"]
            assert c0["required"] is True and c0["status"] == "passed"
            assert c0["fulfillment_exactly_one"] is True
            assert c0["scenario_count_each_direction"] == 50

        for value in row["artifacts"].values():
            assert SHA256.fullmatch(value)
        for value in row["scenario_component_set_sha256"].values():
            assert SHA256.fullmatch(value)
        assert SHA256.fullmatch(row["joint_scenario_set_sha256"])
        artifact_mapping[row["run_id"]] = row["artifacts"]
        science_mapping[row["run_id"]] = {field: row[field] for field in science_fields}

    assert audit["mapping_hashes"] == {
        "run_artifact_mapping_sha256": _sha256_payload(artifact_mapping),
        "science_evidence_mapping_sha256": _sha256_payload(science_mapping),
    }
    assert audit["mapping_hashes"] == {
        "run_artifact_mapping_sha256": "9afd5a1b4cdbafb8df518178ac1ea3bf9ae72f47cb54fddad46367d5571b8b4d",
        "science_evidence_mapping_sha256": "a321954e8103cb42e71f96845c55419623a44f3600d5cda6faeaf7685b847d54",
    }

    # C0/C1/T03 share every random component except fulfillment.
    paired_fields = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256",
    )
    for seed in SEEDS:
        for beta in BETAS:
            rows = [by_key[(seed, beta, profile)] for profile in PROFILES]
            for field in paired_fields:
                assert len({row["scenario_component_set_sha256"][field] for row in rows}) == 1

    combinations = {}
    beta_pass = {}
    for beta in BETAS:
        for profile in PROFILES:
            group = [by_key[(seed, beta, profile)] for seed in SEEDS]
            combinations[(beta, profile)] = {
                "completed_seed_count": sum(row["status"] == "optimal" for row in group),
                "substantive_activation_seed_count": sum(row["substantive_activation"] for row in group),
                "moderate_seed_count": sum(row["moderate_activation"] for row in group),
                "cross_item_gate_seed_count": sum(row["cross_item_allocation"]["gate_passed"] for row in group),
                "C0_equivalence_seed_count": sum(row["c0_equivalence"].get("status") == "passed" for row in group),
            }
        c0, c1, t03 = (combinations[(beta, profile)] for profile in PROFILES)
        beta_pass[beta] = (
            c0["completed_seed_count"] == 5
            and c1["completed_seed_count"] == 5
            and t03["completed_seed_count"] == 5
            and c0["substantive_activation_seed_count"] == 0
            and c0["C0_equivalence_seed_count"] == 5
            and t03["substantive_activation_seed_count"] >= 3
            and t03["moderate_seed_count"] >= 3
            and t03["substantive_activation_seed_count"] > c1["substantive_activation_seed_count"]
            and t03["cross_item_gate_seed_count"] >= 3
        )
    assert beta_pass == {1.1: True, 1.3: False}

    projection = audit["projection"]
    assert projection["status"] == "complete"
    assert projection["verified_primary_run_count"] == 30
    for key in (
        "invalid_primary_run_ids", "invalid_diagnostic_run_ids", "diagnostic_run_ids",
        "duplicate_case_ids", "failed_primary_run_ids", "finalization_failure_run_ids",
    ):
        assert projection[key] == []
    assert projection["common_random_numbers_verified"] is True
    assert projection["passing_betas"] == [1.1]
    assert projection["claim_scope"] == "single_beta_only_budget_effect_claims_forbidden"
    assert projection["overall_decision"] == "permit_separate_formal_extension_design_PR_only"
    assert projection["confirmation_gate_passed"] is True
    assert projection["formal_extension_authorized"] is False

    aggregate = audit["aggregate"]
    assert aggregate["optimal_run_count"] == 30
    assert aggregate["numerical_activation_run_count"] == sum(row["numerical_activation"] for row in runs)
    assert aggregate["substantive_activation_run_count"] == sum(row["substantive_activation"] for row in runs)
    assert aggregate["moderate_activation_run_count"] == sum(row["moderate_activation"] for row in runs)
    assert math.isclose(aggregate["max_R_disc_robust_ratio"], max(row["R_disc_robust_ratio"] for row in runs))
    assert math.isclose(aggregate["total_wall_seconds"], sum(row["wall_seconds"] for row in runs))
    assert math.isclose(aggregate["peak_memory_mb"], max(row["peak_memory_mb"] for row in runs))
    assert audit["global_artifacts"] == {
        "registry_sha256": "8afbac529e3d0f90b5bd6760b47449e17d7766be3d919e89f9413ab53e649012",
        "projection_sha256": "32b080dce691bf3006eea4a3a71f1f5d88114cdc28c43cfff3b35a91aa32e5cb",
    }
    assert audit["execution_boundaries"] == {
        "M2C2_confirmation_runs": 30,
        "diagnostic_runs": 0,
        "pilot_runs": 0,
        "formal_extension_runs": 0,
        "M0_E3_runs": 0,
    }
    assert audit["formal_extension_authorized"] is False

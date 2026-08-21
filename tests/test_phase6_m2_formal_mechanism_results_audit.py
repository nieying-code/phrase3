from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import statistics


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
EXPECTED_GROUP_COUNTS = {
    (1.1, "C0"): (0, 0, 0),
    (1.1, "C1"): (0, 0, 0),
    (1.1, "T03"): (6, 5, 6),
    (1.3, "C0"): (0, 0, 0),
    (1.3, "T03"): (10, 10, 7),
}


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_formal_mechanism_run_identity_and_artifact_mapping_are_exact():
    audit = load_audit()
    runs = audit["runs"]
    expected_cases = {
        (seed, beta, profile)
        for seed in range(2026081401, 2026081411)
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    }
    assert len(runs) == 50
    assert {(row["seed"], row["beta"], row["profile_id"]) for row in runs} == expected_cases
    assert len({row["run_id"] for row in runs}) == len({row["case_id"] for row in runs}) == 50
    for row in runs:
        assert row["run_id"] == f"formal_m2_v1_1_20260821_{row['case_id']}"
        assert row["tier_id"] == "M2F2"
        assert row["status"] == "optimal"
        assert row["parent_run_id"] is None
        assert row["git_sha"] == "a761e1f5c1c2049ddcba0a91e16d0c9e1fd1a70c"
        assert row["git_tree_sha"] == "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69"
        assert row["fingerprints"] == EXPECTED_FINGERPRINTS
        assert row["formal_orchestrator_sha256"] == (
            "a09fd3a71bc04ac748fb85c6acbcec2a387a3e589ba9cdd23c7753090c2322f1"
        )
        assert set(row["artifacts"]) == {
            "result_sha256", "manifest_sha256", "checkpoint_sha256",
            "status_summary_sha256", "heartbeat_sha256",
        }
        assert all(SHA256.fullmatch(value) for value in row["artifacts"].values())
    mapping = {row["run_id"]: row["artifacts"] for row in runs}
    assert canonical_sha256(mapping) == audit["run_artifact_mapping_sha256"] == (
        "e63e0db7269b2a252d11f9879f9477520a0777b9689c9d07f4f81545ff1037fe"
    )
    science_mapping = {row["run_id"]: row["science"] for row in runs}
    assert canonical_sha256(science_mapping) == audit["science_evidence_mapping_sha256"] == (
        "144709109d02812ea86bbf8b1600cea0df9403f8464cf9d94c97d98b890e03f8"
    )


def test_reserve_activation_endpoints_and_fixed_policies_recompute():
    runs = load_audit()["runs"]
    for row in runs:
        science = row["science"]
        budget = science["budget"]
        assert math.isclose(budget, row["beta"] * science["reference_budget"], abs_tol=1e-9)
        reserve = max(0.0, science["R_min_opt"] - science["R_min_feas"])
        ratio = reserve / budget
        assert math.isclose(reserve, science["R_disc_robust"], abs_tol=1e-9)
        assert math.isclose(ratio, science["R_disc_robust_ratio"], abs_tol=1e-12)
        assert science["numerical_activation"] is (ratio > 1e-4)
        assert science["substantive_activation"] is (ratio >= 0.01)
        assert science["moderate_activation"] is (
            science["substantive_activation"] and 0.05 <= ratio <= 0.50
        )
        assert science["minimum_endpoint_status"] == science["maximum_endpoint_status"] == "optimal"
        for field in (
            "minimum_endpoint_consistency_difference",
            "maximum_endpoint_consistency_difference",
        ):
            difference = science[field]
            assert math.isfinite(difference) and difference >= 0
            assert difference <= science["objective_tolerance"] + 1e-8
        for endpoint in science["endpoint_failure_counts"].values():
            assert endpoint == {"infeasible": 0, "solver_failure": 0, "missing": 0}
        assert science["training_scenario_count"] == science["scenario_identity_count"] == 100
        assert science["solver"] == "gurobi_direct"
        assert science["gurobipy_version"] == "13.0.2"
        assert science["gurobi_optimizer_version"] == "13.0.2"
        assert science["threads"] == 1
        policies = science["fixed_reserve_policies"]
        assert [item["rho"] for item in policies] == [0.0, 0.1, 0.3, 0.5]
        for policy in policies:
            expected = science["R_min_feas"] + policy["rho"] * (
                budget - science["R_min_feas"]
            )
            assert math.isclose(policy["reserve"], expected, abs_tol=1e-9)
            assert policy["status"] == "optimal"
            assert policy["regular_purchase_reoptimized"] is True


def test_c0_crn_plan_identity_and_cross_item_evidence_are_bounded():
    runs = load_audit()["runs"]
    crn_fields = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256",
    )
    for seed in range(2026081401, 2026081411):
        selected = [row for row in runs if row["seed"] == seed]
        for field in crn_fields:
            assert len({row["science"]["scenario_component_set_sha256"][field] for row in selected}) == 1
    for row in runs:
        science = row["science"]
        cross = science["cross_item_allocation"]
        assert cross["plan_source"] == "complete_extensive_model_R_min_opt_endpoint"
        assert math.isclose(cross["endpoint_reserve"], science["R_min_opt"], abs_tol=1e-9)
        assert cross["endpoint_regular_purchase_sha256"] == science["minimum_endpoint_regular_purchase_sha256"]
        assert math.isclose(cross["endpoint_exact_objective"], science["minimum_endpoint_exact_objective"], abs_tol=1e-8)
        assert cross["scenario_count"] == 100
        assert SHA256.fullmatch(cross["scenario_item_emergency_spend_sha256"])
        recomputed_gate = (
            cross["positive_total_emergency_spend_scenario_count"] >= 2
            and cross["both_items_each_positive_in_at_least_one_scenario"]
            and cross["item1_emergency_spend_share_range"] >= 1e-4
        )
        assert cross["gate_passed"] is recomputed_gate
        if row["profile_id"] == "C0":
            c0 = science["c0_equivalence"]
            assert c0["required"] is True and c0["status"] == "passed"
            assert c0["fulfillment_exactly_one"] is True
            assert c0["scenario_count_each_direction"] == 100
        if row["beta"] == 1.1 and row["profile_id"] == "T03":
            plans = science["first_stage_plan_identities"]
            assert set(plans) == {
                "endogenous_reserve", "zero_autonomous_reserve",
                "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
                "fixed_autonomous_reserve_0_50",
            }
            assert plans["endogenous_reserve"]["reserve_amount"] == science["R_min_opt"]
            assert plans["zero_autonomous_reserve"]["reserve_amount"] == science["R_min_feas"]
            assert all(SHA256.fullmatch(item["finalized_plan_artifact_sha256"]) for item in plans.values())
        else:
            assert science["first_stage_plan_identities"] is None


def test_group_summaries_progress_and_stop_boundary_recompute():
    audit = load_audit()
    runs = audit["runs"]
    recomputed = []
    for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03"))):
        for profile in profiles:
            selected = [row for row in runs if row["beta"] == beta and row["profile_id"] == profile]
            ratios = [row["science"]["R_disc_robust_ratio"] for row in selected]
            row = {
                "beta": beta,
                "profile_id": profile,
                "run_count": len(selected),
                "numerical_activation_count": sum(item["science"]["numerical_activation"] for item in selected),
                "substantive_activation_count": sum(item["science"]["substantive_activation"] for item in selected),
                "moderate_activation_count": sum(item["science"]["moderate_activation"] for item in selected),
                "R_disc_robust_ratio_min": min(ratios),
                "R_disc_robust_ratio_median": statistics.median(ratios),
                "R_disc_robust_ratio_max": max(ratios),
                "cross_item_allocation_gate_count": sum(item["science"]["cross_item_allocation"]["gate_passed"] for item in selected),
            }
            recomputed.append(row)
            assert (
                row["substantive_activation_count"],
                row["moderate_activation_count"],
                row["cross_item_allocation_gate_count"],
            ) == EXPECTED_GROUP_COUNTS[(beta, profile)]
    assert recomputed == audit["group_summaries"]
    aggregate = audit["aggregate"]
    assert aggregate["completed_primary_run_count"] == aggregate["optimal_primary_run_count"] == 50
    assert aggregate["minimum_endpoint_exact_recourse_evaluation_count"] == 5000
    assert aggregate["maximum_endpoint_exact_recourse_evaluation_count"] == 5000
    assert aggregate["fixed_policy_optimization_count"] == 200
    assert math.isclose(aggregate["total_wall_seconds"], sum(row["wall_seconds"] for row in runs), abs_tol=1e-9)
    assert aggregate["max_peak_memory_mb"] == max(row["peak_memory_mb"] for row in runs)
    assert aggregate["max_R_disc_robust_ratio"] == max(row["science"]["R_disc_robust_ratio"] for row in runs)
    progress = audit["progress"]
    assert progress["status"] == "complete"
    assert progress["required_primary_run_count"] == progress["completed_primary_run_count"] == 50
    for field in (
        "missing_case_ids", "invalid_primary_run_ids", "failed_primary_run_ids",
        "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids",
    ):
        assert progress[field] == []
    assert progress["common_random_numbers_verified"] is True
    assert progress["formal_mechanism_gate_passed"] is True
    assert progress["next_decision"] == "permit_mechanism_results_review_only"
    assert progress["formal_OOS_authorized"] is False
    assert audit["global_artifacts"] == {
        "formal_mechanism_run_registry_sha256": "d418a1a10e9a995365f38f0110c682fb70e709a7deb8127ec039d5d9f0958eb3",
        "formal_mechanism_progress_sha256": "5b02066db0a1bbe205042a9ab7abd454b678c81643e38c50459681e2ce5cab6e",
    }
    assert audit["stop_boundary"] == {
        "formal_mechanism_gate_passed": True,
        "next_decision": "permit_mechanism_results_review_only",
        "formal_OOS_authorized": False,
        "formal_OOS_runs_started": 0,
        "algorithm_performance_runs_started": 0,
        "M0_E3_runs_started": 0,
    }


def test_execution_tree_is_the_reviewed_merged_main_tree():
    baseline = load_audit()["execution_baseline"]
    assert baseline == {
        "execution_git_sha": "a761e1f5c1c2049ddcba0a91e16d0c9e1fd1a70c",
        "execution_git_tree_sha": "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69",
        "merged_main_sha": "9d836911de47cb4025078cb9412a8389b63992db",
        "merged_main_tree_sha": "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69",
        "execution_tree_equals_merged_main_tree": True,
        "tracked_worktree_dirty_at_start": False,
        "untracked_execution_input_count_at_start": 0,
    }

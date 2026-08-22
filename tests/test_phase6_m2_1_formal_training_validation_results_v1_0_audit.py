import hashlib
import json
import math
from pathlib import Path

from src.phase6_m2_1_endpoint_selection import (
    CANDIDATE_IDS,
    PLAN_IDENTITY_FIELDS,
    select_validation_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_formal_training_validation_results_v1_0_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "d5af07fc57c6b0a88ad2d09a3171c6854a08bbd4db5c91bdf8753adb3c509ebe",
    "e3_component_sha256": "e6444ac18bab5db5032860276e829af1b52103d9bbe92240ebecb8eb98fbf47c",
    "family_component_sha256": "67058c0aab89bdc6ca1722539320733ffc1b8c22e362599289f0e92bace740f5",
    "runner_config_sha256": "065426e037c57a4fa1872298b68793d9de68279320187eb55ae0f3955a120d35",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
EXPECTED_GLOBAL_ARTIFACTS = {
    "formal_training_validation_run_registry_sha256": "75c49b0f58d03a40fc87aa0ae638a9ae6faf50e55c078876d21fc4742b033cac",
    "formal_training_validation_projection_sha256": "dca3cd29946bd53aae91b387760c51044b32b9d910d64d27030c31bb05d74295",
    "reviewed_pilot_audit_sha256": "fe63e0e8965503eceb1e0ec99f9e9f9906de322a756e5a3e9fcfbf6f7ddee74b",
    "reviewed_pilot_registry_sha256": "557ea06ea074a4625d0c89524080c3a38f9cff2d80c62bd9e896bb8c2259f553",
    "reviewed_pilot_projection_sha256": "42200d72ee02a304383f3d04a0f7749b29db5df1d5994b385dbfa1b256e5f058",
}


def _load():
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _canonical_sha(value):
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def test_execution_identity_and_ten_triplets_are_exactly_locked():
    audit = _load()
    execution = audit["execution"]
    assert execution["git_sha"] == execution["pr68_merge_commit"] == (
        "adda64a395eb9752676d290e5c82ac59de068b68"
    )
    assert execution["git_tree_sha"] == execution["pr68_merge_tree_sha"] == (
        "71aeb9e93803db0fc0326373836b9c08403fbba4"
    )
    assert execution["execution_tree_equals_merged_main_tree"] is True
    assert execution["working_tree_dirty_at_start"] is False
    assert execution["untracked_execution_input_count_at_start"] == 0
    assert (execution["python_version"], execution["gurobi_optimizer_version"]) == ("3.12.10", "13.0.2")
    assert execution["gurobipy_version"] == "13.0.2"
    assert execution["pyomo_interface"] == "gurobi_direct" and execution["threads"] == 1
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    runs = audit["runs"]
    assert len(runs) == 10
    assert [row["triplet_position"] for row in runs] == list(range(1, 11))
    assert [row["training_seed"] for row in runs] == list(range(2026090101, 2026090111))
    assert [row["validation_seed"] for row in runs] == list(range(2026090201, 2026090211))
    assert [row["reserved_test_seed"] for row in runs] == list(range(2026090301, 2026090311))
    assert all((row["tier_id"], row["beta"], row["profile_id"]) == ("M2F2", 1.1, "T03") for row in runs)
    assert all(row["status"] == "optimal" and row["finalized"] and row["parent_run_id"] is None for row in runs)


def test_formal_test_data_was_not_generated_or_evaluated():
    audit = _load()
    for row in audit["runs"]:
        assert row["test_scenario_count"] == 0
        assert row["test_results_empty"] is True
        assert row["test_scenario_identity_is_null"] is True
    assert all(value == 0 for value in audit["stop_boundary"].values())


def test_validation_plan_scenario_evaluation_and_selection_close_independently():
    audit = _load()
    optimal_count = 0
    selected = []
    for row in audit["runs"]:
        assert row["training_scenario_count"] == 100
        assert row["validation_scenario_count"] == 2000
        assert row["R_min_feas"] <= row["R_min_opt"] <= row["R_max_opt"]
        assert math.isfinite(row["objective_tolerance"]) and row["objective_tolerance"] >= 0
        candidates = row["candidates"]
        assert tuple(candidates) == CANDIDATE_IDS
        scenario_identities = [candidate["scenario_identity"] for candidate in candidates.values()]
        assert all(identity == scenario_identities[0] for identity in scenario_identities)
        assert scenario_identities[0] == row["validation_scenario_identity"]
        metrics_for_selection = {}
        for candidate_id, candidate in candidates.items():
            plan = candidate["plan_identity"]
            evaluation = candidate["evaluation"]
            assert plan["training_joint_scenario_set_sha256"] == row["training_scenario_identity"]["scenario_set_sha256"]
            difference = abs(plan["exact_training_objective"] - row["complete_extensive_objective"])
            assert difference <= row["objective_tolerance"] + 1e-8
            assert evaluation["plan_oos_status"] == "complete_feasible"
            assert evaluation["total_scenario_count"] == evaluation["optimal_scenario_count"] == 2000
            assert evaluation["infeasible_scenario_count"] == evaluation["solver_failure_count"] == 0
            for field in ("mean_total_cost", "total_cost_cvar95", "service_level"):
                assert math.isfinite(evaluation[field])
            metrics_for_selection[candidate_id] = {
                "total_cost_cvar95": evaluation["total_cost_cvar95"],
                "mean_total_cost": evaluation["mean_total_cost"],
                "reserve": plan["reserve_amount"],
            }
            optimal_count += evaluation["optimal_scenario_count"]
        recomputed = select_validation_candidate(metrics_for_selection)
        assert recomputed == row["validation_selection"]
        assert recomputed["selected_candidate_id"] == row["selected_candidate_id"]
        selected.append(row["selected_candidate_id"])
    assert optimal_count == 10 * 3 * 2000 == 60000
    assert selected.count("minimum_endpoint") == 2
    assert selected.count("interval_midpoint") == 0
    assert selected.count("maximum_endpoint") == 8


def test_artifact_science_mappings_aggregates_and_gate_close():
    audit = _load()
    artifact_mapping = {
        row["run_id"]: {
            "result_sha256": row["result_sha256"],
            "manifest_sha256": row["manifest_sha256"],
            "status_summary_sha256": row["status_summary_sha256"],
        }
        for row in audit["runs"]
    }
    science_mapping = {
        row["run_id"]: {
            "case_id": row["case_id"],
            "selected_candidate_id": row["selected_candidate_id"],
            "candidates": row["candidates"],
        }
        for row in audit["runs"]
    }
    assert _canonical_sha(artifact_mapping) == audit["mapping_sha256"]["run_artifact_mapping_sha256"] == (
        "4c1298f6b547ddcd6746d7b917211b0e4c59d438811c8a195e230fb572d155c4"
    )
    assert _canonical_sha(science_mapping) == audit["mapping_sha256"]["science_evidence_mapping_sha256"] == (
        "f56df5f4d2faf5b568c111f61458677da2669490751eb963cbd41b2805e347b7"
    )
    aggregate = audit["aggregate"]
    assert aggregate["completed_primary_run_count"] == aggregate["optimal_primary_run_count"] == 10
    assert aggregate["validation_candidate_plan_count"] == 30
    assert aggregate["validation_optimal_recourse_evaluation_count"] == 60000
    assert math.isclose(aggregate["total_wall_seconds"], sum(row["wall_seconds"] for row in audit["runs"]), abs_tol=1e-9)
    assert aggregate["maximum_triplet_wall_seconds"] == max(row["wall_seconds"] for row in audit["runs"])
    assert aggregate["maximum_peak_memory_mb"] == max(row["peak_memory_mb"] for row in audit["runs"])
    for field in ("failed_primary_run_ids", "invalid_primary_run_ids", "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids"):
        assert aggregate[field] == []
    projection = audit["projection"]
    assert projection["status"] == "complete"
    assert projection["required_primary_run_count"] == projection["verified_primary_run_count"] == 10
    assert projection["validation_candidate_plan_count"] == 30
    assert projection["validation_exact_recourse_evaluation_count"] == 60000
    selected_mapping = {
        row["case_id"]: {
            field: row["candidates"][row["selected_candidate_id"]]["plan_identity"][field]
            for field in PLAN_IDENTITY_FIELDS
        }
        for row in audit["runs"]
    }
    assert projection["selected_candidate_ids"] == [
        row["selected_candidate_id"] for row in audit["runs"]
    ]
    assert _canonical_sha(selected_mapping) == projection["selected_plan_identity_mapping_sha256"] == (
        "df515f14931e903902f15e2089b21a23ca27bcfca2c4162e9d74e0b3c631b831"
    )
    assert projection["formal_training_validation_gate_passed"] is True
    assert projection["selected_plan_freeze_authorized"] is False
    assert projection["formal_test_authorized"] is False
    assert projection["formal_extension_authorized"] is False
    assert projection["next_decision"] == "permit_separate_selected_plan_freeze_review_PR_only"
    assert audit["global_artifacts"] == EXPECTED_GLOBAL_ARTIFACTS

import hashlib
import json
import math
from pathlib import Path

from src.phase6_m2_1_endpoint_selection import (
    CANDIDATE_IDS,
    PLAN_IDENTITY_FIELDS,
    SCENARIO_IDENTITY_FIELDS,
    TEST_STRATEGIES,
    select_validation_candidate,
    validate_shared_scenario_identity,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_endpoint_selection_pilot_results_v1_0_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "1cb170cda4ea880482208419be5fe61218b4bc113eb38a756164ac9ca0a62a60",
    "e3_component_sha256": "fec163490e28069b050f7ff0aca400d6465b61d3d0d78bfcc392a82febf8d631",
    "family_component_sha256": "5bd12f12d9dc6afc3393d406c3492bd8a2e83f6c91fec9a46e9388631f213d9b",
    "runner_config_sha256": "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
EXPECTED_ARTIFACTS = {
    "m21pilot_v10_20260822a_M2_1_triplet01_train2026090401_validation2026090501_test2026090701": (
        "6dc70a37ccbe2c75cadad18356b67be68e5899bf153616363a36febd4426b6c9",
        "0b85e728a9f85ef0ff21434a7263ce0d7ec03c0a7fbe9bebeac8b18ace391c4e",
        "dd40c6a30c03373e601cb957e54792edcee5455ded7f7a142512950b4173f45b",
    ),
    "m21pilot_v10_20260822a_M2_1_triplet02_train2026090402_validation2026090502_test2026090702": (
        "786e428efc72c16352e93d2eff22c51bf6b0d6f78390cd016d52f88b8fa1d9e6",
        "5c7f213aab5d33e721a0b14d96ab1b3eeb7b6428c0186026d169045a238725bc",
        "091b90cbc3b331c7d5d9d7f74b762841f868a6af95619aa0d86ce81973f8b64a",
    ),
    "m21pilot_v10_20260822a_M2_1_triplet03_train2026090403_validation2026090503_test2026090703": (
        "4059e04c538a6226933dee57e9161afd969e229057ea767875fdf9d9e03fe0ac",
        "4c5b78e0c932dcbf1d4eed1f2e6fbb08eca22472bbbf37ffa8e6dbf3b1d831fe",
        "15e3338db5fc29e478bcc9f14441e8cd776410d1aa62ef2ec22757acda344be1",
    ),
}
EXPECTED_VALIDATION_EVIDENCE_SHA256 = "b0a1358e168d651b37965356b2947c029a3d1500e06cc6b00aae245227cb836b"
EXPECTED_TEST_PROBE_EVIDENCE_SHA256 = "ea4fb9c4a81697df1f1989f93f45ccea8e1a9aec60e2aba38a4a18c39c52e3a8"


def _load():
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _canonical_sha256(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_execution_identity_fingerprints_and_run_artifacts_are_locked():
    audit = _load()
    execution = audit["execution"]
    assert execution["git_sha"] == "7d73ab17c2e5fb8b2a5b5d3278f281706a491c72"
    assert execution["git_tree_sha"] == execution["pr66_merge_tree_sha"] == (
        "cb55b01f5dbab4279b17eb9e5ccfd5fc8b6d23f6"
    )
    assert execution["execution_tree_equals_merged_main_tree"] is True
    assert execution["working_tree_dirty_at_start"] is False
    assert execution["untracked_execution_input_count_at_start"] == 0
    assert execution["python_version"] == "3.12.10"
    assert (execution["gurobi_optimizer_version"], execution["gurobipy_version"]) == ("13.0.2", "13.0.2")
    assert execution["pyomo_interface"] == "gurobi_direct" and execution["threads"] == 1
    assert execution["strictly_serial"] is True
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    actual = {
        row["run_id"]: (row["result_sha256"], row["manifest_sha256"], row["status_summary_sha256"])
        for row in audit["runs"]
    }
    assert actual == EXPECTED_ARTIFACTS


def test_three_triplets_candidates_and_exact_recourse_counts_close():
    audit = _load()
    runs = audit["runs"]
    expected = {
        (1, 2026090401, 2026090501, 2026090701, True),
        (2, 2026090402, 2026090502, 2026090702, False),
        (3, 2026090403, 2026090503, 2026090703, False),
    }
    assert {
        (r["triplet_position"], r["training_seed"], r["validation_seed"], r["test_seed"], r["includes_test_probe"])
        for r in runs
    } == expected
    assert all(r["status"] == "optimal" and r["finalized"] and r["parent_run_id"] is None for r in runs)
    assert all((r["tier_id"], r["beta"], r["profile_id"]) == ("M2F2", 1.1, "T03") for r in runs)
    assert all(r["budget"] == 2571.372016574617 for r in runs)
    assert all(
        len(r["candidate_reserves"])
        == len(r["candidate_training_objectives"])
        == len(r["candidate_validation_cvar95"])
        == 3
        for r in runs
    )
    assert all(len(set(r["candidate_plan_sha256"])) == 3 for r in runs)
    assert all(r["selected_candidate_id"] == "minimum_endpoint" for r in runs)
    aggregate = audit["aggregate"]
    assert aggregate["completed_primary_run_count"] == aggregate["optimal_primary_run_count"] == 3
    assert aggregate["validation_candidate_plan_count"] == 3 * 3 == 9
    assert aggregate["validation_optimal_recourse_evaluation_count"] == 3 * 3 * 2000 == 18000
    assert aggregate["test_probe_plan_count"] == 6
    assert aggregate["test_probe_optimal_recourse_evaluation_count"] == 6 * 2000 == 12000


def test_candidates_are_tolerance_optimal_and_validation_is_complete():
    audit = _load()
    for row in audit["runs"]:
        assert row["R_min_feas"] <= row["R_min_opt"] <= row["R_max_opt"]
        assert len(row["training_scenario_sha256"]) == len(row["validation_scenario_sha256"]) == 64
        for objective in row["candidate_validation_cvar95"]:
            assert math.isfinite(objective) and objective > 0
        assert row["objective_tolerance"] > 0
        for objective in row["candidate_training_objectives"]:
            difference = objective - row["complete_extensive_objective"]
            assert math.isfinite(difference) and difference >= 0
            assert difference <= row["objective_tolerance"] + 1e-8


def test_validation_plan_scenario_and_evaluation_evidence_closes_independently():
    audit = _load()
    run_rows = {row["run_id"]: row for row in audit["runs"]}
    evidence = audit["validation_evidence"]
    assert _canonical_sha256(evidence) == EXPECTED_VALIDATION_EVIDENCE_SHA256
    assert set(evidence) == set(run_rows)
    optimal_evaluations = 0
    for run_id, record in evidence.items():
        run = run_rows[run_id]
        assert record["case_id"] == run["case_id"]
        candidates = record["candidates"]
        assert tuple(candidates) == CANDIDATE_IDS
        shared = validate_shared_scenario_identity(
            {candidate_id: row["scenario_identity"] for candidate_id, row in candidates.items()},
            expected_ids=CANDIDATE_IDS,
            phase="validation_audit",
        )
        assert shared["scenario_set_sha256"] == run["validation_scenario_sha256"]
        selection_metrics = {}
        for index, candidate_id in enumerate(CANDIDATE_IDS):
            candidate = candidates[candidate_id]
            assert candidate["source_run_id"] == run_id
            assert candidate["source_case_id"] == run["case_id"]
            plan = candidate["plan_identity"]
            assert tuple(plan) == PLAN_IDENTITY_FIELDS
            assert plan["finalized_plan_artifact_sha256"] == run["candidate_plan_sha256"][index]
            assert plan["reserve_amount"] == run["candidate_reserves"][index]
            assert plan["exact_training_objective"] == run["candidate_training_objectives"][index]
            assert plan["training_joint_scenario_set_sha256"] == run["training_scenario_sha256"]
            assert len(plan["regular_purchase_sha256"]) == 64
            assert tuple(candidate["scenario_identity"]) == SCENARIO_IDENTITY_FIELDS
            evaluation = candidate["evaluation"]
            assert evaluation["candidate_id"] == candidate_id
            assert evaluation["plan_oos_status"] == "complete_feasible"
            assert evaluation["total_scenario_count"] == evaluation["optimal_scenario_count"] == 2000
            assert evaluation["infeasible_scenario_count"] == evaluation["solver_failure_count"] == 0
            assert math.isfinite(evaluation["mean_total_cost"]) and evaluation["mean_total_cost"] > 0
            assert math.isfinite(evaluation["total_cost_cvar95"]) and evaluation["total_cost_cvar95"] > 0
            assert 0.0 <= evaluation["service_level"] <= 1.0
            assert evaluation["total_cost_cvar95"] == run["candidate_validation_cvar95"][index]
            selection_metrics[candidate_id] = {
                "total_cost_cvar95": evaluation["total_cost_cvar95"],
                "mean_total_cost": evaluation["mean_total_cost"],
                "reserve": plan["reserve_amount"],
            }
            optimal_evaluations += evaluation["optimal_scenario_count"]
        assert select_validation_candidate(selection_metrics) == record["selection"]
        assert record["selection"]["selected_candidate_id"] == run["selected_candidate_id"]
    assert optimal_evaluations == 3 * 3 * 2000 == 18000


def test_test_probe_plan_scenario_and_separate_evaluation_evidence_closes():
    audit = _load()
    evidence = audit["test_probe_evidence"]
    assert _canonical_sha256(evidence) == EXPECTED_TEST_PROBE_EVIDENCE_SHA256
    source_run = next(row for row in audit["runs"] if row["run_id"] == evidence["source_run_id"])
    assert evidence["source_case_id"] == source_run["case_id"]
    strategies = evidence["strategies"]
    assert tuple(strategies) == TEST_STRATEGIES
    shared = validate_shared_scenario_identity(
        {strategy_id: row["scenario_identity"] for strategy_id, row in strategies.items()},
        expected_ids=TEST_STRATEGIES,
        phase="test_probe_audit",
    )
    assert shared["scenario_set_sha256"] == source_run["test_scenario_sha256"]
    optimal_evaluations = 0
    for strategy_id, record in strategies.items():
        assert record["source_run_id"] == source_run["run_id"]
        assert record["source_case_id"] == source_run["case_id"]
        assert tuple(record["plan_identity"]) == PLAN_IDENTITY_FIELDS
        assert tuple(record["scenario_identity"]) == SCENARIO_IDENTITY_FIELDS
        plan = record["plan_identity"]
        assert all(
            len(plan[field]) == 64
            for field in (
                "finalized_plan_artifact_sha256",
                "regular_purchase_sha256",
                "training_joint_scenario_set_sha256",
            )
        )
        assert plan["training_joint_scenario_set_sha256"] == source_run["training_scenario_sha256"]
        evaluation = record["evaluation"]
        assert evaluation["strategy_id"] == strategy_id
        assert evaluation["plan_oos_status"] == "complete_feasible"
        assert evaluation["total_scenario_count"] == evaluation["optimal_scenario_count"] == 2000
        assert evaluation["infeasible_scenario_count"] == evaluation["solver_failure_count"] == 0
        assert math.isfinite(evaluation["mean_total_cost"]) and evaluation["mean_total_cost"] > 0
        assert math.isfinite(evaluation["total_cost_cvar95"]) and evaluation["total_cost_cvar95"] > 0
        assert 0.0 <= evaluation["service_level"] <= 1.0
        optimal_evaluations += evaluation["optimal_scenario_count"]
    m2 = strategies["M2_minimum_endpoint"]
    m21 = strategies["M2_1_validation_selected_endpoint"]
    assert m2["source_candidate_id"] == m21["source_candidate_id"] == "minimum_endpoint"
    assert m2["plan_identity"] == m21["plan_identity"]
    assert m2["evaluation"]["strategy_id"] != m21["evaluation"]["strategy_id"]
    assert {
        key: value for key, value in m2["evaluation"].items() if key != "strategy_id"
    } == {
        key: value for key, value in m21["evaluation"].items() if key != "strategy_id"
    }
    assert optimal_evaluations == 6 * 2000 == 12000


def test_test_probe_identity_counts_and_stop_boundary_close():
    audit = _load()
    probe = audit["test_probe"]
    assert probe["selected_candidate_id"] == "minimum_endpoint"
    assert probe["M2_and_M2_1_share_plan_artifact"] is True
    assert probe["M2_and_M2_1_test_metrics_identical"] is True
    assert probe["strategy_count"] == len(probe["strategies"]) == 6
    assert probe["optimal_recourse_evaluation_count"] == 6 * 2000 == 12000
    assert probe["infeasible_recourse_count"] == probe["solver_failure_count"] == 0
    assert probe["strategies"]["M2_minimum_endpoint"] == probe["strategies"]["M2_1_validation_selected_endpoint"]
    aggregate = audit["aggregate"]
    assert math.isclose(aggregate["total_wall_seconds"], sum(r["wall_seconds"] for r in audit["runs"]), abs_tol=1e-9)
    assert aggregate["maximum_triplet_wall_seconds"] == max(r["wall_seconds"] for r in audit["runs"])
    assert aggregate["maximum_peak_memory_mb"] == max(r["peak_memory_mb"] for r in audit["runs"])
    for field in ("failed_primary_run_ids", "invalid_primary_run_ids", "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids"):
        assert aggregate[field] == []
    projection = audit["projection"]
    assert projection["status"] == "complete"
    assert projection["required_primary_run_count"] == projection["verified_primary_run_count"] == 3
    expected_hours = aggregate["maximum_triplet_wall_seconds"] * 10 / 3600
    assert math.isclose(projection["projected_formal_wall_hours"], expected_hours, abs_tol=1e-12)
    assert projection["projected_formal_wall_hours"] <= 72.0
    assert projection["pilot_compute_gate_passed"] is True
    assert projection["next_decision"] == "permit_separate_formal_freeze_PR_only"
    assert projection["formal_extension_authorized"] is False
    assert audit["global_artifacts"] == {
        "pilot_run_registry_sha256": "557ea06ea074a4625d0c89524080c3a38f9cff2d80c62bd9e896bb8c2259f553",
        "pilot_projection_sha256": "42200d72ee02a304383f3d04a0f7749b29db5df1d5994b385dbfa1b256e5f058",
    }
    assert all(value == 0 for value in audit["stop_boundary"].values())

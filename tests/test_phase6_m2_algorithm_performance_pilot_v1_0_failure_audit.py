from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_v1_0_failure_audit.json"
SHA256 = re.compile(r"[0-9a-f]{64}")


def test_failure_identity_root_cause_and_artifact_hashes_are_exact() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["execution_identity"] == {
        "pr79_runner_merge_commit": "72c430e9c12bb3aca9d65f9d69fe257aa71591a0",
        "pr80_authorization_merge_commit": "9da8ef8bbcd3537f407272733bebbc08e4bc3b16",
        "execution_git_sha": "9da8ef8bbcd3537f407272733bebbc08e4bc3b16",
        "execution_git_tree_sha": "cd972a3c6782faec0c2ae5384e33aacec9d47524",
        "branch": "main",
        "HEAD_equal_fetched_origin_main": True,
        "working_tree_dirty": False,
    }
    failed = audit["failed_primary"]
    assert failed["run_id"] == "m2ap_pilot_v1_20260825_M2AP2_pilot_seed2026091001_profileC0"
    assert (failed["seed"], failed["profile_id"], failed["beta"], failed["algorithm"]) == (
        2026091001, "C0", 1.1, "extensive",
    )
    assert (failed["outer_status"], failed["worker_status"]) == (
        "runner_exception", "worker_exception",
    )
    assert failed["failure_stage"] == "complete_extensive_model"
    assert failed["exception_type"] == "AttributeError"
    assert failed["exception_message"] == (
        "'DisruptedProcurementData' object has no attribute 'total_budget'"
    )
    cause = audit["root_cause"]
    assert cause["invalid_access"] == "data.total_budget"
    assert cause["actual_frozen_data_field"] == "data.budget"
    assert cause["mathematical_model_failure"] is False
    assert cause["gurobi_solver_failure"] is False
    assert cause["fix_applied_in_this_PR"] is False
    assert all(SHA256.fullmatch(value) for value in audit["source_artifact_sha256"].values())


def test_failure_batch_accounting_and_stop_boundary_close_independently() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    batch = audit["batch_closure"]
    assert batch["completed_primary_sequence_count"] + batch["failed_primary_sequence_count"] + batch["not_started_primary_sequence_count"] == batch["required_primary_sequence_count"] == 6
    assert batch["attempted_algorithm_solve_count"] + batch["not_started_algorithm_solve_count"] == batch["required_algorithm_solve_count"] == 36
    assert batch["finalized_optimal_algorithm_solve_count"] == 0
    assert batch["diagnostic_run_count"] == 0
    assert batch["duplicate_primary_run_count"] == 0
    assert batch["pilot_compute_gate_passed"] is False
    assert batch["formal_authorized"] is False
    effects = audit["execution_side_effects"]
    assert effects["scenario_generation_count"] == 1
    assert effects["gurobi_call_count"] == 1
    assert effects["residual_python_or_gurobi_process_count"] == 0
    assert effects["same_run_id_retry_count"] == 0
    assert all(effects[field] == 0 for field in (
        "formal_algorithm_execution_count", "M0_E3_additional_runs",
        "M2_mechanism_additional_runs", "M2_OOS_additional_runs",
        "M2_1_additional_runs",
    ))
    disposition = audit["disposition"]
    assert disposition == {
        "failed_output_preserved": True,
        "current_namespace_may_not_be_reused_for_primary_batch": True,
        "automatic_retry_forbidden": True,
        "new_runner_fix_and_reauthorization_required": True,
        "pilot_or_formal_execution_authorized_by_this_PR": False,
    }

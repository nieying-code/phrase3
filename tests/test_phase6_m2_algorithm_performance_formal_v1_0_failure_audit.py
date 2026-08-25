from __future__ import annotations

import json
import math
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_formal_v1_0_failure_audit.json"
SHA256 = re.compile(r"[0-9a-f]{64}")


def _audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_execution_identity_failure_and_source_hashes_are_exact() -> None:
    audit = _audit()
    assert audit["status"] == "stopped_after_first_invalid_primary"
    assert audit["execution_identity"] == {
        "pr84_merge_commit": "b41d5f25f3f4f628307debe6fc4292e2a587ced3",
        "execution_git_sha": "b41d5f25f3f4f628307debe6fc4292e2a587ced3",
        "execution_git_tree_sha": "6cdb22a4fdb80240a9a7c106899e050a07346377",
        "branch": "main",
        "HEAD_equal_fetched_origin_main": True,
        "working_tree_dirty": False,
        "run_id_prefix": "m2ap_formal_v1_20260825",
    }
    assert all(SHA256.fullmatch(value) for value in audit["fingerprints"].values())
    assert all(SHA256.fullmatch(value) for value in audit["source_artifact_sha256"].values())
    failed = audit["failed_primary"]
    assert (failed["seed"], failed["profile_id"], failed["beta"]) == (
        2026091102, "T03", 1.1,
    )
    assert (failed["algorithm"], failed["repetition"]) == ("cold", 1)
    assert (failed["outer_status"], failed["worker_status"]) == (
        "evidence_invalid", "optimal",
    )
    assert failed["termination_status"] == "optimal"
    assert failed["converged"] is True


def test_roundoff_diagnosis_is_independently_recomputed() -> None:
    audit = _audit()
    failed = audit["failed_primary"]
    difference = failed["upper_bound"] - failed["lower_bound"]
    assert difference == failed["reported_gap"] == failed["upper_minus_lower"]
    assert difference < 0.0
    expected_tolerance = 1.0e-5 + 1.0e-7 * max(1.0, abs(failed["objective"]))
    assert math.isclose(
        expected_tolerance, failed["frozen_objective_tolerance"],
        rel_tol=0.0, abs_tol=1.0e-15,
    )
    assert abs(difference) < expected_tolerance
    cause = audit["root_cause"]
    assert cause["classification"] == "numerical_reporting_roundoff_at_zero_gap"
    assert cause["mathematical_model_failure"] is False
    assert cause["gurobi_solver_failure"] is False
    assert cause["fix_applied_in_this_PR"] is False


def test_primary_artifacts_batch_accounting_and_stop_boundary_close() -> None:
    audit = _audit()
    runs = audit["primary_runs"]
    assert [(row["seed"], row["profile_id"], row["status"]) for row in runs] == [
        (2026091101, "C0", "optimal"),
        (2026091101, "T03", "optimal"),
        (2026091102, "C0", "optimal"),
        (2026091102, "T03", "evidence_invalid"),
    ]
    assert len({row["run_id"] for row in runs}) == 4
    assert all(SHA256.fullmatch(row[field]) for row in runs for field in (
        "result_sha256", "manifest_sha256",
    ))
    batch = audit["batch_closure"]
    assert batch["completed_primary_sequence_count"] + batch["failed_primary_sequence_count"] + batch["not_started_primary_sequence_count"] == batch["required_primary_sequence_count"] == 20
    assert batch["completed_budget_pair_count"] + batch["failed_incomplete_budget_pair_count"] + batch["not_started_budget_pair_count"] == batch["required_budget_pair_count"] == 40
    assert batch["completed_algorithm_execution_count"] + batch["failed_evidence_algorithm_execution_count"] + batch["not_started_algorithm_execution_count"] == batch["required_algorithm_execution_count"] == 240
    assert batch["formal_algorithm_performance_gate_passed"] is False
    assert audit["execution_side_effects"]["attempted_worker_algorithm_execution_count"] == 37
    assert audit["execution_side_effects"]["residual_python_or_gurobi_process_count"] == 0
    assert audit["disposition"] == {
        "failed_output_preserved": True,
        "current_namespace_may_not_be_reused_for_primary_batch": True,
        "automatic_retry_forbidden": True,
        "diagnostic_retry_started": False,
        "new_runner_fix_and_reauthorization_required": True,
        "formal_or_other_execution_authorized_by_this_PR": False,
    }

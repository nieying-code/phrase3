from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_formal_oos import formal_oos_orchestrator_sha256


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-21_phase6_m2_formal_oos_runner_v1_1_audit.json"
APPROVAL_PATH = ROOT / "configs/phase6_m2_formal_oos_approval.yaml"
RUNNER_PATH = ROOT / "configs/phase6_m2_formal_oos_runner.yaml"
SOURCE_AUDIT_PATH = ROOT / "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def load_audit() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_reviewed_pr58_evidence_and_formal_oos_identity_are_exact():
    audit = load_audit()
    approval = yaml.safe_load(APPROVAL_PATH.read_text(encoding="utf-8"))
    runner = yaml.safe_load(RUNNER_PATH.read_text(encoding="utf-8"))
    source = json.loads(SOURCE_AUDIT_PATH.read_text(encoding="utf-8"))
    source_digest = hashlib.sha256(SOURCE_AUDIT_PATH.read_bytes()).hexdigest()
    assert audit["base"] == {
        "pr58_merge_commit": "8b5bbb9d44c8f069f3b93627b50021c4bee6a676",
        "pr58_audit_path": str(SOURCE_AUDIT_PATH.relative_to(ROOT)).replace("\\", "/"),
        "pr58_audit_sha256": source_digest,
        "formal_mechanism_registry_sha256": source["global_artifacts"]["formal_mechanism_run_registry_sha256"],
        "formal_mechanism_progress_sha256": source["global_artifacts"]["formal_mechanism_progress_sha256"],
        "formal_mechanism_orchestrator_sha256": source["formal_orchestrator_sha256"],
        "formal_mechanism_gate_passed": True,
        "formal_OOS_authorized_by_pr58": False,
    }
    assert approval["mechanism_evidence"]["audit_sha256"] == source_digest
    assert approval["mechanism_evidence"]["registry_sha256"] == audit["base"]["formal_mechanism_registry_sha256"]
    assert approval["mechanism_evidence"]["progress_sha256"] == audit["base"]["formal_mechanism_progress_sha256"]
    assert runner["namespace"] == audit["identity"]["namespace"]
    assert runner["output_root"] == audit["identity"]["output_root"]
    assert runner["source_output_root"] == audit["identity"]["source_output_root"]


def test_matrix_and_execution_counts_are_frozen_without_running_experiments():
    audit = load_audit()
    design = audit["design"]
    assert design["training_seeds"] == list(range(2026081401, 2026081411))
    assert design["test_seeds"] == list(range(2026081501, 2026081511))
    assert set(design["training_seeds"]).isdisjoint(design["test_seeds"])
    assert design["pairing"] == "same_list_position_one_to_one"
    assert design["beta"] == 1.1 and design["profile_id"] == "T03"
    assert design["strategies"] == [
        "endogenous_reserve", "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    ]
    assert design["primary_run_count"] == 10
    assert design["plan_count"] == 10 * 5 == 50
    assert design["exact_recourse_evaluation_count"] == 10 * 5 * 2000 == 100000
    assert audit["execution_counts"] == {
        "formal_OOS_primary_runs": 0,
        "formal_OOS_plans": 0,
        "formal_OOS_recourse_evaluations": 0,
        "algorithm_performance_runs": 0,
        "M0_E3_runs": 0,
    }


def test_fingerprints_and_safety_contract_are_exact():
    audit = load_audit()
    approval = yaml.safe_load(APPROVAL_PATH.read_text(encoding="utf-8"))
    orchestrator = formal_oos_orchestrator_sha256(ROOT)
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS | {
        "formal_OOS_orchestrator_sha256": orchestrator,
    }
    assert approval["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["formal_OOS_orchestrator_sha256"] == orchestrator
    assert audit["safety"] == {
        "full_primary_batch_required": True,
        "strictly_serial": True,
        "empty_output_namespace_required": True,
        "immutable_run_ids": True,
        "diagnostic_retry_requires_new_run_id_and_parent": True,
        "failed_primary_permanently_blocks_gate": True,
        "reviewed_mechanism_evidence_is_read_only": True,
        "source_plan_identity_cross_checked_against_pr58": True,
        "frozen_limits_preflight_verified": {
            "solver_call_seconds": 120,
            "OOS_plan_wall_seconds": 7200,
            "threads": 1,
        },
        "per_plan_wall_deadline_enforced_at_scenario_boundaries": True,
        "timeout_is_immutable_and_stops_later_strategies_and_runs": True,
        "native_solver_time_limit_immediately_propagates_as_timeout": True,
        "non_timeout_oracle_failure_immediately_stops_evaluation": True,
        "CLI_success_requires_formal_OOS_gate_passed": True,
        "bounded_status_bytes": 16384,
        "algorithm_performance_authorized": False,
    }

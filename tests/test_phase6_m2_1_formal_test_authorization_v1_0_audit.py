from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-23_phase6_m2_1_formal_test_authorization_v1_0_audit.json"


def test_authorization_audit_locks_artifact_runner_and_exact_matrix() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    artifact = audit["authorization_artifact"]
    assert sha256_file(ROOT / artifact["path"]) == artifact["sha256"]
    approval = yaml.safe_load((ROOT / artifact["path"]).read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["formal_test_orchestrator_sha256"] == audit["reviewed_runner"]["formal_test_orchestrator_sha256"]
    matrix = audit["authorized_matrix"]
    assert matrix["primary_run_count"] * matrix["plan_count"] // matrix["primary_run_count"] == 60
    assert matrix["plan_count"] * matrix["scenario_count_per_plan"] == matrix["exact_recourse_evaluation_count"] == 120000
    assert matrix["complete_batch_required"] is True
    assert matrix["strictly_serial"] is True


def test_authorization_audit_records_zero_execution_and_narrow_scope() -> None:
    boundary = json.loads(AUDIT.read_text(encoding="utf-8"))["execution_boundaries"]
    assert boundary["formal_test_authorized"] is True
    assert boundary["formal_extension_authorized"] is False
    assert boundary["algorithm_performance_authorized"] is False
    assert all(boundary[field] == 0 for field in (
        "scenario_generation_count", "gurobi_call_count", "formal_test_runs", "M0_E3_runs",
    ))
    assert boundary["next_decision"] == "await_explicit_user_authorization_for_complete_formal_test_batch"

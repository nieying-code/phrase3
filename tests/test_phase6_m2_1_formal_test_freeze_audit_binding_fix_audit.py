from __future__ import annotations

import json
from pathlib import Path

from src.phase6_m2_1_formal_test import formal_test_fingerprints, orchestrator_sha256
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-23_phase6_m2_1_formal_test_freeze_audit_binding_fix_audit.json"


def test_fix_audit_locks_real_failure_boundary_and_reviewed_inputs() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base"]["pr72_merge_tree"] == audit["base"]["execution_tree_used_for_preflight"]
    assert audit["failure"] == {
        "stage": "read_only_preflight",
        "message": "PR #70 freeze audit boundary mismatch",
        "scenario_generation_reached": False,
        "gurobi_reached": False,
        "output_root_created": False,
    }
    evidence = audit["reviewed_evidence"]
    assert sha256_file(ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml") == evidence["pr70_freeze_sha256"]
    assert sha256_file(ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_selected_plan_freeze_v1_0_audit.json") == evidence["pr70_freeze_audit_sha256"]
    assert sha256_file(ROOT / "configs/phase6_m2_1_formal_test_authorization_v1_0.yaml") == evidence["pr72_authorization_sha256"]
    assert sha256_file(ROOT / "src/phase6_m2_1_formal_test.py") == evidence["fixed_runner_module_sha256"]


def test_fix_changes_only_orchestrator_identity_and_requires_reauthorization() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    actual = formal_test_fingerprints(
        ROOT,
        ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml",
        ROOT / "configs/phase6_m2_1_formal_test_runner.yaml",
    )
    for field in (
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
    ):
        assert actual[field] == audit["fingerprints"][field]
    assert audit["fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    evidence = audit["reviewed_evidence"]
    assert orchestrator_sha256(ROOT) == evidence["fixed_formal_test_orchestrator_sha256"]
    assert evidence["fixed_formal_test_orchestrator_sha256"] != evidence["old_formal_test_orchestrator_sha256"]
    boundary = audit["execution_boundaries"]
    assert boundary["formal_test_authorized_for_fixed_runner"] is False
    assert all(boundary[field] == 0 for field in (
        "formal_test_runs", "scenario_generation_count", "gurobi_call_count",
        "algorithm_performance_runs", "M0_E3_runs",
    ))
    assert not (ROOT / "outputs/phase6_m2_1_formal_test_v1_0").exists()

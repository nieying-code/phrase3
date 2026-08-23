from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.phase6_m2_1_formal_test import formal_test_fingerprints, orchestrator_sha256
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_formal_test_runner_v1_0_audit.json"


def test_runner_audit_binds_reviewed_evidence_and_exact_matrix() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    evidence = audit["reviewed_evidence"]
    assert sha256_file(ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml") == evidence["selected_plan_freeze_sha256"]
    assert sha256_file(ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_selected_plan_freeze_v1_0_audit.json") == evidence["selected_plan_freeze_audit_sha256"]
    assert sha256_file(ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_formal_training_validation_results_v1_0_audit.json") == evidence["pr69_audit_sha256"]
    matrix = audit["matrix"]
    assert matrix["triplet_count"] * matrix["strategy_count_per_triplet"] == matrix["formal_test_plan_count"] == 60
    assert matrix["formal_test_plan_count"] * matrix["scenario_count_per_strategy"] == matrix["formal_test_exact_recourse_evaluation_count"] == 120000
    assert matrix["required_unique_test_scenario_set_count"] == 10
    assert matrix["required_unique_complete_test_scenario_identity_count"] == 10


def test_runner_audit_locks_code_config_and_fingerprints() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8")); artifacts = audit["artifact_sha256"]
    paths = {"runner_module":"src/phase6_m2_1_formal_test.py", "cli":"src/run_phase6_m2_1_formal_test.py", "status_module":"src/phase6_m2_1_formal_test_status.py", "runner_config":"configs/phase6_m2_1_formal_test_runner.yaml", "approval":"configs/phase6_m2_1_formal_test_approval.yaml"}
    for key, path in paths.items(): assert sha256_file(ROOT / path) == artifacts[key]
    assert orchestrator_sha256(ROOT) == artifacts["formal_test_orchestrator_sha256"]
    actual = formal_test_fingerprints(
        ROOT, ROOT/"configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml",
        ROOT/"configs/phase6_m2_1_formal_test_runner.yaml",
    )
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == audit["fingerprints"][field]
    assert len(actual["environment_sha256"]) == 64
    assert audit["fingerprints"]["environment_sha256"] == "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    approval = yaml.safe_load((ROOT / "configs/phase6_m2_1_formal_test_approval.yaml").read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == audit["fingerprints"]


def test_runner_revision_has_zero_execution_and_no_authorization() -> None:
    boundary = json.loads(AUDIT.read_text(encoding="utf-8"))["execution_boundaries"]
    assert boundary["selected_plan_freeze_authorized"] is True
    assert boundary["formal_test_runner_implemented"] is True
    assert boundary["formal_test_authorized"] is False
    assert boundary["formal_extension_authorized"] is False
    assert boundary["algorithm_performance_authorized"] is False
    assert all(boundary[field] == 0 for field in ("scenario_generation_count", "gurobi_call_count", "formal_test_runs", "M0_E3_runs"))
    assert not (ROOT / "outputs/phase6_m2_1_formal_test_v1_0").exists()

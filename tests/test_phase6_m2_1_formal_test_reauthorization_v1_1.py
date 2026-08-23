from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.phase6_m2_1_formal_test import formal_test_fingerprints, orchestrator_sha256
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "configs/phase6_m2_1_formal_test_reauthorization_v1_1.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-23_phase6_m2_1_formal_test_reauthorization_v1_1_audit.json"


def test_reauthorization_binds_pr73_fix_and_exact_runner() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    reviewed = approval["reviewed_runner_fix"]
    assert reviewed["pr73_merge_commit"] == audit["base"]["pr73_merge_commit"]
    assert reviewed["pr73_merge_tree"] == audit["base"]["pr73_merge_tree"]
    assert sha256_file(ROOT / reviewed["audit_path"]) == reviewed["audit_sha256"]
    assert sha256_file(ROOT / "src/phase6_m2_1_formal_test.py") == reviewed["runner_module_sha256"]
    assert sha256_file(ROOT / "src/run_phase6_m2_1_formal_test.py") == reviewed["cli_sha256"]
    assert sha256_file(ROOT / "src/phase6_m2_1_formal_test_status.py") == reviewed["status_module_sha256"]
    assert sha256_file(ROOT / "configs/phase6_m2_1_formal_test_runner.yaml") == reviewed["runner_config_sha256"]
    assert orchestrator_sha256(ROOT) == approval["formal_test_orchestrator_sha256"]
    assert audit["reviewed_runner_fix"]["formal_test_orchestrator_sha256"] == approval["formal_test_orchestrator_sha256"]


def test_reauthorization_preserves_exact_science_and_freeze() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    actual = formal_test_fingerprints(
        ROOT,
        ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml",
        ROOT / "configs/phase6_m2_1_formal_test_runner.yaml",
    )
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == approval["approved_fingerprints"][field] == audit["fingerprints"][field]
    assert approval["approved_fingerprints"]["environment_sha256"] == audit["fingerprints"]["environment_sha256"] == "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    freeze = approval["selected_plan_freeze"]
    assert sha256_file(ROOT / freeze["path"]) == freeze["sha256"]
    assert sha256_file(ROOT / freeze["audit_path"]) == freeze["audit_sha256"]


def test_reauthorization_scope_and_zero_execution_are_exact() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert sha256_file(AUTH) == audit["authorization_artifact"]["sha256"]
    assert approval["status"] == "frozen_for_formal_test_execution"
    assert approval["formal_test_authorized"] is True
    assert approval["formal_extension_authorized"] is False
    assert approval["algorithm_performance_authorized"] is False
    assert approval["accept_prior_track_authorization"] is False
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())
    matrix = audit["authorized_matrix"]
    assert matrix["primary_run_count"] * matrix["strategy_count_per_run"] == matrix["plan_count"] == 60
    assert matrix["plan_count"] * matrix["scenario_count_per_plan"] == matrix["exact_recourse_evaluation_count"] == 120000
    assert matrix["complete_batch_required"] is True
    assert matrix["strictly_serial"] is True
    assert not (ROOT / "outputs/phase6_m2_1_formal_test_v1_0").exists()


def test_old_pr72_authorization_cannot_authorize_fixed_runner() -> None:
    old = yaml.safe_load(
        (ROOT / "configs/phase6_m2_1_formal_test_authorization_v1_0.yaml")
        .read_text(encoding="utf-8")
    )
    current = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    assert old["formal_test_orchestrator_sha256"] == "eb46518ce1c090a1da798a49fb27ae006ffdf42b89886f1292b3bee8bd33b07a"
    assert old["formal_test_orchestrator_sha256"] != orchestrator_sha256(ROOT)
    assert current["formal_test_orchestrator_sha256"] == orchestrator_sha256(ROOT)

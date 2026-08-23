from __future__ import annotations

import json
from pathlib import Path

import yaml

from src.phase6_m2_1_formal_test import formal_test_fingerprints, orchestrator_sha256
from src.reproducibility import sha256_file


ROOT = Path(__file__).resolve().parents[1]
AUTH = ROOT / "configs/phase6_m2_1_formal_test_authorization_v1_0.yaml"


def test_authorization_preserves_exact_historical_runner_and_freeze_binding() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    reviewed = approval["reviewed_runner"]
    assert reviewed["pr71_merge_commit"] == "2d60923cadaeb6c92401429cf3907c174170b3d8"
    assert reviewed["pr71_merge_tree"] == "d91129f28e1f14296e629e710e49c5f52ca215f0"
    assert sha256_file(ROOT / reviewed["audit_path"]) == reviewed["audit_sha256"]
    audit = json.loads((ROOT / reviewed["audit_path"]).read_text(encoding="utf-8"))
    artifacts = audit["artifact_sha256"]
    bindings = {
        "cli_sha256": ("src/run_phase6_m2_1_formal_test.py", "cli"),
        "status_module_sha256": ("src/phase6_m2_1_formal_test_status.py", "status_module"),
        "runner_config_sha256": ("configs/phase6_m2_1_formal_test_runner.yaml", "runner_config"),
    }
    for field, (path, artifact_field) in bindings.items():
        assert sha256_file(ROOT / path) == reviewed[field] == artifacts[artifact_field]
    assert reviewed["runner_module_sha256"] == artifacts["runner_module"]
    assert sha256_file(ROOT / "src/phase6_m2_1_formal_test.py") != reviewed["runner_module_sha256"]
    freeze = approval["selected_plan_freeze"]
    assert sha256_file(ROOT / freeze["path"]) == freeze["sha256"]
    assert sha256_file(ROOT / freeze["audit_path"]) == freeze["audit_sha256"]


def test_runner_fix_preserves_five_fingerprints_but_revokes_old_orchestrator() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    actual = formal_test_fingerprints(
        ROOT, ROOT / "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml",
        ROOT / "configs/phase6_m2_1_formal_test_runner.yaml",
    )
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == approval["approved_fingerprints"][field]
    assert approval["approved_fingerprints"]["environment_sha256"] == "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    assert orchestrator_sha256(ROOT) != approval["formal_test_orchestrator_sha256"]


def test_authorization_scope_is_exact_and_revision_has_zero_execution() -> None:
    approval = yaml.safe_load(AUTH.read_text(encoding="utf-8"))
    assert approval["status"] == "frozen_for_formal_test_execution"
    assert approval["selected_plan_freeze_authorized"] is True
    assert approval["formal_test_runner_implemented"] is True
    assert approval["formal_test_authorized"] is True
    assert approval["formal_extension_authorized"] is False
    assert approval["algorithm_performance_authorized"] is False
    assert approval["accept_prior_track_authorization"] is False
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())
    assert not (ROOT / "outputs/phase6_m2_1_formal_test_v1_0").exists()


def test_historical_pending_approval_remains_non_executable() -> None:
    historical = yaml.safe_load((ROOT / "configs/phase6_m2_1_formal_test_approval.yaml").read_text(encoding="utf-8"))
    assert historical["status"] == "pending_formal_test_runner_review"
    assert historical["formal_test_authorized"] is False

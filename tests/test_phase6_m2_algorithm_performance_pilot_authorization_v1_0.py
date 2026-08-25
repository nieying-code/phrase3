from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_algorithm_performance import algorithm_performance_fingerprints


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/phase6_m2_algorithm_performance_design_v1_0.yaml"
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_runner_v1_0.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_pilot_approval_v1_0.yaml"
RUNNER_AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_runner_v1_0_audit.json"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_authorization_v1_0_audit.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_authorization_is_bound_to_reviewed_pr79_runner_and_executes_nothing() -> None:
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr79_merge_commit": "72c430e9c12bb3aca9d65f9d69fe257aa71591a0",
        "pr79_merge_tree": "f2d9d311bc4de33ef7a3e0ffdf950090be1aa57b",
        "pr79_runner_audit_sha256": _sha(RUNNER_AUDIT),
    }
    expected_artifacts = {
        "approval_sha256": _sha(APPROVAL),
        "design_config_sha256": _sha(DESIGN),
        "runner_config_sha256": _sha(RUNNER),
        "orchestrator_module_sha256": _sha(ROOT / "src/phase6_m2_algorithm_performance.py"),
        "worker_module_sha256": _sha(ROOT / "src/phase6_m2_algorithm_performance_worker.py"),
        "cli_sha256": _sha(ROOT / "src/run_phase6_m2_algorithm_performance.py"),
        "status_module_sha256": _sha(ROOT / "src/phase6_m2_algorithm_performance_status.py"),
    }
    assert audit["artifacts"] == expected_artifacts
    actual = algorithm_performance_fingerprints(ROOT, DESIGN, RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
        "algorithm_performance_orchestrator_sha256",
    ):
        assert actual[field] == audit["fingerprints"][field]
    assert audit["fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["artifact_sha256"] == {
        "runner_config": expected_artifacts["runner_config_sha256"],
        "orchestrator_module": expected_artifacts["orchestrator_module_sha256"],
        "worker_module": expected_artifacts["worker_module_sha256"],
        "cli": expected_artifacts["cli_sha256"],
        "status_module": expected_artifacts["status_module_sha256"],
    }
    assert approval["status"] == "frozen_for_pilot_execution"
    assert approval["pilot_authorized"] is True
    assert approval["review_base_commit"] == audit["base"]["pr79_merge_commit"]
    assert approval["reviewed_runner_merge_commit"] == audit["base"]["pr79_merge_commit"]
    for field in (
        "formal_authorized", "M0_E3_additional_runs_authorized",
        "M2_mechanism_additional_runs_authorized",
        "M2_OOS_additional_runs_authorized", "M2_1_additional_runs_authorized",
    ):
        assert approval[field] is False
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert not (ROOT / "outputs/phase6_m2_algorithm_performance_v1_0").exists()

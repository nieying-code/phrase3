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
    immutable_artifacts = {
        "approval_sha256": _sha(APPROVAL),
        "design_config_sha256": _sha(DESIGN),
        "runner_config_sha256": _sha(RUNNER),
    }
    for field, value in immutable_artifacts.items():
        assert audit["artifacts"][field] == value
    historical_modules = {
        "orchestrator_module_sha256": "aad82a7ca3b6502bb81f39395f145c674d42d03ee9ef1b0760ff4bbec855ab86",
        "worker_module_sha256": "4e02405e89c2ff5d93a9a34d5fe61f828e584203ede6a9591beb01d9a96732f2",
        "cli_sha256": "563ac6958d56dcd4deff403e8d06b8a7cf5b65502680a3551f401a0be7cb93c2",
        "status_module_sha256": "d137fdab8ebe919ea56f12228593ffb7b6ec5881510a6e15cbc899ea0e3fe4d8",
    }
    assert {
        field: audit["artifacts"][field] for field in historical_modules
    } == historical_modules
    assert _sha(ROOT / "src/phase6_m2_algorithm_performance_worker.py") != historical_modules["worker_module_sha256"]
    actual = algorithm_performance_fingerprints(ROOT, DESIGN, RUNNER)
    for field in ("scientific_config_sha256", "runner_config_sha256"):
        assert actual[field] == audit["fingerprints"][field]
    for field in (
        "e3_component_sha256", "family_component_sha256",
        "algorithm_performance_orchestrator_sha256",
    ):
        assert actual[field] != audit["fingerprints"][field]
    assert audit["fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["artifact_sha256"] == {
        "runner_config": immutable_artifacts["runner_config_sha256"],
        "orchestrator_module": historical_modules["orchestrator_module_sha256"],
        "worker_module": historical_modules["worker_module_sha256"],
        "cli": historical_modules["cli_sha256"],
        "status_module": historical_modules["status_module_sha256"],
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
    # The later authorized attempt is preserved under v1.0 and audited by PR #81;
    # this historical authorization test must not require deletion of that evidence.

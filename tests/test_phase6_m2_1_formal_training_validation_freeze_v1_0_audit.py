import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_1_formal_training_validation import formal_fingerprints


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_formal_training_validation_freeze_v1_0_audit.json"
CONFIG = ROOT / "configs/phase6_m2_1_formal_training_validation.yaml"
RUNNER = ROOT / "configs/phase6_m2_1_formal_training_validation_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_1_formal_training_validation_approval.yaml"


def _sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_artifacts_and_fingerprints_are_exactly_locked():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    expected_paths = {
        "formal_config": CONFIG,
        "runner_config": RUNNER,
        "approval": APPROVAL,
        "runner_module": ROOT / "src/phase6_m2_1_formal_training_validation.py",
        "cli": ROOT / "src/run_phase6_m2_1_formal_training_validation.py",
        "status_module": ROOT / "src/phase6_m2_1_formal_training_validation_status.py",
    }
    assert {_id: _sha(path) for _id, path in expected_paths.items()} == audit["artifact_sha256"]
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert formal_fingerprints(ROOT, CONFIG, RUNNER) == audit["fingerprints"]


def test_pilot_binding_matrix_and_phase_stop_boundary_are_locked():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    parent = audit["reviewed_pilot_evidence"]
    assert _sha(ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_endpoint_selection_pilot_results_v1_0_audit.json") == parent["audit_sha256"]
    assert (parent["primary_runs"], parent["validation_exact_recourse_evaluations"], parent["test_probe_exact_recourse_evaluations"]) == (3, 18000, 12000)
    assert parent["pilot_compute_gate_passed"] is True
    matrix = audit["formal_matrix"]
    assert matrix["training_seeds"] == list(range(2026090101, 2026090111))
    assert matrix["validation_seeds"] == list(range(2026090201, 2026090211))
    assert matrix["reserved_test_seeds_not_accessed"] == list(range(2026090301, 2026090311))
    assert (matrix["primary_run_count"], matrix["validation_candidate_plan_count"], matrix["validation_exact_recourse_evaluation_count"]) == (10, 30, 60000)
    assert matrix["formal_test_scenario_generation_count"] == matrix["formal_test_recourse_evaluation_count"] == 0
    authorization = audit["phase_authorization"]
    assert authorization["formal_training_authorized"] is authorization["formal_validation_authorized"] is True
    assert authorization["selected_plan_freeze_authorized"] is False
    assert authorization["formal_test_authorized"] is authorization["formal_extension_authorized"] is False
    assert all(value == 0 for value in audit["execution_counts_in_this_pr"].values())

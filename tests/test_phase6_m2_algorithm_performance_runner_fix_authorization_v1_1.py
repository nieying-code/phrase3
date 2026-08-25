from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_algorithm_performance import build_pilot_cases, validate_static_freeze


ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/phase6_m2_algorithm_performance_design_v1_0.yaml"
RUNNER = ROOT / "configs/phase6_m2_algorithm_performance_runner_v1_1.yaml"
APPROVAL = ROOT / "configs/phase6_m2_algorithm_performance_pilot_approval_v1_1.yaml"
FAILURE_AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_v1_0_failure_audit.json"
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_runner_fix_authorization_v1_1_audit.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load() -> tuple[dict, dict]:
    return (
        yaml.safe_load(APPROVAL.read_text(encoding="utf-8")),
        json.loads(AUDIT.read_text(encoding="utf-8")),
    )


def test_two_commit_review_identity_and_pr81_failure_evidence_are_locked() -> None:
    approval, audit = _load()
    assert audit["base"] == {
        "pr81_merge_commit": "3ee18bae67694dd94d768df780d6e05a65943d8c",
        "pr81_merge_tree": "cc8821b64d23deecde559d36e51630908699bdeb",
        "pr81_failure_audit_path": "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_v1_0_failure_audit.json",
        "pr81_failure_audit_sha256": _sha(FAILURE_AUDIT),
        "reviewed_runner_fix_commit": "03978b0efce768672233079ea23364c6ca632418",
        "reviewed_runner_fix_tree": "14114651d54c3169b3e87c72907557c2041032b1",
    }
    assert approval["review_base_commit"] == audit["base"]["pr81_merge_commit"]
    assert approval["reviewed_runner_merge_commit"] == audit["base"]["reviewed_runner_fix_commit"]


def test_all_execution_artifacts_and_approved_fingerprints_are_exact() -> None:
    approval, audit = _load()
    artifact_paths = {
        "design_config_sha256": DESIGN,
        "runner_config_sha256": RUNNER,
        "approval_sha256": APPROVAL,
        "orchestrator_module_sha256": ROOT / "src/phase6_m2_algorithm_performance.py",
        "worker_module_sha256": ROOT / "src/phase6_m2_algorithm_performance_worker.py",
        "cli_sha256": ROOT / "src/run_phase6_m2_algorithm_performance.py",
        "status_module_sha256": ROOT / "src/phase6_m2_algorithm_performance_status.py",
    }
    assert {_field: _sha(path) for _field, path in artifact_paths.items()} == audit["artifacts"]
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert approval["artifact_sha256"] == {
        "runner_config": audit["artifacts"]["runner_config_sha256"],
        "orchestrator_module": audit["artifacts"]["orchestrator_module_sha256"],
        "worker_module": audit["artifacts"]["worker_module_sha256"],
        "cli": audit["artifacts"]["cli_sha256"],
        "status_module": audit["artifacts"]["status_module_sha256"],
    }


def test_authorization_is_exactly_full_pilot_and_nothing_else() -> None:
    approval, audit = _load()
    context = validate_static_freeze(ROOT, RUNNER, APPROVAL)
    cases = build_pilot_cases(context["design"])
    assert len(cases) == 6
    assert len({(case.seed, case.profile_id) for case in cases}) == 6
    assert audit["matrix"]["pilot_primary_sequence_count"] == 6
    assert audit["matrix"]["pilot_budget_pair_count"] == 12
    assert audit["matrix"]["pilot_algorithm_solve_count"] == 36
    assert audit["matrix"]["formal_algorithm_execution_count"] == 240
    assert approval["pilot_authorized"] is True
    assert approval["formal_authorized"] is False
    for field in (
        "M0_E3_additional_runs_authorized",
        "M2_mechanism_additional_runs_authorized",
        "M2_OOS_additional_runs_authorized",
        "M2_1_additional_runs_authorized",
    ):
        assert approval[field] is False
    assert all(value == 0 for value in audit["execution_counts"].values())


def test_failed_v1_0_namespace_is_excluded_and_v1_1_starts_empty() -> None:
    _, audit = _load()
    safety = audit["safety"]
    assert safety["old_namespace"] == "phase6_m2_algorithm_performance_v1_0"
    assert safety["old_failed_evidence_is_immutable_and_excluded"] is True
    assert safety["new_namespace"] == "phase6_m2_algorithm_performance_v1_1"
    new_root = ROOT / safety["new_output_root"]
    assert not new_root.exists() or not any(new_root.iterdir())
    assert safety["complete_primary_batch_required"] is True
    assert safety["failure_stops_batch"] is True


def test_fix_is_limited_to_real_wrapper_interface_and_does_not_change_matrix() -> None:
    _, audit = _load()
    fix = audit["fix"]
    assert fix == {
        "invalid_interface": "DisruptedProcurementData.total_budget",
        "corrected_interface": "DisruptedProcurementData.budget",
        "real_generated_m2_data_wrapper_tested": True,
        "real_disrupted_procurement_data_wrapper_tested": True,
        "test_stops_at_mock_solver_boundary": True,
        "scientific_matrix_changed": False,
    }

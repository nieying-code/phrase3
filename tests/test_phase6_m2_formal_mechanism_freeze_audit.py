import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_formal_extension import formal_extension_fingerprints, load_formal_extension_config
from src.phase6_m2_formal_mechanism import build_formal_mechanism_cases, formal_orchestrator_sha256


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_mechanism_freeze_v1_1_audit.json"
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
PILOT_RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_formal_mechanism_approval.yaml"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_formal_freeze_audit_locks_files_and_identity():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_mechanism_freeze_v1_1"
    assert audit["base_merge_commit"] == "1c945a835abb837c8e8bae3404fc30c49957bc8f"
    assert audit["base_tree"] == "f5360ef6f3dbfab472774c1543273710ec8b92f5"
    for identity in audit["controlled_files"].values():
        assert _sha(ROOT / identity["path"]) == identity["sha256"]
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert approval["formal_orchestrator_sha256"] == audit["formal_orchestrator_sha256"]
    assert formal_orchestrator_sha256(ROOT) == audit["formal_orchestrator_sha256"]


def test_five_pilot_fingerprints_and_parent_evidence_are_unchanged():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    actual = formal_extension_fingerprints(ROOT, CONFIG, PILOT_RUNNER)
    assert audit["approved_fingerprints"] == approval["approved_fingerprints"]
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == audit["approved_fingerprints"][field]
    assert len(actual["environment_sha256"]) == 64
    assert audit["approved_fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    evidence = approval["pilot_evidence"]
    assert _sha(ROOT / evidence["audit_path"]) == audit["pilot_evidence"]["audit_sha256"]
    assert evidence["audit_sha256"] == "542ef406383a6ac0da1fefc583b40f0617036d43542cea8ca6de6602f90b8d66"
    assert evidence["projection_sha256"] == audit["pilot_evidence"]["projection_sha256"]
    assert evidence["registry_sha256"] == audit["pilot_evidence"]["registry_sha256"]
    parent = json.loads((ROOT / evidence["audit_path"]).read_text(encoding="utf-8"))
    assert evidence["projection_sha256"] == parent["global_artifacts"]["pilot_projection_sha256"]
    assert evidence["registry_sha256"] == parent["global_artifacts"]["pilot_run_registry_sha256"]
    assert parent["fingerprints"] == approval["approved_fingerprints"]
    assert parent["aggregate"]["mechanism_run_count"] == 15
    assert parent["aggregate"]["oos_probe_run_count"] == 1
    reviewed_projection = parent["projection"]
    assert reviewed_projection["verified_mechanism_run_count"] == 15
    assert reviewed_projection["verified_OOS_probe_run_count"] == 1
    for field in (
        "invalid_primary_run_ids", "diagnostic_run_ids", "duplicate_case_ids",
        "failed_primary_run_ids", "finalization_failure_run_ids",
    ):
        assert reviewed_projection[field] == []
    assert reviewed_projection["pilot_compute_gate_passed"] is True


def test_formal_matrix_and_stop_boundary_are_exact():
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    cases = build_formal_mechanism_cases(load_formal_extension_config(CONFIG))
    assert len(cases) == audit["formal_matrix"]["total_run_count"] == 50
    assert sum(case.beta == 1.1 for case in cases) == audit["formal_matrix"]["primary_track_run_count"] == 30
    assert sum(case.beta == 1.3 for case in cases) == audit["formal_matrix"]["secondary_track_run_count"] == 20
    assert audit["scope"] == {
        "formal_mechanism_case_count": 50,
        "formal_OOS_authorized": False,
        "algorithm_performance_authorized": False,
        "M0_E3_authorized": False,
    }
    assert all(value == 0 for value in audit["execution_counts_in_this_PR"].values())

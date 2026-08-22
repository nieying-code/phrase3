from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_1_pilot import pilot_fingerprints


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / "configs/phase6_m2_1_pilot.yaml"
RUNNER = ROOT / "configs/phase6_m2_1_pilot_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_1_pilot_approval.yaml"
FIX_AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_gurobi_version_preflight_fix_audit.json"
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_reauthorization_v1_1_audit.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_reauthorization_binds_fix_and_opens_only_pilot() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    protocol = yaml.safe_load(PILOT.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr65_merge_commit": "82f82fbc372ab9c17a2798beef618ecea963c0ca",
        "pr65_merge_tree": "ddd11aaec49466e95c9fc70d45d030b3283361d8",
        "pr65_fix_audit_sha256": _sha256(FIX_AUDIT),
    }
    assert audit["approval_sha256"] == _sha256(APPROVAL)
    assert audit["runner_module_sha256"] == _sha256(ROOT / "src/phase6_m2_1_pilot.py")
    actual = pilot_fingerprints(ROOT, PILOT, RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == audit["approved_fingerprints"][field]
    assert approval["approved_fingerprints"] == audit["approved_fingerprints"]
    assert protocol["execution_boundaries"]["pilot_authorized"] is True
    assert approval["pilot_authorized"] is True
    assert approval["explicit_cli_authorization_required"] is True
    for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
        "formal_extension_authorized",
    ):
        assert protocol["execution_boundaries"][field] is False
        assert approval[field] is False
    assert approval["accept_M2_authorization"] is False
    assert all(value == 0 for value in audit["execution_counts"].values())

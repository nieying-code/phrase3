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
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_authorization_v1_0_audit.json"
RUNNER_AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_runner_v1_0_audit.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_authorization_is_exactly_bound_and_executes_nothing() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    protocol = yaml.safe_load(PILOT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr63_merge_commit": "662f8b65aa7b42ab997badee37f1ed25ccc014d4",
        "pr63_merge_tree": "459dffd58ceb46b6db35d9865372f6cc2a292eb3",
        "pr63_runner_audit_sha256": _sha256(RUNNER_AUDIT),
    }
    assert audit["artifacts"] == {
        "pilot_config_sha256": _sha256(PILOT),
        "approval_sha256": _sha256(APPROVAL),
        "runner_config_sha256": _sha256(RUNNER),
    }
    assert pilot_fingerprints(ROOT, PILOT, RUNNER) == audit["fingerprints"]
    assert approval["approved_fingerprints"] == audit["fingerprints"]
    assert protocol["execution_boundaries"]["pilot_authorized"] is True
    assert approval["status"] == "approved_for_pilot_execution"
    assert approval["pilot_authorized"] is True
    for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
        "formal_extension_authorized",
    ):
        assert protocol["execution_boundaries"][field] is False
        assert approval[field] is False
    assert approval["accept_M2_authorization"] is False
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())

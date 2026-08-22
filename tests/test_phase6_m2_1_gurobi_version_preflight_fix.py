from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
import yaml

from src import phase6_m2_1_pilot as pilot


ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT / pilot.PILOT_CONFIG_PATH
RUNNER = ROOT / pilot.RUNNER_CONFIG_PATH
APPROVAL = ROOT / pilot.APPROVAL_PATH
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_gurobi_version_preflight_fix_audit.json"
AUTH_AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_authorization_v1_0_audit.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_fix_is_bound_and_old_authorization_cannot_execute() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert audit["base"]["pr64_authorization_audit_sha256"] == _sha256(AUTH_AUDIT)
    assert audit["runner_module_sha256"] == _sha256(ROOT / "src/phase6_m2_1_pilot.py")
    actual = pilot.pilot_fingerprints(ROOT, PILOT, RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert actual[field] == audit["current_fingerprints"][field]
    assert len(actual["environment_sha256"]) == 64
    assert audit["current_fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert approval["approved_fingerprints"] != actual
    with pytest.raises(RuntimeError, match="approved fingerprint mismatch"):
        pilot.validate_preflight(
            root=ROOT, pilot_path=PILOT, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=True,
        )
    assert audit["old_authorization_rejected_by_new_fingerprints"] is True
    assert all(value == 0 for value in audit["execution_counts"].values())

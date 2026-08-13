from __future__ import annotations

import json
from pathlib import Path

import yaml

import src.phase6_m2c2_confirmation as runner


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-13_phase6_m2c2_confirmation_runner_audit.json"
CONFIG = ROOT / "configs/phase6_m2_two_item_confirmation.yaml"
RUNNER = ROOT / "configs/phase6_m2c2_confirmation_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2c2_confirmation_approval.yaml"


def test_runner_audit_locks_matrix_fingerprints_and_zero_execution() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    config = runner.load_confirmation_config(CONFIG)
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    cases = runner.build_confirmation_cases(config)
    assert audit["base_merge_sha"] == "28079b9d63ffeabf5bff909684b8c982f46f1b2b"
    assert audit["matrix"] == {
        "tier_id": "M2C2",
        "seeds": [2026081301, 2026081302, 2026081303, 2026081304, 2026081305],
        "betas": [1.1, 1.3],
        "profiles": ["C0", "C1", "T03"],
        "case_count": 30,
        "reference_budget": 2337.610924158743,
    }
    assert len(cases) == 30
    actual = runner.confirmation_fingerprints(ROOT, CONFIG, RUNNER)
    approved = approval["approved_fingerprints"]
    assert audit["fingerprints"] == approved
    for field in runner.FINGERPRINT_FIELDS[:-1]:
        assert approved[field] == actual[field]
    assert approved["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert set(audit["execution_counts"].values()) == {0}
    assert audit["safety"]["formal_extension_authorized"] is False

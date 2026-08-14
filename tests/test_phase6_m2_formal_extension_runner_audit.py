from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_runner_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "fec4e4dde521692767f9ba48ec6809528f87856c59d2be0a082bcfa360980565",
    "e3_component_sha256": "8c7230752ad73fc6360746061fb887d0ff3f0ad29b86f03bb007feb596c9a62b",
    "family_component_sha256": "54ed1bac9c169e576fc694782c48c6e2d7641870b412fbe48743fb81b4977d2e",
    "runner_config_sha256": "76f54b5394406715b1974db1be6db49805f7c9458f8f886efc1010c7421fd3f0",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_audit_locks_every_controlled_file_and_approval() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_extension_pilot_runner_v1_0"
    assert audit["status"] == "implemented_not_executed_pending_review"
    assert audit["base_main_merge_commit"] == "20af98b522d498c6ffa8a384f819f307f686ddfe"
    for identity in audit["controlled_files"].values():
        assert _sha(ROOT / identity["path"]) == identity["sha256"]
    approval = yaml.safe_load(
        (ROOT / "configs/phase6_m2_formal_extension_pilot_approval.yaml").read_text(encoding="utf-8")
    )
    assert audit["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["approved_fingerprints"] == EXPECTED_FINGERPRINTS
    assert approval["status"] == "frozen_for_pilot_execution"
    assert approval["formal_extension_authorized"] is False
    assert approval["accept_prior_track_authorization"] is False


def test_runner_audit_closes_zero_execution_and_stop_boundary() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["pilot_matrix"] == {
        "mechanism_primary_runs": 15,
        "OOS_probe_runs": 1,
        "mechanism_training_seeds": [2026081601, 2026081602, 2026081603],
        "OOS_probe_training_seed": 2026081601,
        "OOS_probe_test_seed": 2026081701,
        "OOS_probe_strategy_count": 5,
        "OOS_probe_scenarios_per_strategy": 2000,
    }
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert audit["safety_invariants"]["full_primary_pilot_required"] is True
    assert audit["safety_invariants"]["common_random_numbers_are_a_hard_gate"] is True
    assert audit["safety_invariants"]["OOS_reads_finalized_plan_artifacts_only"] is True
    assert audit["formal_extension_authorized"] is False

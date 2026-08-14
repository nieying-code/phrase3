from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_runner_audit.json"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "fec4e4dde521692767f9ba48ec6809528f87856c59d2be0a082bcfa360980565",
    "e3_component_sha256": "b80147591b26099f15794adf095549101d733a51780e076e0e8599ec591bed46",
    "family_component_sha256": "bf6dae9fc3d79a4906995d259b0aa5d50697eb00211072600369da839901be3c",
    "runner_config_sha256": "76f54b5394406715b1974db1be6db49805f7c9458f8f886efc1010c7421fd3f0",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}

def test_runner_audit_locks_every_controlled_file_and_approval() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_extension_pilot_runner_v1_0"
    assert audit["status"] == "implemented_not_executed_pending_review"
    assert audit["base_main_merge_commit"] == "20af98b522d498c6ffa8a384f819f307f686ddfe"
    assert audit["controlled_files"] == {
        "scientific_config": {
            "path": "configs/phase6_m2_formal_extension.yaml",
            "sha256": "c2c46333896f2c9fada020bddc90ca9eb56a30e28bff5e9f8b2bcdc3d32a7b70",
        },
        "runner_config": {
            "path": "configs/phase6_m2_formal_extension_runner.yaml",
            "sha256": "76f54b5394406715b1974db1be6db49805f7c9458f8f886efc1010c7421fd3f0",
        },
        "pilot_approval": {
            "path": "configs/phase6_m2_formal_extension_pilot_approval.yaml",
            "sha256": "ee30aaf3b2fe85bfbb7f21d1dd7aa27c22de83df9d41373a7ae1339cb2999304",
        },
        "runner_source": {
            "path": "src/phase6_m2_formal_extension.py",
            "sha256": "bbc9abaa7f51513812504547ad639a9acb324e77a0670772da5d761682d4b2e7",
        },
        "cli_source": {
            "path": "src/run_phase6_m2_formal_extension.py",
            "sha256": "63d4bd769d7508e713d8b5024cf97b2240e53812b166371b33beddb5e9983025",
        },
        "status_source": {
            "path": "src/phase6_m2_formal_extension_status.py",
            "sha256": "dd3faba986c34f71f4afc9c8572be40f812bcf9f51e8adf0cff29e2f6fadfb47",
        },
    }
    assert audit["approved_fingerprints"] == EXPECTED_FINGERPRINTS


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

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_endpoint_tolerance_fix_audit.json"


def test_endpoint_tolerance_fix_audit_closes_diagnostic_and_stop_boundary() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_extension_endpoint_tolerance_fix_v1_0"
    diagnostic = audit["diagnostic_batch"]
    assert diagnostic["mechanism_run_count"] == 15
    assert diagnostic["OOS_probe_run_count"] == 1
    assert diagnostic["raw_endpoint_check_count"] == 30
    assert diagnostic["positive_raw_tolerance_excess_count"] == 18
    assert diagnostic["maximum_raw_tolerance_excess"] == 1.5735617236306565e-11
    assert diagnostic["maximum_raw_tolerance_excess"] < audit["correction"]["numerical_comparison_slack"]
    assert diagnostic["corrected_read_only_validator_mechanism_count"] == 15
    assert diagnostic["old_projection_rewritten"] is False
    assert audit["correction"]["objective_tolerance_finite_and_nonnegative_required"] is True
    assert audit["correction"]["endpoint_differences_finite_and_nonnegative_required"] is True
    assert all(value == 0 for value in audit["execution_counts_in_this_fix"].values())
    assert audit["approval_updated"] is False
    assert audit["fresh_namespace_required_before_rerun"] is True
    assert audit["formal_extension_authorized"] is False
    source = audit["corrected_runner_source"]
    assert source == {
        "path": "src/phase6_m2_formal_extension.py",
        "sha256": "1b56aa49932376da86617749af196f108f66b7807f252b8f0602cb6619c1daee",
    }


def test_only_protected_component_fingerprints_change() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    before = audit["fingerprints"]["before"]
    corrected = audit["fingerprints"]["corrected"]
    assert before["scientific_config_sha256"] == corrected["scientific_config_sha256"]
    assert before["runner_config_sha256"] == corrected["runner_config_sha256"]
    assert before["environment_sha256"] == corrected["environment_sha256"]
    assert before["e3_component_sha256"] != corrected["e3_component_sha256"]
    assert before["family_component_sha256"] != corrected["family_component_sha256"]

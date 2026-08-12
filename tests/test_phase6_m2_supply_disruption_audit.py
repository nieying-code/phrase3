import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-12_phase6_m2_supply_disruption_audit.json"


def test_m2_design_audit_freezes_scope_and_zero_execution() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "implementation_validated_pending_manual_merge"
    assert audit["base_merge_sha"] == "1a9fa3063a18c482812b2328cb38aee5503f78d8"
    assert audit["validated_implementation_head"] == "aad5d3c7ad0fa344b17ffe1f4a75542b6acf4cf3"
    assert audit["intermediate_traceability"] == {
        "initial_implementation_head": "aefcec14ead24d89931b27eae0ad4fe2ac02c7cb",
        "initial_documentation_head": "566b97d5ca40ae46b16ed969191bd06d9d994390",
        "initial_ci_run_id": 31561123103,
        "classification": "intermediate_not_final_review_state",
    }
    assert audit["scientific_change"] == "scenario_dependent_paid_regular_contract_fulfillment_only"
    assert audit["accounting"] == {
        "budget_equality_unchanged": True,
        "regular_contract_paid_in_full": True,
        "refund_allowed": False,
        "undelivered_enters_inventory": False,
        "undelivered_enters_disposal_or_waste": False,
        "undelivered_additional_cost": False,
    }
    grid = audit["development_preregistration"]
    assert len(grid["seeds"]) * len(grid["beta"]) * len(grid["profiles"]) == 27
    assert grid["configuration_count"] == 27
    assert grid["seeds"] == [2026081201, 2026081202, 2026081203]
    assert grid["disjoint_from_M1_development_seeds"] is True
    assert grid["started_count"] == 0
    assert audit["execution_boundaries"] == {
        "pilot_count": 0,
        "formal_count": 0,
        "M0_E3_count": 0,
        "M0_or_M1_outputs_modified": False,
    }
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "c354a91917c31ed51429d6b2e84a8b2c09dcefcc1ad145a58ef0f27e0e87742d",
        "e3_component_sha256": "f4db040c9d62965e1c90f38d091a0b519b226e565c93c6c2972ce6263dec7f38",
        "family_component_sha256": "d6b623cf16108681f263efc4f12f9961fa986833d24e2ca91d78959b09001f9d",
        "runner_config_sha256": "d9de25037d85b21e4cc086b73db29a1eb9d6c95066154001c0463de12d66eb10",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["tests"] == {
        "specialized": "20 passed",
        "full_regression": "259 passed",
    }
    assert audit["github_actions"] == {
        "validated_head": "aad5d3c7ad0fa344b17ffe1f4a75542b6acf4cf3",
        "run_id": 31565293591,
        "status": "success",
        "linux": "passed",
        "windows": "passed",
    }

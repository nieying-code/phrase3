import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-12_phase6_m2_supply_disruption_audit.json"


def test_m2_design_audit_freezes_scope_and_zero_execution() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base_merge_sha"] == "1a9fa3063a18c482812b2328cb38aee5503f78d8"
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
    assert grid["started_count"] == 0
    assert audit["execution_boundaries"] == {
        "pilot_count": 0,
        "formal_count": 0,
        "M0_E3_count": 0,
        "M0_or_M1_outputs_modified": False,
    }
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "a2ac5dac56ee1e473a1397492e363eb76d330db9b9a69773b181304505784124",
        "e3_component_sha256": "bb63ccda160312059179ea15446cee4f4f4db60975c47b13156d77976ffe8d67",
        "family_component_sha256": "cfc69451989ad8d4771f7399f63b7a6e95fcf640516dd52564bc0fcb560300d3",
        "runner_config_sha256": "d9de25037d85b21e4cc086b73db29a1eb9d6c95066154001c0463de12d66eb10",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }

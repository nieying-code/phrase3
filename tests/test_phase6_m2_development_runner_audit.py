import json
from pathlib import Path

from src.phase6_m2_development import load_development_approval


ROOT = Path(__file__).resolve().parents[1]


def test_m2_development_runner_audit_locks_scope_and_zero_execution() -> None:
    audit = json.loads((ROOT / "docs/handoffs/2026-08-12_phase6_m2_development_runner_audit.json").read_text(encoding="utf-8"))
    approval = load_development_approval(ROOT / "configs/phase6_m2_development_approval.yaml")
    assert audit["base_merge_sha"] == "29938da2982ba74608dc98f4fefac35850c6de65"
    assert audit["status"] == "superseded_after_first_run_wrapper_interface_failure"
    assert audit["superseded_by_protocol"] == "phase6_m2_supply_disruption_v1_1"
    assert audit["draft_pr"] == "https://github.com/nieying-code/phrase3/pull/43"
    assert audit["initial_implementation_commit"] == "673896cc4d2b301b4fa247fa56fb31d7daba1f06"
    assert audit["validated_implementation_commit"] == "03dcb659121f5cdc75ad95f2d36adf9bcede36b4"
    assert audit["validated_scientific_gate_fix_commit"] == "bdc1b47dfb93af6c8e9e3018b534b32a385321cc"
    assert audit["matrix"] == {
        "tier": "V1", "seeds": [2026081201, 2026081202, 2026081203],
        "beta": [0.9, 1.1, 1.3], "profiles": ["C0", "C1", "C2"],
        "case_count": 27, "ordering": ["seed", "beta", "profile"],
    }
    historical = audit["approved_fingerprints"]
    assert historical["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert historical != approval["approved_fingerprints"]
    assert approval["formal_extension_authorized"] is False
    assert approval["accept_m0_or_m1_authorization"] is False
    assert audit["activation"] == {
        "all_three_seeds_optimal_required": True,
        "minimum_substantive_activation_seed_count": 2,
        "substantive_threshold": 0.01,
        "eligible_profiles": ["C1", "C2"],
        "C0_all_three_seeds_optimal_required": True,
        "C0_substantive_activation_forbidden": True,
        "projection_recomputes_activation_from_raw_values": True,
        "common_random_number_component_hashes_required": True,
        "endpoint_and_fixed_policy_evidence_required": True,
        "formal_extension_authorized": False,
    }
    assert set(audit["execution_counts"].values()) == {0}
    assert audit["tests"] == {"focused": "45 passed", "full_regression": "285 passed"}
    assert audit["github_actions"] == {
        "run_id": 31575140393,
        "url": "https://github.com/nieying-code/phrase3/actions/runs/31575140393",
        "status": "success",
        "linux": "279 passed + 6 passed",
        "windows": "16 passed",
    }

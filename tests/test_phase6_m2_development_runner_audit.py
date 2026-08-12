import json
from pathlib import Path

from src.phase6_m2 import m2_fingerprints
from src.phase6_m2_development import load_development_approval


ROOT = Path(__file__).resolve().parents[1]


def test_m2_development_runner_audit_locks_scope_and_zero_execution() -> None:
    audit = json.loads((ROOT / "docs/handoffs/2026-08-12_phase6_m2_development_runner_audit.json").read_text(encoding="utf-8"))
    approval = load_development_approval(ROOT / "configs/phase6_m2_development_approval.yaml")
    actual = m2_fingerprints(
        project_root=ROOT,
        config_path=ROOT / "configs/phase6_m2_supply_disruption.yaml",
        runner_config_path=ROOT / "configs/phase6_m2_runner.yaml",
    )
    assert audit["base_merge_sha"] == "29938da2982ba74608dc98f4fefac35850c6de65"
    assert audit["matrix"] == {
        "tier": "V1", "seeds": [2026081201, 2026081202, 2026081203],
        "beta": [0.9, 1.1, 1.3], "profiles": ["C0", "C1", "C2"],
        "case_count": 27, "ordering": ["seed", "beta", "profile"],
    }
    assert approval["approved_fingerprints"] == audit["approved_fingerprints"] == actual
    assert approval["formal_extension_authorized"] is False
    assert approval["accept_m0_or_m1_authorization"] is False
    assert audit["activation"] == {
        "all_three_seeds_optimal_required": True,
        "minimum_substantive_activation_seed_count": 2,
        "substantive_threshold": 0.01,
        "formal_extension_authorized": False,
    }
    assert set(audit["execution_counts"].values()) == {0}

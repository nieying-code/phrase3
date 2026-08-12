import json
import platform
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
    assert audit["status"] == "implementation_complete_pending_ci"
    assert audit["draft_pr"] == "https://github.com/nieying-code/phrase3/pull/43"
    assert audit["validated_implementation_commit"] == "673896cc4d2b301b4fa247fa56fb31d7daba1f06"
    assert audit["matrix"] == {
        "tier": "V1", "seeds": [2026081201, 2026081202, 2026081203],
        "beta": [0.9, 1.1, 1.3], "profiles": ["C0", "C1", "C2"],
        "case_count": 27, "ordering": ["seed", "beta", "profile"],
    }
    approved = approval["approved_fingerprints"]
    assert approved == audit["approved_fingerprints"]
    assert approved["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    platform_independent_keys = {
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
    }
    assert {key: approved[key] for key in platform_independent_keys} == {
        key: actual[key] for key in platform_independent_keys
    }
    # The approved execution environment is the Windows/PyCharm Gurobi
    # environment.  Linux CI validates the platform-independent fingerprints
    # but must not replace or reinterpret that approved environment identity.
    if platform.system() == "Windows":
        assert actual["environment_sha256"] == approved["environment_sha256"]
    assert approval["formal_extension_authorized"] is False
    assert approval["accept_m0_or_m1_authorization"] is False
    assert audit["activation"] == {
        "all_three_seeds_optimal_required": True,
        "minimum_substantive_activation_seed_count": 2,
        "substantive_threshold": 0.01,
        "formal_extension_authorized": False,
    }
    assert set(audit["execution_counts"].values()) == {0}
    assert audit["tests"] == {"focused": "42 passed", "full_regression": "282 passed"}

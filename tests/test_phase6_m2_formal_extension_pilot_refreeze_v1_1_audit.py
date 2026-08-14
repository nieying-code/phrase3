from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from src.phase6_m2_formal_extension import (
    build_pilot_cases,
    formal_extension_fingerprints,
    load_formal_extension_config,
)


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_formal_extension_pilot_approval.yaml"
AUDIT = ROOT / "docs/handoffs/2026-08-14_phase6_m2_formal_extension_pilot_refreeze_v1_1_audit.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_refreeze_locks_controlled_files_and_fingerprints() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_id"] == "phase6_m2_formal_extension_pilot_refreeze_v1_1"
    assert audit["base_merge_commit"] == "5c955f738aff8f379c0ff8bb59ac97c91a43399e"
    assert audit["base_tree"] == "e9f53836c947b361a02cf26f2418fe3a739b4b65"
    for identity in audit["controlled_files"].values():
        assert _sha(ROOT / identity["path"]) == identity["sha256"]
    actual = formal_extension_fingerprints(ROOT, CONFIG, RUNNER)
    for field in (
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
    ):
        assert actual[field] == audit["approved_fingerprints"][field]
    assert len(actual["environment_sha256"]) == 64
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert approval["approved_fingerprints"] == audit["approved_fingerprints"]
    assert audit["approved_fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert audit["CI_environment_does_not_authorize_experiment_execution"] is True


def test_refreeze_namespace_is_new_empty_and_old_evidence_is_rejected() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    config = load_formal_extension_config(CONFIG)
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert config["protocol_id"] == "phase6_m2_formal_extension_design_v1_1"
    assert config["runner_namespace"] == "phase6_m2_formal_extension_v1_1"
    assert config["output_root"] == "outputs/phase6_m2_formal_extension_v1_1"
    assert approval["approval_id"] == "phase6_m2_formal_extension_pilot_v1_1"
    assert approval["runner_namespace"] == config["runner_namespace"]
    assert approval["accept_prior_track_authorization"] is False
    assert audit["namespace_isolation"]["old_results_accepted"] is False
    assert audit["namespace_isolation"]["registry_or_projection_migration_allowed"] is False
    assert not (ROOT / config["output_root"]).exists()


def test_refreeze_preserves_complete_pilot_and_stop_boundary() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    config = load_formal_extension_config(CONFIG)
    cases = build_pilot_cases(config)
    assert len([case for case in cases if case.run_kind == "mechanism"]) == 15
    assert len([case for case in cases if case.run_kind == "OOS_probe"]) == 1
    assert tuple(case.seed for case in cases if case.run_kind == "mechanism")[::5] == (
        2026081601, 2026081602, 2026081603,
    )
    evidence = config["runner_fix_evidence"]
    assert _sha(ROOT / evidence["audit"]) == evidence["audit_sha256"]
    assert evidence["finite_nonnegative_endpoint_evidence_required"] is True
    assert evidence["endpoint_comparison_slack"] == 1e-8
    assert evidence["old_namespace_results_accepted"] is False
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert audit["formal_extension_authorized"] is False

from __future__ import annotations

import json
from pathlib import Path
import re

from src.phase6_m1 import load_m1_config, m1_fingerprints


ROOT = Path(__file__).resolve().parents[1]
AUDIT = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-11_phase6_m1_procurement_cap_audit.json"
)
CONFIG = ROOT / "configs" / "phase6_m1_procurement_cap.yaml"
RUNNER = ROOT / "configs" / "phase6_m1_runner.yaml"

EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": (
        "6439d8a1945e44985cb1c8b20a20b7641617ed9a160db554680f3dc4680aa8c8"
    ),
    "e3_component_sha256": (
        "13f034140db75dc62059b99fe6cc2e238de521bb2483e299ff6cfd83fbec1160"
    ),
    "family_component_sha256": (
        "f3b24114668ae612133b54f0cfd5850c1ad835b2e0d4672b3b0a68057f935825"
    ),
    "runner_config_sha256": (
        "204362904604a5e34922a6022696859657ca3ffd9b5fa3e04dec59900337169f"
    ),
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}


def test_m1_design_audit_is_complete_and_reproducible() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    config = load_m1_config(CONFIG)

    assert audit["base"] == {
        "merged_pr": 38,
        "merge_commit_sha": "0c7c6cffe82a858b534e8bf812a23291ef40b709",
        "merge_tree_sha": "595ed0025be82beb7b7283faca6f53282fa8ab22",
    }
    assert audit["branch"] == "agent/phase6-m1-procurement-cap"
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    actual_fingerprints = m1_fingerprints(
        project_root=ROOT,
        config_path=CONFIG,
        runner_config_path=RUNNER,
    )
    assert {
        key: value
        for key, value in actual_fingerprints.items()
        if key != "environment_sha256"
    } == {
        key: value
        for key, value in EXPECTED_FINGERPRINTS.items()
        if key != "environment_sha256"
    }
    assert re.fullmatch(
        r"[0-9a-f]{64}", actual_fingerprints["environment_sha256"]
    )
    assert audit["environment_fingerprint_scope"] == {
        "recorded_value": "local_controlled_gurobi_execution_host",
        "cross_platform_CI_expected_to_match": False,
        "future_M1_runs_must_match_recorded_local_environment": True,
    }

    protocol = audit["protocol"]
    assert protocol["status"] == config["status"] == "candidate_design_pending_review"
    assert protocol["runner_namespace"] == config["runner_namespace"]
    assert protocol["output_root"] == config["output_root"]
    assert protocol["inherits_M0_authorization"] is False
    assert protocol["accepts_M0_registry_or_projection"] is False

    prereg = audit["development_preregistration"]
    expected_cases = {
        (seed, beta, kappa)
        for seed in (2026081101, 2026081102, 2026081103)
        for beta in (0.9, 1.1, 1.3)
        for kappa in (None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8)
    }
    actual_cases = {
        (seed, beta, kappa)
        for seed in prereg["seeds"]
        for beta in prereg["beta"]
        for kappa in prereg["kappa"]
    }
    assert actual_cases == expected_cases
    assert len(actual_cases) == prereg["configuration_count"] == 63
    assert prereg["numerical_activation_ratio_strictly_greater_than"] == 1.0e-4
    assert prereg["substantive_activation_ratio_greater_than_or_equal_to"] == 0.01
    assert prereg["minimum_substantive_activation_seed_count"] == 2
    assert prereg["all_three_seeds_must_succeed"] is True
    assert prereg["manual_or_outcome_based_selection_forbidden"] is True

    boundaries = audit["execution_boundaries"]
    assert boundaries["development_grid_run_count"] == 0
    assert boundaries["pilot_run_count"] == 0
    assert boundaries["formal_run_count"] == 0
    assert boundaries["M0_E3_run_count"] == 0
    assert boundaries["scenario_generation_performed_by_design_validation"] is False
    assert boundaries["M0_results_modified_or_deleted"] is False
    assert boundaries["M1_results_written_to_M0_output_root"] is False

    assert audit["verification"]["github_actions"] == {
        "validated_head_sha": "abcc6c7d8c0f855b561db40c0bc171b7cd2451e9",
        "run_id": 31459808225,
        "url": "https://github.com/nieying-code/phrase3/actions/runs/31459808225",
        "linux_unit_and_regression": "186 passed",
        "phase5_end_to_end": "6 passed",
        "windows_reproducibility": "passed",
        "status": "success",
    }

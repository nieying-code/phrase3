"""Validate the compact, reviewable Phase 6 v2.1 V1 pilot audit."""

from __future__ import annotations

import json
import re
from pathlib import Path


AUDIT_PATH = Path(
    "docs/handoffs/2026-08-01_phase6_v2_1_v1_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SEEDS = {2026072001, 2026072002, 2026072003}
EXPECTED_DISPOSAL_FIELDS = {
    "early_disposal": True,
    "expired_waste": True,
    "total_disposal": True,
}
EXPECTED_DIRTY_PATHS = {
    "outputs/gurobi_validation/",
    "outputs/phase6_v21_rr_clean/",
    "outputs/relative_complete_recourse_validation/",
    "outputs/tmp/",
}
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": (
        "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3"
    ),
    "e3_component_sha256": (
        "7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f"
    ),
    "family_component_sha256": (
        "5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f"
    ),
    "environment_sha256": (
        "0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2"
    ),
}


def test_phase6_v1_pilot_audit_is_complete_and_internally_consistent() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    counts = audit["counts"]
    projection = audit["projection"]
    runs = audit["runs"]

    assert audit["output_root"] == "outputs/phase6_v21_rr_clean"
    assert audit["source"]["execution_git_sha"] == (
        "977675e27f2de0f48ec51a60e349dc2a77165ee0"
    )
    assert audit["source"]["execution_git_tree_sha"] == (
        "e15526efe9ecbb350c41eb25cfb797153c24749e"
    )
    assert audit["source"]["execution_tree_matches_remote_merged_base"] is True
    assert audit["source"]["working_tree_dirty_recorded_by_manifest"] is True
    worktree = audit["source"]["worktree_status_evidence"]
    assert worktree["tracked_modified_count"] == 0
    assert set(worktree["pre_output_initialization_untracked_paths"]) == (
        EXPECTED_DIRTY_PATHS - {"outputs/phase6_v21_rr_clean/"}
    )
    assert set(worktree["manifest_time_untracked_paths"]) == EXPECTED_DIRTY_PATHS
    dirty_paths = worktree["dirty_paths"]
    assert {entry["path"] for entry in dirty_paths} == EXPECTED_DIRTY_PATHS
    assert all(entry["git_status"] == "untracked" for entry in dirty_paths)
    assert all(entry["is_e3_component"] is False for entry in dirty_paths)
    assert all(
        entry["is_matrix_or_runner_config"] is False for entry in dirty_paths
    )
    assert all(entry["is_dependency_lock"] is False for entry in dirty_paths)
    assert all(entry["used_as_runtime_input"] is False for entry in dirty_paths)
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "environment_sha256": EXPECTED_FINGERPRINTS["environment_sha256"],
    }
    assert counts == {
        "primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 18,
        "optimal_algorithm_execution_count": 18,
        "failed_primary_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "family_run_count_in_clean_root": 0,
    }
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == EXPECTED_SEEDS
    assert all(run["tier_id"] == "V1" for run in runs)
    assert all(run["execution_mode"] == "pilot" for run in runs)
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["parent_run_id"] is None for run in runs)

    pairs = [pair for run in runs for pair in run["budget_pairs"]]
    assert len(pairs) == 9
    assert all(pair["status"] == "optimal" for pair in pairs)
    assert all(pair["cold_status"] == "optimal" for pair in pairs)
    assert all(pair["warm_status"] == "optimal" for pair in pairs)
    assert all(pair["objective_difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert {pair["budget_factor"] for pair in pairs} == {0.9, 1.1, 1.3}

    assert all(
        run["disposal_fields_present"] == EXPECTED_DISPOSAL_FIELDS
        for run in runs
    )
    for key, expected in EXPECTED_FINGERPRINTS.items():
        assert audit["fingerprints"][key] == expected
    for run in runs:
        assert run["fingerprints"]["scientific_config_sha256"] == (
            EXPECTED_FINGERPRINTS["scientific_config_sha256"]
        )
        assert run["fingerprints"]["e3_component_sha256"] == (
            EXPECTED_FINGERPRINTS["e3_component_sha256"]
        )
        assert run["fingerprints"]["environment_sha256"] == (
            EXPECTED_FINGERPRINTS["environment_sha256"]
        )
        assert all(SHA256.fullmatch(value) for value in run["artifacts"].values())

    assert all(
        SHA256.fullmatch(value)
        for value in audit["global_artifacts"].values()
    )
    assert projection["completed_run_count"] == 3
    assert projection["required_run_count"] == 12
    assert projection["primary_completion_rate"] == 0.25
    assert projection["failed_primary_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert projection["formal_execution_authorized"] is False

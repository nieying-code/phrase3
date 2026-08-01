"""Validate the post-PR22 V1 E3 pilot audit snapshot."""

from __future__ import annotations

import json
import re
from pathlib import Path


AUDIT_PATH = Path(
    "docs/handoffs/2026-08-02_phase6_repro_v3_v1_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
EXPECTED_SEEDS = {2026072001, 2026072002, 2026072003}
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
    "runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
    "e3_component_sha256": "fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def test_repro_v3_v1_pilot_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    counts = audit["counts"]
    runs = audit["runs"]
    pairs = [pair for run in runs for pair in run["budget_pairs"]]

    assert audit["output_root"] == "outputs/phase6_v21_repro_v3"
    assert audit["source"] == {
        "execution_git_sha": "92f92b8fa8f85436797a7f9f4b20295ab09a3b35",
        "execution_git_tree_sha": "384b6ddd523d45c468068f466c41c0c6eec31d1e",
        "all_manifests_record_clean_worktree": True,
    }
    assert {key: audit["fingerprints"][key] for key in EXPECTED_FINGERPRINTS} == EXPECTED_FINGERPRINTS
    assert counts == {
        "primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 18,
        "optimal_algorithm_execution_count": 18,
        "infeasible_recourse_count": 0,
        "solver_failure_count": 0,
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
    assert all(run["working_tree_dirty"] is False for run in runs)
    assert len(pairs) == 9
    assert {pair["budget_factor"] for pair in pairs} == {0.9, 1.1, 1.3}
    assert all(pair["status"] == "optimal" for pair in pairs)
    assert all(pair["cold_status"] == "optimal" for pair in pairs)
    assert all(pair["warm_status"] == "optimal" for pair in pairs)
    assert all(pair["objective_difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(
        run["disposal_fields_present"]
        == {"early_disposal": True, "expired_waste": True, "total_disposal": True}
        for run in runs
    )
    assert all(
        run["fingerprints"] == EXPECTED_FINGERPRINTS for run in runs
    )
    assert all(
        SHA256.fullmatch(value)
        for run in runs
        for value in run["artifacts"].values()
    )
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())
    assert audit["performance"]["max_abs_objective_difference"] == 0.0
    projection = audit["projection"]
    assert projection["completed_run_count"] == 3
    assert projection["required_run_count"] == 12
    assert projection["primary_completion_rate"] == 0.25
    assert projection["failed_primary_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False

"""Validate the compact Phase 6 v2.1 V2 E3 pilot audit."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-01_phase6_v2_1_v2_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}
UNTRACKED_OUTPUTS = {
    "outputs/gurobi_validation/",
    "outputs/phase6_v21_rr_clean/",
    "outputs/relative_complete_recourse_validation/",
    "outputs/tmp/",
}
HISTORICAL_OUTPUTS = UNTRACKED_OUTPUTS - {"outputs/phase6_v21_rr_clean/"}


def test_v2_e3_pilot_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    counts = audit["counts"]
    runs = audit["runs"]
    pairs = audit["budget_pairs"]

    assert source["execution_tree_matches_remote_main"] is True
    assert source["execution_git_tree_sha"] == source["remote_main_tree_sha"]
    assert source["tracked_modified_count_at_start"] == 0
    assert source["working_tree_dirty_recorded_by_manifest"] is True
    assert set(source["untracked_output_directories"]) == UNTRACKED_OUTPUTS
    assert set(
        source["historical_output_directories_not_used_as_runtime_input"]
    ) == HISTORICAL_OUTPUTS
    controlled_root = source["controlled_read_write_root"]
    assert controlled_root["path"] == "outputs/phase6_v21_rr_clean/"
    assert controlled_root["read_inputs"] == [
        "approved V1 E3 registry and projection artifacts",
        "approved family registry, projection, and prerequisite artifacts",
    ]
    assert controlled_root["write_outputs"] == "current V2 E3 pilot artifacts"
    assert all(
        value is False
        for value in source["uncommitted_execution_inputs"].values()
    )
    traceability = audit["review_traceability"]
    assert traceability == {
        "final_validated_v2_results_head": (
            "33a5267b8d1300246f7dad7d77f9c26ce9ef45e5"
        ),
        "final_validated_v2_results_ci_run": 30696021947,
        "final_validated_v2_results_ci_status": "success",
        "intermediate_results_head": (
            "eb7a84a37549a015d69ea0281131edb0d9e2c0ba"
        ),
        "intermediate_ci_run": 30695967027,
        "intermediate_state_is_final": False,
    }
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert counts == {
        "primary_run_count": 3,
        "optimal_primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 54,
        "optimal_algorithm_execution_count": 54,
        "technical_repeat_group_count": 18,
        "cold_execution_count": 27,
        "warm_execution_count": 27,
        "failed_primary_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "diagnostic_attempt_count": 0,
    }
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    assert all(run["tier_id"] == "V2" for run in runs)
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["budget_pair_count"] == 3 for run in runs)
    assert all(run["algorithm_execution_count"] == 18 for run in runs)
    assert all(run["parent_run_id"] is None for run in runs)
    for run in runs:
        for name in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
            "budget_comparison_sha256",
        ):
            assert SHA256.fullmatch(run[name])

    assert len(pairs) == 9
    assert {pair["seed"] for pair in pairs} == SEEDS
    assert {pair["budget_factor"] for pair in pairs} == {0.9, 1.1, 1.3}
    assert all(pair["difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(pair["cold_iterations"] > 0 for pair in pairs)
    assert all(pair["warm_iterations"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["cold_median_seconds"]) for pair in pairs)
    assert all(math.isfinite(pair["warm_median_seconds"]) for pair in pairs)

    numerical = audit["numerical_consistency"]
    assert numerical["max_within_technical_repeat_objective_difference"] == 0.0
    assert numerical["max_cold_warm_objective_difference"] == 0.0
    assert numerical["disposal_fields_present"] == {
        "early_disposal": True,
        "expired_waste": True,
        "total_disposal": True,
    }
    assert all(SHA256.fullmatch(value) for value in audit["fingerprints"].values())
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())

    projection = audit["projection"]
    assert projection["completed_run_count"] == 6
    assert projection["required_run_count"] == 12
    assert projection["status"] == "insufficient_pilot_coverage"
    assert projection["failed_primary_runs"] == 0
    assert projection["duplicate_primary_runs"] == 0
    assert projection["diagnostic_attempts"] == 0
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert audit["family_prerequisites"] == {
        "family_run_count": 12,
        "completed_work_unit_count": 30,
        "all_optimal": True,
    }
    assert all(value is False for value in audit["stop_boundary"].values())

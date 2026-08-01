"""Validate the compact Phase 6 v2.1 E1 formal audit snapshot."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


AUDIT = Path("docs/handoffs/2026-08-01_phase6_v2_1_e1_formal_audit.json")
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_e1_formal_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["source"]["execution_git_sha"] == (
        "f169f2d783cf4714e8fffcadb92de1e2930c46bb"
    )
    assert audit["source"]["tracked_modified_count_at_start"] == 0
    assert audit["source"]["uncommitted_model_or_configuration_input"] is False
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo": "6.10.1",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert all(SHA256.fullmatch(value) for value in audit["fingerprints"].values())

    counts = audit["counts"]
    assert counts == {
        "primary_run_count": 14,
        "optimal_primary_run_count": 14,
        "planned_work_unit_count": 45,
        "completed_work_unit_count": 45,
        "extensive_model_execution_count": 45,
        "standard_ccg_execution_count": 45,
        "total_model_algorithm_execution_count": 90,
        "exact_evaluation_block_count": 90,
        "exact_optimal_scenario_count": 7140,
        "infeasible_scenario_count": 0,
        "solver_failure_count": 0,
        "failed_primary_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "diagnostic_attempt_count": 0,
    }
    assert audit["tier_summary"]["D0"]["work_unit_count"] == 6
    assert audit["tier_summary"]["V1"]["work_unit_count"] == 9
    assert audit["tier_summary"]["V2"]["work_unit_count"] == 30

    runs = audit["runs"]
    assert len(runs) == 14
    assert Counter(run["tier_id"] for run in runs) == Counter(
        {"D0": 1, "V1": 3, "V2": 10}
    )
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["planned_work_units"] == run["completed_work_units"] for run in runs)
    for run in runs:
        assert run["wall_seconds"] > 0.0
        assert run["peak_memory_mb"] > 0.0
        for field in (
            "result_sha256", "manifest_sha256", "status_summary_sha256"
        ):
            assert SHA256.fullmatch(run[field])

    consistency = audit["numerical_consistency"]
    assert consistency[
        "max_abs_extensive_vs_standard_ccg_objective_difference"
    ] <= min(
        summary["max_objective_tolerance"]
        for summary in audit["tier_summary"].values()
        if summary["max_objective_tolerance"] > 0.0
    )
    assert consistency["max_abs_extensive_vs_standard_ccg_reserve_difference"] < 1e-10
    assert consistency["all_objective_differences_within_plan_tolerance"] is True
    assert consistency["all_exact_evaluations_optimal"] is True
    assert consistency["relative_complete_recourse_violations"] == 0
    assert consistency["solver_values"] == ["gurobi_direct"]

    assert all(audit["artifact_validation"].values())
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())
    assert all(value is False for value in audit["stop_boundary"].values())

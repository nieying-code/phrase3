"""Validate the compact Phase 6 reproducibility-v4 E1 formal audit."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_repro_v4_e1_formal_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")


def test_repro_v4_e1_formal_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["source"] == {
        "execution_git_sha": (
            "e6cffb6a65996f5189dd9d6b06845b485da985bc"
        ),
        "execution_git_tree_sha": (
            "9880f7c76f3e12bc53f295abc752022c029ec016"
        ),
        "tracked_modified_count_at_start": 0,
        "untracked_execution_input_count_at_start": 0,
        "working_tree_dirty": False,
        "controlled_read_write_root": "outputs/phase6_v21_repro_v3/",
        "external_historical_output_directories_used_as_input": False,
    }
    assert audit["fingerprints"] == {
        "scientific_config_sha256": (
            "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3"
        ),
        "family_config_sha256": (
            "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c"
        ),
        "family_component_sha256": (
            "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e"
        ),
        "environment_sha256": (
            "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
        ),
    }
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo": "6.10.1",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert audit["counts"] == {
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

    runs = audit["runs"]
    assert len(runs) == 14
    assert Counter(run["tier_id"] for run in runs) == Counter(
        {"D0": 1, "V1": 3, "V2": 10}
    )
    assert {run["seed"] for run in runs if run["tier_id"] == "D0"} == {
        20260723
    }
    assert {run["seed"] for run in runs if run["tier_id"] == "V1"} == set(
        range(2026072401, 2026072404)
    )
    assert {run["seed"] for run in runs if run["tier_id"] == "V2"} == set(
        range(2026072401, 2026072411)
    )
    assert all(run["execution_mode"] == "formal" for run in runs)
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["parent_run_id"] == "" for run in runs)
    assert sum(run["planned_work_units"] for run in runs) == 45
    assert all(
        run["planned_work_units"] == run["completed_work_units"]
        for run in runs
    )
    for run in runs:
        assert run["wall_seconds"] > 0.0
        for field in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
        ):
            assert SHA256.fullmatch(run[field])

    tiers = audit["tier_summary"]
    assert tiers["D0"]["work_unit_count"] == 6
    assert tiers["V1"]["work_unit_count"] == 9
    assert tiers["V2"]["work_unit_count"] == 30
    assert sum(row["exact_optimal_scenario_count"] for row in tiers.values()) == 7140
    assert all(
        row["max_abs_objective_difference"] <= row["max_objective_tolerance"]
        for row in tiers.values()
    )

    consistency = audit["numerical_consistency"]
    assert consistency[
        "max_abs_extensive_vs_standard_ccg_objective_difference"
    ] == 5.4569682106375694e-12
    assert consistency[
        "max_abs_extensive_vs_standard_ccg_reserve_difference"
    ] == 5.684341886080802e-14
    assert consistency["all_objective_differences_within_plan_tolerance"] is True
    assert consistency["all_exact_evaluations_optimal"] is True
    assert consistency["relative_complete_recourse_violations"] == 0
    assert consistency["solver_values"] == ["gurobi_direct"]

    assert all(audit["artifact_validation"].values())
    assert audit["global_artifacts"] == {
        "family_run_registry_sha256": (
            "0355411199aab404a3af9f61dd0f7cb258432e93c86d891fdcb48be1a0e40df9"
        ),
        "algorithm_performance_sha256": (
            "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3"
        ),
        "pilot_projection_sha256": (
            "c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2"
        ),
    }
    assert audit["authorization_after_batch"] == {
        "projection_status": "passed",
        "compute_gate_passed": True,
        "formal_execution_authorized": True,
    }
    assert all(value is False for value in audit["stop_boundary"].values())

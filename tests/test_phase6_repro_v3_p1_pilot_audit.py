"""Validate the repro-v3 Phase 6 P1 E3 pilot and scale gate audit."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-09_phase6_repro_v3_p1_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}


def test_repro_v3_p1_e3_pilot_audit_and_scale_assessment() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == (
        "1440b288cc875d0ff70b2acbd581ae75764a7724"
    )
    assert source["execution_git_tree_sha"] == (
        "38a16b8a3bf66d49729cdec6fafebe3d479a3579"
    )
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_paths_at_start"] == []
    assert source["working_tree_dirty"] is False
    assert source["historical_output_directories_used_as_input"] is False
    assert source["uncommitted_model_or_configuration_input"] is False
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "e3_component_sha256": "fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083",
        "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
        "runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert audit["counts"] == {
        "primary_run_count": 3,
        "optimal_primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 18,
        "optimal_algorithm_execution_count": 18,
        "cold_execution_count": 9,
        "warm_execution_count": 9,
        "failed_primary_run_count": 0,
        "artifact_invalid_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "diagnostic_attempt_count": 0,
    }

    runs = audit["runs"]
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    assert all(run["execution_mode"] == "pilot" for run in runs)
    assert all(run["tier_id"] == "P1" for run in runs)
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["budget_pair_count"] == 3 for run in runs)
    assert all(run["algorithm_execution_count"] == 6 for run in runs)
    assert all(run["parent_run_id"] is None for run in runs)
    for run in runs:
        for field in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
            "budget_comparison_sha256",
        ):
            assert SHA256.fullmatch(run[field])

    pairs = audit["budget_pairs"]
    assert len(pairs) == 9
    assert {(pair["seed"], pair["budget_factor"]) for pair in pairs} == {
        (seed, factor)
        for seed in SEEDS
        for factor in (0.9, 1.1, 1.3)
    }
    assert all(pair["difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(pair["cold_iterations"] > 0 for pair in pairs)
    assert all(pair["warm_iterations"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["cold_seconds"]) for pair in pairs)
    assert all(math.isfinite(pair["warm_seconds"]) for pair in pairs)

    gate = audit["pilot_scale_advancement_assessment"]
    assert gate["scope"] == "P1 pilot to P2 pilot review authorization only"
    assert gate["planned_pair_count"] == gate["jointly_optimal_pair_count"] == 9
    assert gate["joint_pair_completion_rate"] == 1.0
    assert gate["joint_pair_completion_rate"] >= gate[
        "joint_pair_completion_rate_minimum"
    ]
    assert gate["budget_wall_seconds_per_algorithm"] == 1800.0
    assert gate["maximum_algorithm_median_runtime_fraction"] == max(
        gate["cold_median_runtime_fraction"],
        gate["warm_median_runtime_fraction"],
    )
    assert gate["maximum_algorithm_median_runtime_fraction"] <= gate[
        "maximum_runtime_fraction_threshold"
    ]
    assert gate["assessment_passed"] is True
    assert gate["canonical_scale_advancement_json_created"] is False

    assert audit["numerical_consistency"][
        "max_cold_warm_objective_difference"
    ] == 0.0
    assert audit["numerical_consistency"]["disposal_fields_present"] == {
        "early_disposal": True,
        "expired_waste": True,
        "total_disposal": True,
    }
    projection = audit["projection"]
    assert projection == {
        "completed_run_count": 9,
        "required_run_count": 12,
        "status": "insufficient_pilot_coverage",
        "failed_primary_runs": 0,
        "artifact_invalid_runs": 0,
        "duplicate_primary_runs": 0,
        "diagnostic_attempts": 0,
        "compute_gate_passed": False,
        "formal_execution_authorized": False,
    }
    assert audit["family_prerequisites"] == {
        "family_run_count": 12,
        "completed_work_unit_count": 30,
        "all_optimal": True,
    }
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())
    assert all(value is False for value in audit["stop_boundary"].values())

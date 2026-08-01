"""Validate the compact P2 E3 pilot and complete compute-gate audit."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-01_phase6_v2_1_p2_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}


def test_p2_e3_pilot_and_complete_compute_gate_audit() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == (
        "ce9d5e32fb60e444d90550be07deb61641544f4c"
    )
    assert source["execution_tree_matches_merged_main"] is True
    assert source["execution_git_tree_sha"] == source[
        "merged_main_git_tree_sha"
    ]
    assert source["tracked_modified_count_at_start"] == 0
    assert source["uncommitted_model_or_configuration_input"] is False

    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert all(SHA256.fullmatch(value) for value in audit["fingerprints"].values())

    counts = audit["p2_counts"]
    assert counts == {
        "primary_run_count": 3,
        "optimal_primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 18,
        "optimal_algorithm_execution_count": 18,
        "cold_execution_count": 9,
        "warm_execution_count": 9,
        "failed_primary_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "diagnostic_attempt_count": 0,
    }
    runs = audit["p2_runs"]
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    assert all(run["status"] == "optimal" for run in runs)
    for run in runs:
        assert run["elapsed_seconds"] > 0.0
        assert run["peak_memory_mb"] > 0.0
        for name in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
            "budget_comparison_sha256",
        ):
            assert SHA256.fullmatch(run[name])

    pairs = audit["p2_budget_pairs"]
    assert len(pairs) == 9
    assert {pair["seed"] for pair in pairs} == SEEDS
    assert {pair["budget_factor"] for pair in pairs} == {0.9, 1.1, 1.3}
    assert all(pair["difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(pair["cold_iterations"] > 0 for pair in pairs)
    assert all(pair["warm_iterations"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["cold_seconds"]) for pair in pairs)
    assert all(math.isfinite(pair["warm_seconds"]) for pair in pairs)
    assert audit["p2_numerical_consistency"] == {
        "max_cold_warm_objective_difference": 0.0,
        "max_peak_memory_mb": 220.6171875,
        "disposal_fields_present": {
            "early_disposal": True,
            "expired_waste": True,
            "total_disposal": True,
        },
    }

    e3 = audit["complete_e3_projection"]
    assert e3["completed_run_count"] == e3["required_run_count"] == 12
    assert e3["primary_completion_rate"] == 1.0
    assert e3["tier_run_counts"] == {"V1": 3, "V2": 3, "P1": 3, "P2": 3}
    for field in (
        "missing_run_count",
        "failed_primary_run_count",
        "duplicate_primary_run_count",
        "diagnostic_attempt_count",
    ):
        assert e3[field] == 0

    family = audit["family_projection"]
    assert family["family_primary_run_count"] == 12
    assert family["planned_work_unit_count"] == 30
    assert family["completed_work_unit_count"] == 30
    assert family["statuses"] == {
        "E1": "projected",
        "E2": "projected",
        "E3": "projected",
        "E4": "projected",
        "E5": "projected",
    }
    assert set(family["projected_wall_hours"]) == {
        "E1", "E2", "E3", "E4", "E5"
    }
    assert all(
        value > 0.0 for value in family["projected_wall_hours"].values()
    )

    gate = audit["compute_gate"]
    assert gate["projection_status"] == "passed"
    assert gate["projected_total_wall_hours"] <= gate[
        "maximum_projected_total_wall_hours"
    ]
    assert gate["largest_projected_family_wall_hours"] <= gate[
        "maximum_projected_single_family_wall_hours"
    ]
    assert gate["compute_gate_passed"] is True
    assert gate["formal_execution_authorized"] is True
    assert "remain stopped" in gate["authorization_interpretation"]
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())
    assert all(value is False for value in audit["stop_boundary"].values())

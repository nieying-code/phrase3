"""Validate the compact Phase 6 v2.1 P1 E3 pilot audit."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-01_phase6_v2_1_p1_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}


def test_p1_e3_pilot_audit_and_advancement_assessment() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["source"]["execution_git_sha"] == (
        "9c135f7120ad322302bc2db868f2c77e260e49af"
    )
    assert audit["source"]["tracked_modified_count_at_start"] == 0
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
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "diagnostic_attempt_count": 0,
    }
    runs = audit["runs"]
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    assert all(run["status"] == "optimal" for run in runs)
    for run in runs:
        for name in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
            "budget_comparison_sha256",
        ):
            assert SHA256.fullmatch(run[name])
    pairs = audit["budget_pairs"]
    assert len(pairs) == 9
    assert {pair["seed"] for pair in pairs} == SEEDS
    assert {pair["budget_factor"] for pair in pairs} == {0.9, 1.1, 1.3}
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
    assert gate["maximum_algorithm_median_runtime_fraction"] == max(
        gate["cold_median_runtime_fraction"],
        gate["warm_median_runtime_fraction"],
    )
    assert gate["maximum_algorithm_median_runtime_fraction"] <= gate[
        "maximum_runtime_fraction_threshold"
    ]
    assert gate["assessment_passed"] is True
    assert gate["canonical_scale_advancement_json_created"] is False

    projection = audit["projection"]
    assert projection["completed_run_count"] == 9
    assert projection["required_run_count"] == 12
    assert projection["status"] == "insufficient_pilot_coverage"
    assert projection["failed_primary_runs"] == 0
    assert projection["duplicate_primary_runs"] == 0
    assert projection["diagnostic_attempts"] == 0
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert all(SHA256.fullmatch(value) for value in audit["fingerprints"].values())
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())
    assert all(value is False for value in audit["stop_boundary"].values())

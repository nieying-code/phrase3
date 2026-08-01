"""Validate the compact repro-v3 Phase 6 family-pilot audit snapshot."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path


AUDIT_PATH = Path(
    "docs/handoffs/2026-08-02_phase6_repro_v3_family_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}


def test_repro_v3_family_pilot_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    counts = audit["counts"]
    runs = audit["runs"]

    assert audit["output_root"] == "outputs/phase6_v21_repro_v3"
    assert audit["source"]["tracked_modified_count_at_start"] == 0
    assert audit["source"]["untracked_paths_at_start"] == []
    assert audit["source"]["working_tree_dirty"] is False
    assert re.fullmatch(r"^[0-9a-f]{40}$", audit["source"]["execution_git_sha"])
    assert re.fullmatch(r"^[0-9a-f]{40}$", audit["source"]["execution_git_tree_sha"])
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert counts == {
        "primary_run_count": 12,
        "optimal_primary_run_count": 12,
        "planned_work_unit_count": 30,
        "completed_work_unit_count": 30,
        "failed_primary_run_count": 0,
        "duplicate_primary_run_count": 0,
        "parent_run_count": 0,
        "work_units_by_family": {"E1": 3, "E2": 18, "E4": 3, "E5": 6},
    }

    assert len(runs) == 12
    assert Counter(run["family"] for run in runs) == Counter(
        {"E1": 3, "E2": 3, "E4": 3, "E5": 3}
    )
    for family in ("E1", "E2", "E4", "E5"):
        assert {run["seed"] for run in runs if run["family"] == family} == SEEDS
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["run_id"].startswith("pilot_family_repro_v3_") for run in runs)
    for run in runs:
        assert SHA256.fullmatch(run["result_sha256"])
        assert SHA256.fullmatch(run["manifest_sha256"])
        assert SHA256.fullmatch(run["status_summary_sha256"])

    assert len(audit["e1_consistency"]) == 3
    assert all(item["difference"] == 0.0 for item in audit["e1_consistency"])
    assert all(
        item["extensive_objective"] == item["standard_ccg_objective"]
        and item["extensive_infeasible_recourse_count"] == 0
        and item["standard_ccg_infeasible_recourse_count"] == 0
        for item in audit["e1_consistency"]
    )
    e2 = audit["e2_summary"]
    assert e2["strategy_result_count"] == e2["optimal_count"] == 18
    assert e2["infeasible_recourse_count"] == 0
    assert e2["solver_failure_count"] == 0

    assert len(audit["e4_oos"]) == 3
    assert sum(item["total_scenarios"] for item in audit["e4_oos"]) == 6000
    for item in audit["e4_oos"]:
        assert item["status"] == "optimal"
        assert item["plan_oos_status"] == "complete_feasible"
        assert item["total_scenarios"] == item["optimal_scenarios"] == 2000
        assert item["infeasible_scenarios"] == 0
        assert item["solver_failures"] == 0
        assert SHA256.fullmatch(item["source_e2_result_sha256"])
        for name in (
            "mean_total_cost",
            "p95_total_cost",
            "cvar95_total_cost",
            "service_level",
            "mean_early_disposal",
            "mean_expired_waste",
            "mean_total_disposal",
        ):
            assert math.isfinite(item[name])
        assert math.isclose(
            item["mean_total_disposal"],
            item["mean_early_disposal"] + item["mean_expired_waste"],
            rel_tol=1e-12,
            abs_tol=1e-9,
        )
    e5 = audit["e5_summary"]
    assert e5["configuration_result_count"] == e5["optimal_count"] == 6

    expected_fingerprints = {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "e3_component_sha256": "fd0dc3ea77f850615502005e2caf9f3b7c0259d7c11a9efc7e2a30025c404083",
        "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
        "family_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    assert audit["fingerprints"] == expected_fingerprints
    assert all(SHA256.fullmatch(value) for value in expected_fingerprints.values())
    assert all(SHA256.fullmatch(value) for value in audit["global_artifacts"].values())

    projection = audit["projection"]
    assert projection["e3_completed_run_count"] == 3
    assert projection["e3_required_run_count"] == 12
    assert projection["family_status"] == {
        "E1": "projected",
        "E2": "projected",
        "E3": "awaiting_complete_pilots",
        "E4": "projected",
        "E5": "projected",
    }
    assert projection["status"] == "projection_incomplete"
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert all(value is False for value in audit["stop_boundary"].values())

"""Validate the compact Phase 6 v2.1 family-pilot audit snapshot."""

from __future__ import annotations

import json
import math
import re
from collections import Counter
from pathlib import Path


AUDIT_PATH = Path(
    "docs/handoffs/2026-08-01_phase6_v2_1_family_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}


def test_family_pilot_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    counts = audit["counts"]
    runs = audit["runs"]

    assert audit["output_root"] == "outputs/phase6_v21_rr_clean"
    assert audit["environment"] == {
        "python": "3.12.10",
        "gurobipy": "13.0.2",
        "gurobi_optimizer": "13.0.2",
        "pyomo_interface": "gurobi_direct",
        "threads": 1,
        "highs_fallback": False,
    }
    assert counts["primary_run_count"] == 12
    assert counts["optimal_primary_run_count"] == 12
    assert counts["planned_work_unit_count"] == 30
    assert counts["completed_work_unit_count"] == 30
    assert counts["failed_primary_run_count"] == 0
    assert counts["duplicate_primary_run_count"] == 0
    assert counts["parent_run_count"] == 0
    assert counts["work_units_by_family"] == {
        "E1": 3,
        "E2": 18,
        "E4": 3,
        "E5": 6,
    }

    assert len(runs) == 12
    assert Counter(run["family"] for run in runs) == Counter(
        {"E1": 3, "E2": 3, "E4": 3, "E5": 3}
    )
    for family in ("E1", "E2", "E4", "E5"):
        assert {run["seed"] for run in runs if run["family"] == family} == SEEDS
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["run_id"].startswith("pilot_rr_v21_postv1_family_") for run in runs)
    for run in runs:
        assert SHA256.fullmatch(run["result_sha256"])
        assert SHA256.fullmatch(run["manifest_sha256"])
        assert SHA256.fullmatch(run["status_summary_sha256"])

    assert len(audit["e1_consistency"]) == 3
    assert all(item["difference"] == 0.0 for item in audit["e1_consistency"])
    assert all(
        item["extensive_objective"] == item["standard_ccg_objective"]
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
        "e3_component_sha256": "7713671bab67eec8d99fdf776f1d645740d09d020ef31b55513ccc80595f951f",
        "family_component_sha256": "5803afd60d39a2e982d9b2c879453ef2d4e21755fcb46791810a1e1de8e5076f",
        "family_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
        "environment_sha256": "0306c49cf953a79e3ade0fdf537e074dd17ddb942677333c62ef3f1bfb4782c2",
    }
    assert audit["fingerprints"] == expected_fingerprints
    assert all(SHA256.fullmatch(value) for value in expected_fingerprints.values())
    assert all(
        SHA256.fullmatch(value) for value in audit["global_artifacts"].values()
    )

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

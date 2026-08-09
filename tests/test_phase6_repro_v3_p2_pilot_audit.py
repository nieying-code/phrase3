"""Validate repro-v3 P2 pilots and the complete Phase 6 compute gate."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-09_phase6_repro_v3_p2_e3_pilots_audit.json"
)
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SEEDS = {2026072001, 2026072002, 2026072003}
FACTORS = {0.9, 1.1, 1.3}


def test_repro_v3_p2_pilots_and_complete_compute_gate() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["audit_schema"] == (
        "phase6_repro_v3_p2_e3_pilots_and_compute_gate_v2"
    )
    source = audit["source"]
    assert source["execution_git_sha"] == (
        "b53eb42c323f36175ad89940aec1fd460e66a171"
    )
    assert source["execution_git_tree_sha"] == (
        "bc569a17f3e60d08953f8ba6678b9ffe6fcf6cf9"
    )
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False
    assert source["controlled_read_write_root"] == {
        "path": "outputs/phase6_v21_repro_v3/",
        "read_inputs": {
            "approved_v1_v2_p1_e3_registry": (
                "experiments/phase6/run_registry.csv"
            ),
            "approved_v1_v2_p1_e3_projection": (
                "experiments/phase6/pilot_throughput_projection.json"
            ),
            "approved_family_prerequisite_registry": (
                "experiments/phase6/family_run_registry.csv"
            ),
            "approved_family_prerequisite_artifacts": (
                "experiments/phase6/family_runs/*/{result.json,manifest.json}"
            ),
        },
        "write_outputs": {
            "current_p2_e3_pilot_artifacts": (
                "experiments/phase6/runs/pilot_p2_repro_v3_*"
            ),
            "updated_e3_registry": "experiments/phase6/run_registry.csv",
            "updated_e3_projection": (
                "experiments/phase6/pilot_throughput_projection.json"
            ),
        },
    }
    assert source["external_historical_output_directories_used_as_input"] is False
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
    assert audit["p2_counts"] == {
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

    runs = audit["p2_runs"]
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    assert all(run["execution_mode"] == "pilot" for run in runs)
    assert all(run["tier_id"] == "P2" for run in runs)
    assert all(run["status"] == "optimal" for run in runs)
    assert all(run["budget_pair_count"] == 3 for run in runs)
    assert all(run["algorithm_execution_count"] == 6 for run in runs)
    assert all(run["worker_seconds"] > 0.0 for run in runs)
    assert all(run["peak_memory_mb"] > 0.0 for run in runs)
    assert all(run["manifest_result_sha256_matches"] is True for run in runs)
    for run in runs:
        assert run["disposal_fields_present"] == {
            "early_disposal": True,
            "expired_waste": True,
            "total_disposal": True,
        }
        for name in (
            "result_sha256",
            "manifest_sha256",
            "status_summary_sha256",
            "budget_comparison_sha256",
        ):
            assert SHA256.fullmatch(run[name])

    pairs = audit["p2_budget_pairs"]
    assert len(pairs) == 9
    assert {(row["seed"], row["budget_factor"]) for row in pairs} == {
        (seed, factor) for seed in SEEDS for factor in FACTORS
    }
    assert all(row["cold_status"] == "optimal" for row in pairs)
    assert all(row["warm_status"] == "optimal" for row in pairs)
    assert all(row["cold_objective"] == row["warm_objective"] for row in pairs)
    assert all(row["difference"] == 0.0 for row in pairs)
    assert all(row["cold_iterations"] > 0 for row in pairs)
    assert all(row["warm_iterations"] > 0 for row in pairs)
    assert all(math.isfinite(row["cold_seconds"]) for row in pairs)
    assert all(math.isfinite(row["warm_seconds"]) for row in pairs)
    assert audit["p2_numerical_consistency"] == {
        "max_cold_warm_objective_difference": 0.0,
        "max_peak_memory_mb": max(run["peak_memory_mb"] for run in runs),
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
    for name in (
        "missing_run_count",
        "failed_primary_run_count",
        "artifact_invalid_run_count",
        "duplicate_primary_run_count",
        "diagnostic_attempt_count",
    ):
        assert e3[name] == 0

    family = audit["family_projection"]
    assert family["projection_method"] == (
        "experiment_family_specific_dimensionally_consistent_rates"
    )
    assert family["family_primary_run_count"] == 12
    assert family["planned_work_unit_count"] == 30
    assert family["completed_work_unit_count"] == 30
    assert family["all_optimal"] is True
    families = family["families"]
    assert set(families) == {"E1", "E2", "E3", "E4", "E5"}
    assert all(row["status"] == "projected" for row in families.values())
    expected_plans = {"E1": 45, "E2": 180, "E4": 90, "E5": 75}
    recalculated_hours: dict[str, float] = {}
    for name, planned in expected_plans.items():
        row = families[name]
        assert row["work_unit"] == "complete_family_plan"
        assert row["planned_work_units"] == planned
        assert row["pilot_seeds"] == sorted(SEEDS)
        assert row["pilot_run_ids"] == [
            f"pilot_family_repro_v3_{name.lower()}_{seed}"
            for seed in sorted(SEEDS)
        ]
        rate = row["conservative_work_units_per_hour"]
        assert rate > 0.0
        recalculated = planned / rate
        assert math.isclose(
            row["projected_wall_hours"],
            recalculated,
            rel_tol=0.0,
            abs_tol=1e-15,
        )
        recalculated_hours[name] = recalculated

    e3_family = families["E3"]
    assert e3_family["work_unit"] == "recourse_lp_solve"
    assert e3_family["pilot_seeds"] == sorted(SEEDS)
    assert set(e3_family["pilot_run_ids"]) == {
        f"pilot_{tier.lower()}_repro_v3_{seed}"
        for tier in ("V1", "V2", "P1", "P2")
        for seed in SEEDS
    }
    assert e3_family["estimated_recourse_lp_calls"] == 519000
    e3_rate = e3_family["conservative_recourse_lp_solves_per_hour"]
    assert e3_rate > 0.0
    recalculated_e3 = 519000 / e3_rate
    assert math.isclose(
        e3_family["projected_wall_hours"],
        recalculated_e3,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    recalculated_hours["E3"] = recalculated_e3

    gate = audit["compute_gate"]
    total_hours = sum(recalculated_hours.values())
    largest_hours = max(recalculated_hours.values())
    assert math.isclose(
        gate["projected_total_wall_hours"], total_hours, rel_tol=0.0, abs_tol=1e-12
    )
    assert math.isclose(
        gate["largest_projected_family_wall_hours"],
        largest_hours,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert gate["maximum_projected_total_wall_hours"] == 168.0
    assert gate["maximum_projected_single_family_wall_hours"] == 72.0
    all_families_projected = all(
        row["status"] == "projected" for row in families.values()
    )
    e3_complete = (
        e3["completed_run_count"] == e3["required_run_count"] == 12
        and all(
            e3[name] == 0
            for name in (
                "missing_run_count",
                "failed_primary_run_count",
                "artifact_invalid_run_count",
                "duplicate_primary_run_count",
                "diagnostic_attempt_count",
            )
        )
    )
    family_complete = (
        family["family_primary_run_count"] == 12
        and family["planned_work_unit_count"] == 30
        and family["completed_work_unit_count"] == 30
        and family["all_optimal"] is True
    )
    expected_gate = (
        all_families_projected
        and e3_complete
        and family_complete
        and total_hours <= 168.0
        and largest_hours <= 72.0
    )
    assert gate["projection_status"] == "passed"
    assert gate["compute_gate_passed"] is expected_gate
    assert gate["matrix_status"] == "frozen_for_formal_execution"
    expected_authorization = (
        expected_gate and gate["matrix_status"] == "frozen_for_formal_execution"
    )
    assert gate["formal_execution_authorized"] is expected_authorization
    assert "remain stopped" in gate["authorization_interpretation"]
    assert audit["global_artifacts"] == {
        "run_registry_sha256": "0943977b50ed789771cd4ee1d075511b7070b559877024103ef7bc548c9807c4",
        "algorithm_performance_sha256": "dbf9273d830946620f21efb82fdafe9c93a163e638ac9749554aa7f1379512cb",
        "pilot_projection_sha256": "c048043c616b141a22ea9dedb0b21f4bb66a81c41988183ec586868265935d40",
        "family_registry_sha256": "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9",
    }
    assert all(value is False for value in audit["stop_boundary"].values())

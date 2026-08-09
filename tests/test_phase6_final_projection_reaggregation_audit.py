"""Validate the final Phase 6 projection reaggregation audit."""

from __future__ import annotations

import json
import math
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-09_phase6_final_projection_reaggregation_audit.json"
)
SEEDS = [2026072001, 2026072002, 2026072003]
FINGERPRINTS = {
    "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
    "e3_component_sha256": "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e",
    "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
    "e3_runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
    "family_runner_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
GLOBAL_HASHES = {
    "run_registry.csv": "3a46e655fbeca18f730f755c2d38a9ebdfc6946be4ef7a9ba9576535975a4fe9",
    "algorithm_performance.csv": "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3",
    "family_run_registry.csv": "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9",
    "pilot_throughput_projection_before.json": "ca5bea5f4e2a5876d3a76cf4778f92439097ac0c9f9a16ba9b666eaa351f33eb",
    "pilot_throughput_projection_after.json": "c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2",
}
FAMILY_PROJECTION_INPUTS = {
    "E1": {
        "work_unit": "complete_family_plan",
        "planned_work_units": 45,
        "conservative_work_units_per_hour": 1456.0171201608373,
        "projected_wall_hours": 0.030906230000255167,
        "pilot_run_ids": [
            "pilot_family_repro_v3_e1_2026072001",
            "pilot_family_repro_v3_e1_2026072002",
            "pilot_family_repro_v3_e1_2026072003",
        ],
    },
    "E2": {
        "work_unit": "complete_family_plan",
        "planned_work_units": 180,
        "conservative_work_units_per_hour": 1365.0234135596927,
        "projected_wall_hours": 0.13186587000042588,
        "pilot_run_ids": [
            "pilot_family_repro_v3_e2_2026072001",
            "pilot_family_repro_v3_e2_2026072002",
            "pilot_family_repro_v3_e2_2026072003",
        ],
    },
    "E4": {
        "work_unit": "complete_family_plan",
        "planned_work_units": 90,
        "conservative_work_units_per_hour": 118.06314963061385,
        "projected_wall_hours": 0.7623039049998624,
        "pilot_run_ids": [
            "pilot_family_repro_v3_e4_2026072001",
            "pilot_family_repro_v3_e4_2026072002",
            "pilot_family_repro_v3_e4_2026072003",
        ],
    },
    "E5": {
        "work_unit": "complete_family_plan",
        "planned_work_units": 75,
        "conservative_work_units_per_hour": 1626.8554427662136,
        "projected_wall_hours": 0.04610120729133389,
        "pilot_run_ids": [
            "pilot_family_repro_v3_e5_2026072001",
            "pilot_family_repro_v3_e5_2026072002",
            "pilot_family_repro_v3_e5_2026072003",
        ],
    },
}
E3_PROJECTION_INPUTS = {
    "work_unit": "recourse_lp_solve",
    "estimated_recourse_lp_calls": 519000,
    "conservative_recourse_lp_solves_per_hour": 58516.74272579252,
    "projected_wall_hours": 8.86925648667795,
}


def test_final_projection_reaggregation_audit() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == (
        "f91e10c9140fc49b4a67dcaadc654a8bfb9df8e3"
    )
    assert source["execution_git_tree_sha"] == (
        "e3ed562c3a63cb45309f86e8a681f4cd6acea000"
    )
    assert source["working_tree_dirty_at_start"] is False
    assert source["untracked_execution_input_count_at_start"] == 0
    assert audit["fingerprints"] == FINGERPRINTS

    operation = audit["operation"]
    assert operation["write_outputs"] == [
        "experiments/phase6/pilot_throughput_projection.json"
    ]
    for field in (
        "scenario_generation_performed",
        "gurobi_solve_performed",
        "new_pilot_run_performed",
        "formal_seed_started",
    ):
        assert operation[field] is False

    e3 = audit["e3_gate_inputs"]
    assert e3["completed_run_count"] == e3["required_run_count"] == 12
    assert e3["primary_completion_rate"] == 1.0
    assert e3["tier_run_counts"] == {"V1": 3, "V2": 3, "P1": 3, "P2": 3}
    for field in (
        "missing_runs",
        "failed_primary_runs",
        "artifact_invalid_runs",
        "duplicate_primary_runs",
        "diagnostic_attempts",
    ):
        assert e3[field] == []

    family_gate = audit["family_gate_inputs"]
    assert family_gate == {
        "primary_run_count": 12,
        "planned_work_unit_count": 30,
        "completed_work_unit_count": 30,
        "nonoptimal_run_ids": [],
    }

    projections = audit["family_projections"]
    assert set(projections) == {"E1", "E2", "E3", "E4", "E5"}
    recomputed: dict[str, float] = {}
    for family in ("E1", "E2", "E4", "E5"):
        row = projections[family]
        assert row["status"] == "projected"
        assert row["pilot_seeds"] == SEEDS
        approved = FAMILY_PROJECTION_INPUTS[family]
        for field in (
            "work_unit",
            "planned_work_units",
            "conservative_work_units_per_hour",
            "projected_wall_hours",
            "pilot_run_ids",
        ):
            assert row[field] == approved[field]
        expected = row["planned_work_units"] / row[
            "conservative_work_units_per_hour"
        ]
        assert math.isclose(
            expected, row["projected_wall_hours"], rel_tol=0.0, abs_tol=1e-12
        )
        recomputed[family] = expected
    e3_projection = projections["E3"]
    assert e3_projection["status"] == "projected"
    for field, approved in E3_PROJECTION_INPUTS.items():
        assert e3_projection[field] == approved
    recomputed["E3"] = E3_PROJECTION_INPUTS[
        "estimated_recourse_lp_calls"
    ] / E3_PROJECTION_INPUTS[
        "conservative_recourse_lp_solves_per_hour"
    ]
    assert math.isclose(
        recomputed["E3"],
        e3_projection["projected_wall_hours"],
        rel_tol=0.0,
        abs_tol=1e-12,
    )

    gate = audit["compute_gate"]
    assert gate["projection_status"] == "passed"
    assert gate["matrix_status"] == "frozen_for_formal_execution"
    total = sum(recomputed.values())
    largest_family = max(recomputed, key=recomputed.get)
    assert math.isclose(
        total, gate["projected_total_wall_hours"], rel_tol=0.0, abs_tol=1e-12
    )
    assert largest_family == gate["largest_projected_family"] == "E3"
    assert math.isclose(
        recomputed[largest_family],
        gate["largest_projected_family_wall_hours"],
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert gate["maximum_projected_total_wall_hours"] == 168.0
    assert gate["maximum_projected_single_family_wall_hours"] == 72.0
    all_projected = all(row["status"] == "projected" for row in projections.values())
    e3_complete = (
        e3["completed_run_count"] == e3["required_run_count"]
        and all(not e3[field] for field in (
            "missing_runs",
            "failed_primary_runs",
            "artifact_invalid_runs",
            "duplicate_primary_runs",
            "diagnostic_attempts",
        ))
    )
    family_complete = (
        family_gate["primary_run_count"] == 12
        and family_gate["completed_work_unit_count"]
        == family_gate["planned_work_unit_count"] == 30
        and not family_gate["nonoptimal_run_ids"]
    )
    expected_compute_gate = (
        all_projected
        and e3_complete
        and family_complete
        and total <= 168.0
        and recomputed[largest_family] <= 72.0
    )
    assert gate["compute_gate_passed"] is expected_compute_gate is True
    expected_authorization = (
        expected_compute_gate
        and gate["matrix_status"] == "frozen_for_formal_execution"
    )
    assert gate["formal_execution_authorized"] is expected_authorization is True
    assert "remain stopped" in gate["authorization_interpretation"]
    assert audit["global_artifact_sha256"] == GLOBAL_HASHES
    assert all(value is False for value in audit["stop_boundary"].values())

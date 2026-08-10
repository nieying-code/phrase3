"""Validate the compact Phase 6 reproducibility-v4 E1 formal audit."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_repro_v4_e1_formal_audit.json"
)
EXPECTED_RUNS = {
    "formal_e1_repro_v4_d0_20260723": {
        "tier_id": "D0", "seed": 20260723, "planned_work_units": 6,
        "result_sha256": "487005d63bf5263b9e807ca965eaa24062c990e96c87c8b6de344691cbf90f17",
        "manifest_sha256": "f9f90c2842377937a281f1cb4a73148efb1fac7c01192383eb4b75cb342a5124",
        "status_summary_sha256": "bf230d1699eedc72e28545b1561c40d3e29a349a2ea10074e4aadef47b023003",
    },
    "formal_e1_repro_v4_v1_2026072401": {
        "tier_id": "V1", "seed": 2026072401, "planned_work_units": 3,
        "result_sha256": "a80ac558d33cdd1e2f5ab1b5f215c6539c183f1371472e64e73ee2c3d6c3794b",
        "manifest_sha256": "6b0047e19c6c6ee1c6afb444fd9336a750c7ac5d5925e2075ca8941c842c9615",
        "status_summary_sha256": "c9c261f347f633e75de99b0e1429b394162421eab6d13b350ab88f32ccbdb9bd",
    },
    "formal_e1_repro_v4_v1_2026072402": {
        "tier_id": "V1", "seed": 2026072402, "planned_work_units": 3,
        "result_sha256": "7cd741e0883d3c7811e4f968fa76783c435ab428a64e2331c77bb8d6b6bbf626",
        "manifest_sha256": "ad984848588c52fb273476bf3e8003afaee63cbb723f1655465ea04a57e9ab22",
        "status_summary_sha256": "0fdaeb4fa42b2e18a5b570fd73dca596100b9e0ef29a6cecf485726ca6468edb",
    },
    "formal_e1_repro_v4_v1_2026072403": {
        "tier_id": "V1", "seed": 2026072403, "planned_work_units": 3,
        "result_sha256": "1526e42b1b8c404c00cc1d7ed5b1ae94b78cc57814442f01361870a7c32d0185",
        "manifest_sha256": "8a21509b0d5513a9a93af3d6915ef43c0d3c7a979edd4059e88f706e525509be",
        "status_summary_sha256": "d12140d557ce55257d32694ebf1bf5296bdb7e8a97ec1622a53ef4ebfb549dd4",
    },
    "formal_e1_repro_v4_v2_2026072401": {
        "tier_id": "V2", "seed": 2026072401, "planned_work_units": 3,
        "result_sha256": "a427e017f90a17c66db09a177fe79fd17a8402e87da8e82f35866c2eb09209ae",
        "manifest_sha256": "e32d192969e0e46ce5d472dc4010728deed1b14cf37019b84e04fc5b933aa66e",
        "status_summary_sha256": "dd81bf3a367a71c3c26a26d4454effb9edcfec6fe0fcde7d7b9f1c1327b9bfac",
    },
    "formal_e1_repro_v4_v2_2026072402": {
        "tier_id": "V2", "seed": 2026072402, "planned_work_units": 3,
        "result_sha256": "bd88095666e9f7e140edbd2ca0ce39eba82346315595d9d7e17ae3dd63dcf718",
        "manifest_sha256": "7c688063e0ade477f40dda0714ac49ee9c2f18ad72ef80aaf2a81784218b5ee4",
        "status_summary_sha256": "e3f6a390e6283239b461f61cff874d98bef0c93a23c8da8e5ba9d106fcfe07d7",
    },
    "formal_e1_repro_v4_v2_2026072403": {
        "tier_id": "V2", "seed": 2026072403, "planned_work_units": 3,
        "result_sha256": "8a7ce9b76d7e2806fbd7ccd964635dfc3353a728a35736ef722db00e196f8e6c",
        "manifest_sha256": "35ecca6c1f3d181f1acb7b1f83d0b483dd3ff5163fb419118899e7c9a562bda1",
        "status_summary_sha256": "642fb4f0b0122f076b1b09ee286a8aa2f5b3f7583fc9bd660516e49b0340b010",
    },
    "formal_e1_repro_v4_v2_2026072404": {
        "tier_id": "V2", "seed": 2026072404, "planned_work_units": 3,
        "result_sha256": "a522f7224876af97787b9e061543f1e7f0085885fa35e3056d470cb525d51c92",
        "manifest_sha256": "b5a0b3ae4bab89682b8281bc1c3b8297d04d010a9e16259ed1874e4214e6f25b",
        "status_summary_sha256": "a705c68a1961037b46799791bcfc941c475473d580415824863bcb6ab586f05a",
    },
    "formal_e1_repro_v4_v2_2026072405": {
        "tier_id": "V2", "seed": 2026072405, "planned_work_units": 3,
        "result_sha256": "cbc7f2db885516fdb5dd2eca0fe0e17b8f9fb8a392901ad399ecbeeb5c2025ea",
        "manifest_sha256": "2fcfa033df1cf7e7c29823e4f8b248927cc0e5d33715a032e774c406c12018df",
        "status_summary_sha256": "ae364b6d4f57e85f8d3b3a9825b4225eaf5f5a7587b9413644be0c271e4f44db",
    },
    "formal_e1_repro_v4_v2_2026072406": {
        "tier_id": "V2", "seed": 2026072406, "planned_work_units": 3,
        "result_sha256": "24ce0c7ffaaddc5de55f0c3ff31521fc4570dd08c717358cd2c79b6c9519d67b",
        "manifest_sha256": "0ae832ec2faa2416b3ee5621f00ac7e056dd6b05f8f658a8460f7e2c4155f93b",
        "status_summary_sha256": "727b34b7c15174cfc6e852e8e5bcdccce0501637990409f0a1523c5735af9eb1",
    },
    "formal_e1_repro_v4_v2_2026072407": {
        "tier_id": "V2", "seed": 2026072407, "planned_work_units": 3,
        "result_sha256": "10eb6431a5706422394d71993d8a659fae88b348d35a79ae2fcbb139b60f9fba",
        "manifest_sha256": "e6478a3187fb3277289b6a50d29ce20802ac1ee780a5fe7ba8110f5debc78fad",
        "status_summary_sha256": "2a7f8de73df315b83b39c669605b0008c869cada2474d0575172a3431334b836",
    },
    "formal_e1_repro_v4_v2_2026072408": {
        "tier_id": "V2", "seed": 2026072408, "planned_work_units": 3,
        "result_sha256": "7fcbe791fa48b13c47f1054d02c542ac2f02dd43a114c7817f464dece2685d1a",
        "manifest_sha256": "01cd5fd7ca73f92bb8a1f8271085db62980e2df5c43ea10088aeedf8c4aa6c17",
        "status_summary_sha256": "896a7adf7ed65322b2ca3155a38b182dd2ce48da0f73e5b759509a82443ec2b8",
    },
    "formal_e1_repro_v4_v2_2026072409": {
        "tier_id": "V2", "seed": 2026072409, "planned_work_units": 3,
        "result_sha256": "04f2d8867224ba3d11917f6b5e47e264a2e2ecaff926d91a6471db56efafa335",
        "manifest_sha256": "a12dbdb2330aff25c9cdc4e4b17b580cbfe94f4476bb6089755bf172dd45b493",
        "status_summary_sha256": "f9ba20a44368228324241485bcad58d910d05cb667861e1ecf838e55d8fc1857",
    },
    "formal_e1_repro_v4_v2_2026072410": {
        "tier_id": "V2", "seed": 2026072410, "planned_work_units": 3,
        "result_sha256": "814b893344081a0725d0c88d6418da965831a7d9a2cba9143f75171126da9918",
        "manifest_sha256": "f139130865be6593fcbdc0e5de6edc05d90c3f7dac7cf8849b6cef7b0226f2c5",
        "status_summary_sha256": "bd36d22b1f63688fc5653f9582a122537eff0bedc33d6331e3902f02d15af515",
    },
}
EXPECTED_TIER_CLOSURE = {
    "D0": {"run_count": 1, "work_units": 6, "blocks": 12, "scenarios": 240},
    "V1": {"run_count": 3, "work_units": 9, "blocks": 18, "scenarios": 900},
    "V2": {"run_count": 10, "work_units": 30, "blocks": 60, "scenarios": 6000},
}


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
    observed_runs = {run["run_id"]: run for run in runs}
    assert set(observed_runs) == set(EXPECTED_RUNS)
    assert len(observed_runs) == 14
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
    for run_id, expected in EXPECTED_RUNS.items():
        run = observed_runs[run_id]
        for field, expected_value in expected.items():
            assert run[field] == expected_value
        assert run["completed_work_units"] == expected["planned_work_units"]
        assert run["execution_mode"] == "formal"
        assert run["status"] == "optimal"
        assert run["parent_run_id"] == ""
        assert run["wall_seconds"] > 0.0

    tiers = audit["tier_summary"]
    recomputed_work_units = 0
    recomputed_blocks = 0
    recomputed_scenarios = 0
    for tier_id, expected in EXPECTED_TIER_CLOSURE.items():
        tier_runs = [run for run in runs if run["tier_id"] == tier_id]
        work_units = sum(run["planned_work_units"] for run in tier_runs)
        assert len(tier_runs) == expected["run_count"]
        assert work_units == expected["work_units"]
        assert tiers[tier_id]["work_unit_count"] == work_units
        assert tiers[tier_id]["exact_evaluation_block_count"] == expected["blocks"]
        assert tiers[tier_id]["exact_optimal_scenario_count"] == expected["scenarios"]
        recomputed_work_units += work_units
        recomputed_blocks += expected["blocks"]
        recomputed_scenarios += expected["scenarios"]
    assert recomputed_work_units == 45
    assert recomputed_work_units * 2 == 90
    assert recomputed_blocks == 90
    assert recomputed_scenarios == 7140
    assert audit["counts"]["planned_work_unit_count"] == recomputed_work_units
    assert audit["counts"]["total_model_algorithm_execution_count"] == (
        recomputed_work_units * 2
    )
    assert audit["counts"]["exact_evaluation_block_count"] == recomputed_blocks
    assert audit["counts"]["exact_optimal_scenario_count"] == recomputed_scenarios
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

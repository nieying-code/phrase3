from __future__ import annotations

import json
import math
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-09_phase6_e3_p1_repro_v4_pilots_audit.json"
)
SEEDS = {2026072001, 2026072002, 2026072003}
FINGERPRINTS = {
    "scientific_config_sha256": (
        "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3"
    ),
    "e3_component_sha256": (
        "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e"
    ),
    "family_component_sha256": (
        "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e"
    ),
    "runner_config_sha256": (
        "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd"
    ),
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}
RUN_HASHES = {
    "pilot_e3_repro_v4_p1_2026072001": {
        "result.json": "b0c0cd8ee01abc422f86efbd00ad8f91f984252f3e4f9ae3a171b50df8a72eb0",
        "manifest.json": "424773d85bb393f06bb3e4389685d1f4b8ea36162750d5b37290665fb15b58f4",
        "status_summary.json": "34dcad980665a2e96c8b247a1c39a5c1b12b22120717dbdd0c38c74371860fc4",
        "budget_comparison.csv": "d39f2a75770e302ff117e20e0f7b6900344e3297946ea5459c53427c076bb258",
    },
    "pilot_e3_repro_v4_p1_2026072002": {
        "result.json": "dc7f7059989c17e67ec596d52450d9d8d54c533735ad172aaf5836c90195ddd5",
        "manifest.json": "9d44b51d5b28ad66901cd3f2ace17f742ea2beebb585afc029bf31f22fbd6edc",
        "status_summary.json": "e8fe0236d82bfaf11574c8533ad13584f3ceb4e8582c67dbf6c8b3e9ccc41c7f",
        "budget_comparison.csv": "4eb3ba6ba7d50d5f199612755dd8a6e0c0b67b919158c2a3fb63d2629a574450",
    },
    "pilot_e3_repro_v4_p1_2026072003": {
        "result.json": "8934661cbab6ad77f4154d6dbda2fd07ea8748efc510dcf8bb14e8c41e50d2d9",
        "manifest.json": "a9d4ba9ed58e9fdc699009cbf9f9b136f6685374e335feecfb1543d3976e6057",
        "status_summary.json": "db34c7816074ada44d61ce8ec75a6002af45856e9a8b9f99486a83e117cc02f3",
        "budget_comparison.csv": "4efe40f7347e2225a4f3551ac582c2f947cfe4ab7cf20fa4f83d00ec317cc72f",
    },
}
GLOBAL_HASHES = {
    "run_registry.csv": "814e3e865987c7622554fc5a9c3100272a8565ab944caa5f4e1deb9c7b87af57",
    "algorithm_performance.csv": "6e3d79bf6f81ade7441b4850c36d441c7d587de2f43e310ef4ca4052eed9f729",
    "pilot_throughput_projection.json": "31c97a4f4b35a7c411ce41f2aed8eb2509b81848f98843e1891e4c21cef4cd00",
    "family_run_registry.csv": "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9",
}


def test_phase6_e3_p1_repro_v4_audit_and_scale_gate() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == source["merged_main_sha"] == (
        "de1593e94b4cd22653255421a21a0c6b792ffdd2"
    )
    assert source["execution_git_tree_sha"] == source["merged_main_tree_sha"] == (
        "5424daebb2da574034c5b210e9a4e02d64d1c451"
    )
    assert source["tree_equivalent"] is True
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False
    assert source["external_historical_output_directories_used_as_input"] is False
    assert source["uncommitted_model_or_configuration_input"] is False
    assert audit["fingerprints"] == FINGERPRINTS

    runs = audit["runs"]
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == SEEDS
    for run in runs:
        assert run["tier_id"] == "P1"
        assert run["execution_mode"] == "pilot"
        assert run["status"] == "optimal"
        assert run["parent_run_id"] is None
        assert run["planned_budget_count"] == run["completed_budget_count"] == 3
        assert run["algorithm_execution_count"] == 6
        assert run["fingerprints_match_approved"] is True
        assert run["disposal_fields"] == [
            "early_disposal",
            "expired_waste",
            "total_disposal",
        ]
        assert run["artifact_sha256"] == RUN_HASHES[run["run_id"]]

    pairs = audit["budget_pairs"]
    assert len(pairs) == 9
    assert {(pair["seed"], pair["budget_factor"]) for pair in pairs} == {
        (seed, factor) for seed in SEEDS for factor in (0.9, 1.1, 1.3)
    }
    assert all(pair["cold_status"] == pair["warm_status"] == "optimal" for pair in pairs)
    assert all(pair["scenario_count"] == 500 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(pair["difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_iterations"] > 0 for pair in pairs)
    assert all(pair["warm_iterations"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["cold_seconds"]) and pair["cold_seconds"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["warm_seconds"]) and pair["warm_seconds"] > 0 for pair in pairs)

    counts = audit["counts"]
    assert counts == {
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

    cold_median = statistics.median(pair["cold_seconds"] for pair in pairs)
    warm_median = statistics.median(pair["warm_seconds"] for pair in pairs)
    consistency = audit["numerical_consistency"]
    assert cold_median == consistency["cold_median_seconds"]
    assert warm_median == consistency["warm_median_seconds"]
    assert consistency["max_cold_warm_objective_difference"] == 0.0

    gate = audit["pilot_scale_advancement_assessment"]
    planned_pairs = len(pairs)
    jointly_optimal = sum(
        pair["cold_status"] == pair["warm_status"] == "optimal"
        and pair["cold_objective"] == pair["warm_objective"]
        for pair in pairs
    )
    completion_rate = jointly_optimal / planned_pairs
    assert gate["planned_pair_count"] == planned_pairs == 9
    assert gate["jointly_optimal_pair_count"] == jointly_optimal == 9
    assert gate["joint_pair_completion_rate"] == completion_rate == 1.0
    assert gate["joint_pair_completion_rate_minimum"] == 0.80
    assert gate["maximum_runtime_fraction_threshold"] == 0.75
    assert gate["budget_wall_seconds_per_algorithm"] == 1800.0
    cold_fraction = cold_median / 1800.0
    warm_fraction = warm_median / 1800.0
    maximum_fraction = max(cold_fraction, warm_fraction)
    assert math.isclose(gate["cold_median_runtime_fraction"], cold_fraction, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(gate["warm_median_runtime_fraction"], warm_fraction, rel_tol=0.0, abs_tol=1e-15)
    assert math.isclose(gate["maximum_algorithm_median_runtime_fraction"], maximum_fraction, rel_tol=0.0, abs_tol=1e-15)
    assert gate["assessment_passed"] is (
        completion_rate >= 0.80 and maximum_fraction <= 0.75
    )
    assert gate["canonical_scale_advancement_json_created"] is False

    projection = audit["projection"]
    assert {(row["tier_id"], row["seed"]) for row in projection["missing_runs"]} == {
        ("P2", seed) for seed in SEEDS
    }
    assert projection["completed_run_count"] == 9
    assert projection["required_run_count"] == 12
    assert projection["completed_run_count"] + len(projection["missing_runs"]) == 12
    assert projection["primary_completion_rate"] == 0.75
    assert projection["failed_primary_runs"] == []
    assert projection["artifact_invalid_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert audit["family_prerequisites"] == {
        "family_run_count": 12,
        "planned_work_unit_count": 30,
        "completed_work_unit_count": 30,
        "all_optimal": True,
    }
    assert audit["global_artifact_sha256"] == GLOBAL_HASHES
    assert audit["stop_boundary"] == {
        "p2_started": False,
        "formal_seed_started": False,
    }

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs" / "handoffs" / "2026-08-09_phase6_e3_p2_repro_v4_pilots_audit.json"
SEEDS = {2026072001, 2026072002, 2026072003}
FINGERPRINTS = {
    "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
    "e3_component_sha256": "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e",
    "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
    "runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
RUN_HASHES = {
    "pilot_e3_repro_v4_p2_2026072001": {
        "result.json": "785ab94e0d24eee9fc92c67eb524a10ffba69782e63b40a7ca583b4e4ef20be0",
        "manifest.json": "ea037596a6603cd1c7509acf3d3d70a56a3851cf75258fed4b294bc2d8738333",
        "status_summary.json": "dce18294f0d0ee03c4bba3628f690a150c1928c06e376f1ababceffabf9aea87",
        "budget_comparison.csv": "ac065442f1fe83dcf3aee74d8274697a235c19d45f1bbeba0008722b10603ad2",
    },
    "pilot_e3_repro_v4_p2_2026072002": {
        "result.json": "a6e8f58cc3f2fc0e7738f9c3f8fc3655974a274290c8b5bf15b049dd0c534b52",
        "manifest.json": "0da12c5b64fc331946da91077f4cb1637a04494f8390f297c85ea44db3277a1f",
        "status_summary.json": "e8fe53e9af4ef49fce2301e384d09ce4ec4230016aa21d68812891153eb44809",
        "budget_comparison.csv": "6c2cca5674420c9039ca6c39b6a4dbfce54eba2f0ba2b3c14cff5cc9c5e2860c",
    },
    "pilot_e3_repro_v4_p2_2026072003": {
        "result.json": "bf4c8dc65314c244f1994f9f22990f37c09517ca838cab9922579c2afc78740c",
        "manifest.json": "f19583cba5903b33f4d47e7a17ee7eee5c10bc443100861c9dd58f8fa1812673",
        "status_summary.json": "06d6a4e3e5959e4e7570ab288e6e6f57ce94b9f9764354cfea6b04cb2f67ab8a",
        "budget_comparison.csv": "5a0b8de1b9c1ed26e4ff436b543fc9a07cb4f917cc5ed807a825c8e6f7848897",
    },
}
GLOBAL_HASHES = {
    "run_registry.csv": "3a46e655fbeca18f730f755c2d38a9ebdfc6946be4ef7a9ba9576535975a4fe9",
    "algorithm_performance.csv": "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3",
    "pilot_throughput_projection.json": "ca5bea5f4e2a5876d3a76cf4778f92439097ac0c9f9a16ba9b666eaa351f33eb",
    "family_run_registry.csv": "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9",
}


def test_phase6_e3_p2_repro_v4_audit_is_closed() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == source["merged_main_sha"] == "921b9e0866ce7d3856ff2275d4159f9702b5b942"
    assert source["execution_git_tree_sha"] == source["merged_main_tree_sha"] == "42b480ec855e8eb90bb33c09de47adcc33f63300"
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
        assert run["tier_id"] == "P2"
        assert run["execution_mode"] == "pilot"
        assert run["status"] == "optimal"
        assert run["parent_run_id"] is None
        assert run["planned_budget_count"] == run["completed_budget_count"] == 3
        assert run["algorithm_execution_count"] == 6
        assert run["fingerprints_match_approved"] is True
        assert run["disposal_fields"] == ["early_disposal", "expired_waste", "total_disposal"]
        assert run["artifact_sha256"] == RUN_HASHES[run["run_id"]]

    pairs = audit["budget_pairs"]
    assert len(pairs) == 9
    assert {(pair["seed"], pair["budget_factor"]) for pair in pairs} == {
        (seed, factor) for seed in SEEDS for factor in (0.9, 1.1, 1.3)
    }
    assert all(pair["cold_status"] == pair["warm_status"] == "optimal" for pair in pairs)
    assert all(pair["scenario_count"] == 1000 for pair in pairs)
    assert all(pair["cold_objective"] == pair["warm_objective"] for pair in pairs)
    assert all(pair["difference"] == 0.0 for pair in pairs)
    assert all(pair["cold_iterations"] > 0 and pair["warm_iterations"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["cold_seconds"]) and pair["cold_seconds"] > 0 for pair in pairs)
    assert all(math.isfinite(pair["warm_seconds"]) and pair["warm_seconds"] > 0 for pair in pairs)

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
    assert audit["numerical_consistency"]["max_cold_warm_objective_difference"] == 0.0
    assert audit["numerical_consistency"]["max_peak_memory_mb"] == 207.265625

    projection = audit["projection"]
    assert projection["completed_run_count"] == projection["required_run_count"] == 12
    assert projection["primary_completion_rate"] == 1.0
    assert projection["status"] == "projection_incomplete"
    assert projection["missing_runs"] == []
    assert projection["failed_primary_runs"] == []
    assert projection["artifact_invalid_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert projection["e3_projection"] == {
        "status": "projected",
        "estimated_recourse_lp_calls": 519000,
        "conservative_recourse_lp_solves_per_hour": 58516.74272579252,
        "projected_wall_hours": 8.86925648667795,
    }
    assert projection["family_projection_reaggregation_performed"] is False
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert audit["family_prerequisites"] == {
        "family_run_count": 12,
        "planned_work_unit_count": 30,
        "completed_work_unit_count": 30,
        "all_optimal": True,
    }
    assert audit["global_artifact_sha256"] == GLOBAL_HASHES

    terminal = audit["outer_terminal_observation"]
    assert terminal["run_id"] == "pilot_e3_repro_v4_p2_2026072003"
    assert terminal["terminal_wrapper_exit_code"] == 124
    assert terminal["scientific_result_already_finalized"] is True
    assert terminal["final_result_status"] == "optimal"
    assert terminal["runner_exception_present"] is False
    assert terminal["python_processes_after_inspection"] == 0
    assert audit["stop_boundary"] == {
        "final_family_projection_reaggregation_started": False,
        "formal_seed_started": False,
    }

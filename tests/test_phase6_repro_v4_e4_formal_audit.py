"""Validate the compact Phase 6 reproducibility-v4 E4 formal audit."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_repro_v4_e4_formal_audit.json"
)
TRAINING_SEEDS = list(range(2026072401, 2026072406))
TEST_SEEDS = list(range(2026082401, 2026082406))
BUDGETS = [
    1107.2893851278257,
    1353.3536929340091,
    1599.4180007401926,
]
POLICIES = [
    "deterministic_mean",
    "zero_reserve",
    "fixed_reserve_0_10",
    "fixed_reserve_0_30",
    "fixed_reserve_0_50",
    "endogenous_reserve",
]
EXPECTED_RUNS = {
    "formal_e4_repro_v4_v2_2026072401": (2026072401, 2026082401, "969815c3ff38fd08e6e110e84cc7090b461eb564fdffcbf219f5016faedf38fc", "46e26c63307e90b628e09fc4242cb530b826dc1af0197c406f1bf7ddabe2351f", "493ab266301391eaaf879e309fdc593a6c4bb4a1814780c876596eadfe31212c", "3d4e1fe3ede63e2a6462ee7d9153d3395b05bc6113e0c4dc0eea533c42e2241c", "979927008244a1a2ee0b43e6ade1cdd53462362021e27525c782d1a83bcaf914", "86f41c12703809bcc254fe04089def0c08fc33643cc0ccc9ecd4ad8d042a68d5"),
    "formal_e4_repro_v4_v2_2026072402": (2026072402, 2026082402, "469e6b2c76463e1b74013f727bbfa9502a6271db59a7d2ac3a756aacca74dff9", "c1d723b664c2b8dc8b048652bfd9e131dfd2c7ec1277bc32f5a60cfae751662c", "3347d10cf37d3ff7b2bae6c4bb5222b24f1b2a16dcb24c1994dff5200319dcdf", "522311fdc68df1a9bddf807b531ac2020553ebfe5c441ff65c7f69355660b39e", "113b8dc4f5546fd3a7c24d4a08d6af0bac2c89aa32cc6d5464bfd2e845b3961c", "c0e87bbbc06cb9365a10e3a4c03f3b81f76ee96df0d916f22d452336087507c5"),
    "formal_e4_repro_v4_v2_2026072403": (2026072403, 2026082403, "b2ef81e52cb588b4bd1d1aa1761ae0222f4e305b3005f98e1ac60a68bad90bf8", "9df7510768b52f0ec2651e4fe84e79291f842358edd6b09e2828b83cedc15467", "8271e996ca9e5fafa0887d79e835a4d7fdf989e86b84dbd2e26606a3907b9776", "1f05c25c0c3d03f3a6f51e96529030eb6aca0e724912c56cd0be7459c361bedf", "ab18fdaac819091a0ecd233273ac768fd3337aef6bde22b81f6f6c5c810eef6e", "9c46f4dfd0015c679c2ab1d8e95bfa4fcaa03232ce18223cb0f2c8bd04eeb46f"),
    "formal_e4_repro_v4_v2_2026072404": (2026072404, 2026082404, "f34192309357284f7bf740b049bf34a6cf60de7f3154f2e776810996d9d58bcc", "bac0633e73f43dd841d00e4c31d9a5981d3c2b80c3c72b42480be576c51e2e6d", "b5122fdfd40ae421b904a677d56daaca6942d0cd8877a81e35d304bf1588dbc6", "d57df0d170d51a70e8bff8ac573e2ef701ca609b6c47618f2799aca168c5f72d", "0d2e852067b657a49153943f5a38765a63c747ff49232b18e1b6fd859214a494", "9ca33d0468a671a0d9f716818a7a6c3d9ac47f7df5279b9157ee2ac384acd0f8"),
    "formal_e4_repro_v4_v2_2026072405": (2026072405, 2026082405, "e251f9e18f8aa89cbc0e2085093cbffd105f62dcfcef80b836b3a9a49ae98aab", "8155dac74d0c17f742b9534eca6f3ee7da09ab33fd1a3ad9af063eadcd904349", "871f5ec700029fab6c2f4cc47e02228d3b6a862d983cf75e07143b739b23150c", "f1aa07a1f37bb7a00ff86c65344ec2f7ec25996b89d974aa707d079d362f4a25", "3fd2a51d459765db2688f6a66b387d7c2aef6472a4640dc1775f4b112aafbcca", "a1859b60a4bca5aeb5a9a6e52d4591bafc10dd8366a7579e96d95f40c9313e18"),
}


def _canonical_sha256(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_repro_v4_e4_formal_audit_is_complete_and_consistent() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    source = audit["source"]
    assert source["execution_git_sha"] == source["merged_main_git_sha"] == "2161e4182c6e0cd80b54c385b54c5e20048aee7f"
    assert source["execution_git_tree_sha"] == source["merged_main_git_tree_sha"] == "7e5f15a3a2637b860d7dde9447d3dff13c8f1b11"
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False

    assert audit["fingerprints"] == {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "family_config_sha256": "983776a19e0a12937bc8a185b0fe5fdf76877d266445dcfce5f252d397a6ca8c",
        "family_component_sha256": "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
    }
    environment = audit["environment"]
    assert environment["python"] == "3.12.10"
    assert environment["gurobipy"] == environment["gurobi_optimizer"] == "13.0.2"
    assert environment["pyomo_interface"] == "gurobi_direct"
    assert environment["threads"] == 1
    assert environment["highs_fallback"] is False

    design = audit["design"]
    assert design["tier_id"] == "V2"
    assert design["training_seeds"] == TRAINING_SEEDS
    assert design["test_seeds"] == TEST_SEEDS
    assert design["budget_indices"] == [0, 1, 2]
    assert design["budgets"] == BUDGETS
    assert design["policies"] == POLICIES
    assert design["scenarios_per_plan"] == 2000
    assert design["test_set_reoptimization"] is False

    runs = {row["run_id"]: row for row in audit["runs"]}
    assert set(runs) == set(EXPECTED_RUNS)
    reconstructed_plan_count = 0
    for run_id, expected in EXPECTED_RUNS.items():
        train_seed, test_seed, result_hash, manifest_hash, status_hash, plan_hash, worker_hash, source_hash = expected
        row = runs[run_id]
        assert row["tier_id"] == "V2"
        assert row["training_seed"] == train_seed
        assert row["test_seed"] == test_seed
        assert row["execution_mode"] == "formal"
        assert row["status"] == "optimal"
        assert row["planned_work_units"] == row["completed_work_units"] == 18
        assert row["parent_run_id"] == ""
        assert row["result_sha256"] == result_hash
        assert row["manifest_sha256"] == manifest_hash
        assert row["status_summary_sha256"] == status_hash
        assert row["worker_hash_map_sha256"] == worker_hash
        assert row["source_e2_map_sha256"] == source_hash
        plan_ids = sorted(
            f"E4_V2_{train_seed}_{test_seed}_b{budget_index:02d}_{policy}"
            for budget_index in range(3)
            for policy in POLICIES
        )
        reconstructed_plan_count += len(plan_ids)
        assert _canonical_sha256(plan_ids) == plan_hash

    counts = audit["counts"]
    assert len(runs) == counts["primary_run_count"] == counts["optimal_primary_run_count"] == 5
    assert reconstructed_plan_count == counts["planned_work_unit_count"] == counts["completed_work_unit_count"] == 90
    assert counts["policy_count"] == 6
    assert counts["work_units_per_policy"] == 15
    assert counts["out_of_sample_scenario_evaluation_count"] == 90 * 2000 == 180000
    assert counts["optimal_scenario_evaluation_count"] == 180000
    for field in (
        "infeasible_scenario_count",
        "solver_failure_count",
        "failed_primary_run_count",
        "duplicate_primary_run_count",
        "parent_run_count",
        "diagnostic_attempt_count",
    ):
        assert counts[field] == 0

    summaries = audit["policy_summary_means"]
    assert set(summaries) == set(POLICIES)
    assert all(row["count"] == 15 for row in summaries.values())
    assert summaries["endogenous_reserve"] == summaries["zero_reserve"]

    paired_rows = []
    for training_seed, test_seed in zip(TRAINING_SEEDS, TEST_SEEDS, strict=True):
        for budget_index, budget in enumerate(BUDGETS):
            paired_rows.append(
                {
                    "training_seed": training_seed,
                    "test_seed": test_seed,
                    "budget_index": budget_index,
                    "budget": budget,
                    "mean_total_cost_difference": 0.0,
                    "total_cost_p95_difference": 0.0,
                    "total_cost_cvar95_difference": 0.0,
                    "service_level_difference": 0.0,
                    "shortage_probability_difference": 0.0,
                }
            )
    paired = audit["endogenous_vs_zero_reserve_paired_audit"]
    assert paired["comparison_group_count"] == len(paired_rows) == 15
    for field in (
        "mean_cost_match_count",
        "p95_match_count",
        "cvar95_match_count",
        "service_level_match_count",
        "shortage_probability_match_count",
    ):
        assert paired[field] == 15
    assert paired["max_abs_difference_across_locked_metrics"] == 0.0
    assert paired["paired_rows_sha256"] == _canonical_sha256(paired_rows) == "76bde8d04e8397a6a174185b426060224cabb5b6717d7bce772421bf25e78fcc"

    assert audit["inventory_exit_audit"] == {
        "max_abs_mean_total_disposal_minus_components": 0.0,
        "max_abs_mean_waste_alias_minus_total_disposal": 0.0,
    }
    assert audit["formal_primary_run_count_by_family_after_batch"] == {
        "E1": 14,
        "E2": 10,
        "E4": 5,
        "E5": 0,
    }
    assert audit["global_artifacts"] == {
        "family_run_registry_sha256": "59482cd3a4b786e45af7eb4e67ccaf77d2a735804a3919e3db4c34cbc0d97d5e",
        "algorithm_performance_sha256": "2486b070ee569bcc938cdb2468eb173d658353fd181c286bdaccf6216cb791c3",
        "pilot_throughput_projection_sha256": "c3b9c26e69a46aa89a99d7b6f40ff307c308c2782405e884154bc21c906faff2",
    }
    assert audit["authorization_after_batch"] == {
        "projection_status": "passed",
        "compute_gate_passed": True,
        "formal_execution_authorized": True,
    }
    assert audit["stop_boundary"] == {
        "e3_formal_started_in_batch": False,
        "e5_formal_started": False,
    }

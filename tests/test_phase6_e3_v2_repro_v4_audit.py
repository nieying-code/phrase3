from __future__ import annotations

import json
import statistics
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-09_phase6_e3_v2_repro_v4_pilots_audit.json"
)
EXPECTED_SOURCE_SHA = "e7fae479092cbaab35f4ac05fae3001b6b1b94a4"
EXPECTED_TREE_SHA = "5bb7715fb80a78783488a0f6b33eb00849c2902d"
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": (
        "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3"
    ),
    "runner_config_sha256": (
        "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd"
    ),
    "e3_component_sha256": (
        "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e"
    ),
    "family_component_sha256": (
        "92bbf40a3dbbb6c72f75f257d39197ee9c42f455daf6efecb4e8df710e065b5e"
    ),
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}
EXPECTED_BUDGETS = {
    0: (0.9, 1107.2893851278257),
    1: (1.1, 1353.3536929340091),
    2: (1.3, 1599.4180007401926),
}
EXPECTED_GLOBAL_HASHES = {
    "run_registry.csv": (
        "e7cf00da066262d050b2cefd83d1a09fcad2955576c96d78b53dce09c525917b"
    ),
    "algorithm_performance.csv": (
        "cfc0150c9f753c7ce110ae3ac35dc6d192a872512027d8b8998b82b5a4b71c4e"
    ),
    "pilot_throughput_projection.json": (
        "1aecd67d9ea9791b2e8fb80b668ee9397b19ce6821552b1e30342165e035189d"
    ),
    "family_run_registry.csv": (
        "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9"
    ),
}
EXPECTED_RUN_ARTIFACT_HASHES = {
    "pilot_e3_repro_v4_v2_2026072001": {
        "result.json": (
            "46cd8637ef5b610588b57af8a0463d6dcabd4b1800323b816277b01a1676d620"
        ),
        "manifest.json": (
            "c6952d7c370a1c3aef0aeac9ef3812938812e20d90e1d11a742d906091d549ac"
        ),
        "status_summary.json": (
            "fc11073224129052f3aff378a2b3a6eaafe33bb6d4f0f6a351a052ead4132d79"
        ),
    },
    "pilot_e3_repro_v4_v2_2026072002": {
        "result.json": (
            "1269d78f01e3d6a76ef507f6f2a0884eb66a993b92d8abe704795577f3f33e3c"
        ),
        "manifest.json": (
            "65f00fb441c2a4858d68e2c4bbebac07dbefc3bbd1cca5618c46cd90e5078c67"
        ),
        "status_summary.json": (
            "3652d2ef6dd6e452b642c38d0dd30388baf9b441b4d2388320689269d8904d28"
        ),
    },
    "pilot_e3_repro_v4_v2_2026072003": {
        "result.json": (
            "4028d55ca38bc471da36efe8f3fb51e544af071943edfd850cd25d4c85622037"
        ),
        "manifest.json": (
            "1cd01bba4b7503f408191d38208f8a3c384b8a33b4f97b0d57efc8153ef95e96"
        ),
        "status_summary.json": (
            "37b18384b2218f45fecd4a4faf7fef57cec97b30a4ad89c27f66bd6c95397830"
        ),
    },
}


def test_phase6_e3_v2_repro_v4_audit_is_closed() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    source = audit["source"]
    runs = audit["runs"]
    summary = audit["summary"]
    projection = audit["projection"]

    assert source == {
        "execution_git_sha": EXPECTED_SOURCE_SHA,
        "execution_git_tree_sha": EXPECTED_TREE_SHA,
        "merged_main_sha": EXPECTED_SOURCE_SHA,
        "merged_main_tree_sha": EXPECTED_TREE_SHA,
        "tree_equivalent": True,
        "tracked_modified_count_at_start": 0,
        "untracked_execution_input_count_at_start": 0,
        "working_tree_dirty": False,
    }
    assert audit["fingerprints"] == EXPECTED_FINGERPRINTS
    assert len(runs) == 3
    assert {run["seed"] for run in runs} == {
        2026072001,
        2026072002,
        2026072003,
    }

    pair_count = 0
    execution_count = 0
    group_count = 0
    state_transfer_count = 0
    max_within_group_spread = 0.0
    max_pair_difference = 0.0
    for run in runs:
        assert run["tier_id"] == "V2"
        assert run["execution_mode"] == "pilot"
        assert run["status"] == "optimal"
        assert run["parent_run_id"] is None
        assert run["completed_budget_count"] == run["planned_budget_count"] == 3
        assert run["fingerprints"] == {
            key: value
            for key, value in EXPECTED_FINGERPRINTS.items()
            if key != "family_component_sha256"
        }
        assert run["disposal_fields"] == [
            "early_disposal",
            "expired_waste",
            "total_disposal",
        ]
        assert {pair["budget_index"] for pair in run["budget_pairs"]} == {0, 1, 2}
        assert run["artifact_sha256"] == EXPECTED_RUN_ARTIFACT_HASHES[
            run["run_id"]
        ]
        for pair in run["budget_pairs"]:
            expected_factor, expected_budget = EXPECTED_BUDGETS[pair["budget_index"]]
            assert pair["budget_factor"] == expected_factor
            assert pair["budget"] == expected_budget
            assert pair["cold_statuses"] == ["optimal"] * 3
            assert pair["warm_statuses"] == ["optimal"] * 3
            assert len(pair["cold_objectives"]) == 3
            assert len(pair["warm_objectives"]) == 3
            assert len(pair["cold_seconds"]) == 3
            assert len(pair["warm_seconds"]) == 3
            assert all(seconds > 0.0 for seconds in pair["cold_seconds"])
            assert all(seconds > 0.0 for seconds in pair["warm_seconds"])
            cold_spread = max(pair["cold_objectives"]) - min(pair["cold_objectives"])
            warm_spread = max(pair["warm_objectives"]) - min(pair["warm_objectives"])
            max_within_group_spread = max(
                max_within_group_spread, cold_spread, warm_spread
            )
            cold_objective = statistics.median(pair["cold_objectives"])
            warm_objective = statistics.median(pair["warm_objectives"])
            assert pair["objective_difference"] == abs(
                cold_objective - warm_objective
            )
            max_pair_difference = max(
                max_pair_difference, pair["objective_difference"]
            )
            assert pair["transferred_from_previous_budget"] is (
                pair["budget_index"] > 0
            )
            state_transfer_count += int(pair["transferred_from_previous_budget"])
            pair_count += 1
            group_count += 2
            execution_count += 6

    assert audit["disposal_fields"] == [
        "early_disposal",
        "expired_waste",
        "total_disposal",
    ]
    assert pair_count == 9
    assert group_count == 18
    assert execution_count == 54
    assert state_transfer_count == 6
    assert max_within_group_spread == 0.0
    assert max_pair_difference == 0.0
    assert summary == {
        "primary_run_count": 3,
        "budget_pair_count": 9,
        "technical_repetition_group_count": 18,
        "algorithm_execution_count": 54,
        "adjacent_budget_state_transfer_count": 6,
        "all_optimal": True,
        "max_within_group_objective_spread": 0.0,
        "max_abs_cold_warm_objective_difference": 0.0,
        "failed_primary_count": 0,
        "duplicate_primary_count": 0,
        "diagnostic_parent_count": 0,
        "family_registry_run_count": 12,
    }

    expected_missing = {
        (tier, seed)
        for tier in ("P1", "P2")
        for seed in (2026072001, 2026072002, 2026072003)
    }
    actual_missing = {
        (row["tier_id"], row["seed"]) for row in projection["missing_runs"]
    }
    assert actual_missing == expected_missing
    assert projection["completed_run_count"] == 6
    assert projection["required_run_count"] == 12
    assert projection["completed_run_count"] + len(actual_missing) == 12
    assert projection["primary_completion_rate"] == 0.5
    assert projection["status"] == "insufficient_pilot_coverage"
    assert projection["failed_primary_runs"] == []
    assert projection["artifact_invalid_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert audit["global_artifact_sha256"] == EXPECTED_GLOBAL_HASHES
    assert audit["experiment_scope"] == {
        "v1_current_fingerprint_run_count": 3,
        "v2_current_fingerprint_run_count": 3,
        "p1_started": False,
        "p2_started": False,
        "formal_started": False,
    }

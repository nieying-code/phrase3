from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = (
    ROOT
    / "docs"
    / "handoffs"
    / "2026-08-09_phase6_e3_v1_repro_v4_pilots_audit.json"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
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
    "environment_sha256": (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    ),
}
EXPECTED_BUDGETS = {
    0: 1107.2893851278257,
    1: 1353.3536929340091,
    2: 1599.4180007401926,
}


def test_phase6_e3_v1_repro_v4_audit_is_closed() -> None:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    source = audit["source"]
    summary = audit["summary"]
    projection = audit["projection"]
    runs = audit["runs"]

    assert source["execution_git_sha"] == (
        "75ac9b852781e880c998dba0618a3f0b48195234"
    )
    assert source["merged_main_sha"] == (
        "1fa12bd9c3026ad202377d72fb79bfcd70c7c07e"
    )
    assert source["execution_git_tree_sha"] == (
        "e4f268fa170013f3d8bd52b3f71e5133c716571e"
    )
    assert source["merged_main_tree_sha"] == (
        "e4f268fa170013f3d8bd52b3f71e5133c716571e"
    )
    assert source["tree_equivalent"] is True
    assert source["tracked_modified_count_at_start"] == 0
    assert source["untracked_execution_input_count_at_start"] == 0
    assert source["working_tree_dirty"] is False

    assert len(runs) == 3
    assert {run["seed"] for run in runs} == {
        2026072001,
        2026072002,
        2026072003,
    }
    assert len({run["run_id"] for run in runs}) == 3
    for run in runs:
        assert run["tier_id"] == "V1"
        assert run["status"] == "optimal"
        assert run["execution_mode"] == "pilot"
        assert run["parent_run_id"] is None
        assert run["completed_budget_count"] == run["planned_budget_count"] == 3
        assert run["fingerprints"] == EXPECTED_FINGERPRINTS
        assert set(run["disposal_fields"]) == {
            "early_disposal",
            "expired_waste",
            "total_disposal",
        }
        assert {pair["budget_index"] for pair in run["budget_pairs"]} == {0, 1, 2}
        for pair in run["budget_pairs"]:
            assert pair["budget"] == EXPECTED_BUDGETS[pair["budget_index"]]
            assert pair["cold_status"] == pair["warm_status"] == "optimal"
            assert pair["cold_objective"] == pair["warm_objective"]
            assert pair["objective_difference"] == 0.0
        assert set(run["artifact_sha256"]) == {
            "result.json",
            "manifest.json",
            "status_summary.json",
        }
        assert all(
            SHA256.fullmatch(value)
            for value in run["artifact_sha256"].values()
        )

    assert summary == {
        "primary_run_count": 3,
        "budget_pair_count": 9,
        "algorithm_execution_count": 18,
        "all_optimal": True,
        "max_abs_objective_difference": 0.0,
        "failed_primary_count": 0,
        "duplicate_primary_count": 0,
        "diagnostic_parent_count": 0,
        "family_registry_run_count": 12,
    }
    expected_missing = {
        (tier, seed)
        for tier in ("V2", "P1", "P2")
        for seed in (2026072001, 2026072002, 2026072003)
    }
    actual_missing = {
        (row["tier_id"], row["seed"]) for row in projection["missing_runs"]
    }
    assert actual_missing == expected_missing
    assert projection["completed_run_count"] == 3
    assert projection["required_run_count"] == 12
    assert projection["completed_run_count"] + len(actual_missing) == (
        projection["required_run_count"]
    )
    assert projection["status"] == "insufficient_pilot_coverage"
    assert projection["compute_gate_passed"] is False
    assert projection["formal_execution_authorized"] is False
    assert projection["e3_component_sha256"] == EXPECTED_FINGERPRINTS[
        "e3_component_sha256"
    ]
    assert projection["failed_primary_runs"] == []
    assert projection["artifact_invalid_runs"] == []
    assert projection["duplicate_primary_runs"] == []
    assert projection["diagnostic_attempts"] == []
    assert audit["global_artifact_sha256"] == {
        "run_registry.csv": (
            "714baced90c731428669eb008585cfe03bcef6dc1debc321fc27eca3527e5601"
        ),
        "algorithm_performance.csv": (
            "998ca0634a040d104966d9d21d9d7b5209430c29af68884bd7ca4caedbd8ec08"
        ),
        "pilot_throughput_projection.json": (
            "06ca895fbd19394071630eccb0b589272303f5be6e1bef27176827d77b045078"
        ),
        "family_run_registry.csv": (
            "fc9051452d8eafbd7bcbc871f38936b7206554499db054b0c4596bc94e9958b9"
        ),
    }
    assert audit["experiment_scope"] == {
        "v2_started": False,
        "p1_started": False,
        "p2_started": False,
        "formal_started": False,
    }

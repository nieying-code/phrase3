from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_results_v1_1_audit.json"


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _load() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def test_exact_run_grid_and_artifact_mapping_are_locked() -> None:
    audit = _load()
    runs = audit["runs"]
    expected = {
        f"m2ap_pilot_v1_1_20260825_M2AP2_pilot_seed{seed}_profile{profile}":
        (f"M2AP2_pilot_seed{seed}_profile{profile}", seed, profile)
        for seed in (2026091001, 2026091002, 2026091003)
        for profile in ("C0", "T03")
    }
    assert {row["run_id"] for row in runs} == set(expected)
    for row in runs:
        case_id, seed, profile = expected[row["run_id"]]
        assert (row["case_id"], row["seed"], row["profile_id"]) == (case_id, seed, profile)
        assert row["tier_id"] == "M2AP2"
        assert row["execution_mode"] == "pilot"
        assert row["status"] == "optimal"
        assert row["planned_algorithm_solve_count"] == row["completed_algorithm_solve_count"] == 6
        for field in ("result_sha256", "manifest_sha256", "status_summary_sha256"):
            assert len(row[field]) == 64
    mapping = {
        row["run_id"]: {
            field: row[field]
            for field in (
                "case_id", "seed", "profile_id", "result_sha256",
                "manifest_sha256", "status_summary_sha256",
            )
        }
        for row in runs
    }
    assert _canonical_sha(mapping) == audit["global_artifacts"]["run_artifact_mapping_sha256"]
    assert audit["global_artifacts"]["run_artifact_mapping_sha256"] == (
        "d6e57f909be4a378e238a8d190ac5ce66d5cfd0fe4372498e8ed393056e4a851"
    )


def test_all_36_solves_have_complete_oracles_and_matching_objectives() -> None:
    audit = _load()
    solve_count = 0
    maximum_difference = 0.0
    maximum_ccg_seconds = 0.0
    maximum_rss = 0.0
    for row in audit["runs"]:
        assert len(row["comparisons"]) == 2
        for comparison in row["comparisons"]:
            index = comparison["budget_index"]
            assert comparison["execution_order"] == (
                ["extensive", "cold", "warm"] if index == 0
                else ["extensive", "warm", "cold"]
            )
            assert set(comparison["methods"]) == {"extensive", "cold", "warm"}
            objectives = []
            method_oracle_orders = []
            for name, method in comparison["methods"].items():
                solve_count += 1
                assert method["status"] == "optimal"
                assert method["exact_oracle_scenario_count"] == 50
                expected_order = [f"s{index:04d}" for index in range(50)]
                assert method["exact_oracle_scenario_keys"] == expected_order
                assert len(set(method["exact_oracle_scenario_keys"])) == 50
                oracle_order_sha = _canonical_sha(method["exact_oracle_scenario_keys"])
                assert method["exact_oracle_scenario_order_sha256"] == oracle_order_sha
                assert oracle_order_sha == method["component_set_sha256"]["scenario_order_sha256"]
                assert method["joint_scenario_set_sha256"] == comparison["joint_scenario_set_sha256"]
                assert method["component_set_sha256"] == comparison["component_set_sha256"]
                method_oracle_orders.append(method["exact_oracle_scenario_keys"])
                assert math.isfinite(method["objective"])
                assert math.isfinite(method["subprocess_wall_seconds"])
                assert method["subprocess_wall_seconds"] > 0.0
                assert math.isfinite(method["sampled_peak_RSS_MiB"])
                assert method["sampled_peak_RSS_MiB"] > 0.0
                objectives.append(method["objective"])
                maximum_rss = max(maximum_rss, method["sampled_peak_RSS_MiB"])
                if name in {"cold", "warm"}:
                    maximum_ccg_seconds = max(maximum_ccg_seconds, method["subprocess_wall_seconds"])
            assert method_oracle_orders[0] == method_oracle_orders[1] == method_oracle_orders[2]
            difference = max(objectives) - min(objectives)
            tolerance = 1.0e-5 + 1.0e-7 * max(1.0, *(abs(value) for value in objectives))
            assert difference <= tolerance
            assert comparison["maximum_objective_difference"] == difference
            maximum_difference = max(maximum_difference, difference)
    assert solve_count == 36
    aggregate = audit["aggregate"]
    assert aggregate["maximum_three_method_objective_difference"] == maximum_difference
    projection = aggregate["formal_compute_projection"]
    assert projection["conservative_seconds_per_execution"] == maximum_ccg_seconds
    assert projection["projected_wall_hours"] == 240 * maximum_ccg_seconds / 3600.0
    assert projection["maximum_sampled_peak_RSS_MiB"] == maximum_rss


def test_crn_and_cross_budget_transfer_are_reconstructed_from_run_evidence() -> None:
    audit = _load()
    by_seed_profile = {(row["seed"], row["profile_id"]): row for row in audit["runs"]}
    shared_fields = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256",
    )
    transferred = active_or_worst = 0
    for seed in (2026091001, 2026091002, 2026091003):
        c0 = by_seed_profile[(seed, "C0")]
        t03 = by_seed_profile[(seed, "T03")]
        for row in (c0, t03):
            first, second = row["comparisons"]
            assert first["joint_scenario_set_sha256"] == second["joint_scenario_set_sha256"]
            assert first["component_set_sha256"] == second["component_set_sha256"]
            assert first["transfer_input_state"] is None
            assert first["transfer_input_state_sha256"] is None
            assert first["transferred_state_sha256"] == _canonical_sha(first["transferred_state"])
            assert second["transfer_input_state"] == first["transferred_state"]
            assert second["transfer_input_state_sha256"] == first["transferred_state_sha256"]
            assert second["transferred_state_sha256"] == _canonical_sha(second["transferred_state"])
            warm = second["methods"]["warm"]
            assert warm["transfer_source_state_sha256"] == first["transferred_state_sha256"]
            assert warm["transfer_source_budget"] == first["budget"] == 2571.372016574617
            assert warm["initial_scenario_pool_size"] == len(warm["initial_scenarios"])
            reusable = set(first["transferred_state"]["active_scenarios"]) | set(
                first["transferred_state"]["historical_adversarial_scenarios"]
            )
            expected_transfer = [
                name for name in warm["initial_scenarios"] if name in reusable
            ]
            assert warm["transferred_exact_scenarios"] == expected_transfer
            assert warm["transferred_exact_scenario_count"] == len(warm["transferred_exact_scenarios"])
            assert warm["transferred_exact_scenario_count"] > 0
            assert warm["transferred_scenario_reuse_rate"] == len(expected_transfer) / len(warm["initial_scenarios"])
            assert set(warm["transferred_exact_scenario_costs"]) == set(expected_transfer)
            expected_active_or_worst = [
                name for name in expected_transfer
                if warm["exact_oracle_worst_cost"]
                - warm["transferred_exact_scenario_costs"][name] <= 1.0e-6
                or name == warm["worst_scenario"]
            ]
            assert warm["transferred_scenarios_becoming_active_or_worst"] == expected_active_or_worst
            assert warm["transferred_scenarios_becoming_active_or_worst_count"] == len(expected_active_or_worst)
            assert set(expected_active_or_worst).issubset(
                set(warm["active_scenarios_at_frozen_tolerance"]) | {warm["worst_scenario"]}
            )
            transferred += warm["transferred_exact_scenario_count"]
            active_or_worst += warm["transferred_scenarios_becoming_active_or_worst_count"]
        for budget_index in (0, 1):
            c0_components = c0["comparisons"][budget_index]["component_set_sha256"]
            t03_components = t03["comparisons"][budget_index]["component_set_sha256"]
            assert all(c0_components[field] == t03_components[field] for field in shared_fields)
            assert c0_components["fulfillment_sha256"] != t03_components["fulfillment_sha256"]
    assert transferred == audit["aggregate"]["total_transferred_exact_scenario_count"] == 10
    assert active_or_worst == audit["aggregate"]["total_transferred_scenarios_becoming_active_or_worst_count"] == 10


def test_gate_counts_execution_identity_and_stop_boundary_are_closed() -> None:
    audit = _load()
    assert audit["status"] == "passed"
    assert audit["execution_identity"] == {
        "branch": "main",
        "upstream_remote": "origin",
        "upstream_merge": "refs/heads/main",
        "head": "769dafca0fddf13f3d28287a815a6bca0807454b",
        "remote_main": "769dafca0fddf13f3d28287a815a6bca0807454b",
        "tree": "6bcb55edc6db5fa979ea903786c84b9e6d92a8ea",
        "reviewed_runner_merge_commit": "03978b0efce768672233079ea23364c6ca632418",
    }
    aggregate = audit["aggregate"]
    assert aggregate["required_primary_sequence_count"] == aggregate["completed_primary_sequence_count"] == 6
    assert aggregate["required_budget_pair_count"] == aggregate["completed_budget_pair_count"] == 12
    assert aggregate["required_algorithm_solve_count"] == aggregate["completed_algorithm_solve_count"] == 36
    for field in (
        "missing_case_ids", "duplicate_case_ids", "failed_primary_run_ids",
        "invalid_primary_runs", "diagnostic_run_ids", "common_random_number_mismatches",
    ):
        assert aggregate[field] == []
    assert aggregate["pilot_compute_gate_passed"] is True
    assert aggregate["formal_authorized"] is False
    assert all(value == 0 for value in audit["execution_boundaries"].values())

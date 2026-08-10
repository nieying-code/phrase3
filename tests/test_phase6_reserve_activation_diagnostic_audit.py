"""Validate the compact reserve-activation diagnostic audit."""

from __future__ import annotations

import json
from pathlib import Path


AUDIT = Path(
    "docs/handoffs/2026-08-10_phase6_reserve_activation_diagnostic_audit.json"
)


def test_reserve_activation_diagnostic_audit_closes_the_mechanism_claims() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["status"] == "complete"
    assert audit["scope"] == "exploratory_mechanism_diagnostic_only"
    assert audit["formal_evidence"] is False
    assert audit["replaces_frozen_e5"] is False

    execution = audit["execution"]
    assert execution["successful_attempt_commit"] == (
        "dbc0dc88c201cf4e1a625d7943269a96b486b817"
    )
    assert execution["successful_attempt_tree"] == (
        "2aec4de34c3d20854f0783ac088a93d5180a5092"
    )
    assert execution["merged_pr37_commit"] == (
        "595ed0025be82beb7b7283faca6f53282fa8ab22"
    )
    assert execution["merged_pr37_tree"] == execution["local_parent_tree"] == (
        "b3ce557e953c39f162f0abbc6e1af935f2359990"
    )
    assert execution["merged_main_and_local_parent_tree_equal"] is True
    assert execution["tracked_worktree_dirty"] is False
    assert execution["result_size_bytes"] == 35079
    assert execution["result_sha256"] == (
        "e203da869e09959d36ba5b3d40f9f1f004980084479d76ea277549e7a03d4b1d"
    )
    assert execution["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )

    failed = audit["failed_attempt"]
    assert failed["status"] == "runner_extraction_error"
    assert failed["final_result_file_created"] is False
    assert failed["gurobi_or_model_failure"] is False
    assert failed["same_output_path_reused"] is False

    design = audit["design"]
    assert design["tier_id"] == "V1"
    assert design["seed"] == 20260723
    assert design["items"] == 1
    assert design["periods"] == 6
    assert design["training_scenarios"] == 50
    assert design["budget_factor"] == 1.1
    assert design["reserve_frontier_ratios"] == [
        0.0,
        0.0025,
        0.005,
        0.01,
        0.02,
        0.05,
        0.1,
    ]
    assert design["emergency_price_scales"] == [1.0, 0.9, 0.75, 0.5]
    assert design["waste_penalty_multipliers"] == [1.0, 4.0, 16.0, 64.0]

    frontier = audit["reserve_frontier"]
    assert [row["reserve_ratio"] for row in frontier] == design[
        "reserve_frontier_ratios"
    ]
    baseline_objective = frontier[0]["objective"]
    assert baseline_objective == audit["baseline"]["objective"]
    assert audit["baseline"]["reserve"] == 0.0
    assert audit["baseline"]["maximum_emergency_purchase"] == 0.0
    for row in frontier:
        assert row["delta_from_zero"] == row["objective"] - baseline_objective
    assert all(
        frontier[index]["objective"] < frontier[index + 1]["objective"]
        for index in range(len(frontier) - 1)
    )

    surface = audit["mechanism_surface_by_price_scale"]
    assert set(surface) == {"1.0", "0.9", "0.75", "0.5"}
    assert surface["1.0"]["reserve_ratio"] == 0.0
    assert surface["0.9"]["reserve_ratio"] == 0.0
    assert surface["0.75"]["reserve_ratio"] == 0.13283467769592186
    assert surface["0.5"]["reserve_ratio"] == 0.604093845219933
    assert all(row["waste_multiplier_count"] == 4 for row in surface.values())
    assert audit["waste_penalty_result"][
        "objective_and_reserve_invariant_within_each_price_scale"
    ] is True

    attribution = audit["markup_attribution"]
    assert attribution["baseline_objective"] == baseline_objective
    for key, expected_delta in (
        ("markup_0.15", -1899.5000074549862),
        ("markup_0.55", 1899.5000074549753),
    ):
        row = attribution[key]
        assert row["pure_price_delta"] == 0.0
        assert row["pure_price_fixed_shortage_penalty_objective"] == (
            baseline_objective
        )
        assert row["coupled_delta"] == expected_delta
        assert row["reserve"] == 0.0
        assert row["maximum_emergency_purchase"] == 0.0

    diagnosis = audit["diagnosis"]
    assert diagnosis["coarse_fixed_reserve_grid_is_root_cause"] is False
    assert diagnosis["solver_or_reserve_variable_failure_is_root_cause"] is False
    assert diagnosis["pure_emergency_markup_effect_under_zero_reserve"] is False
    assert diagnosis["current_relative_price_calibration_is_decisive"] is True
    assert diagnosis[
        "model_can_activate_positive_reserve_in_prespecified_positive_control"
    ] is True
    assert diagnosis["positive_control_is_empirical_evidence"] is False

    assert audit["recommended_paper_route"]["route"] == (
        "preserve_frozen_model_and_report_zero_reserve_boundary"
    )
    assert audit["stop_boundary"] == {
        "e3_formal_started": False,
        "frozen_matrix_modified": False,
        "formal_results_overwritten": False,
    }


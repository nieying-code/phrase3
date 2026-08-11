"""Validate the compact reserve-activation diagnostic audit."""

from __future__ import annotations

import json
from itertools import product
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
    assert failed["execution_commit"] == (
        "d701342fd632310f79f5aaae7af5f69fe3f88c17"
    )
    assert failed["execution_tree"] == (
        "ba33e3c528098c3b724f077e696fb9d4a1dbfbc0"
    )
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

    cases = audit["mechanism_surface_cases"]
    expected_pairs = set(
        product(
            design["emergency_price_scales"],
            design["waste_penalty_multipliers"],
        )
    )
    rows_by_pair = {
        (row["emergency_price_scale"], row["waste_penalty_multiplier"]): row
        for row in cases
    }
    assert len(cases) == len(rows_by_pair) == 16
    assert set(rows_by_pair) == expected_pairs

    expected_by_price = {
        1.0: {
            "reserve": 0.0,
            "reserve_ratio": 0.0,
            "objective": 18448.853760028822,
            "regular_purchase_sha256": (
                "70bd22a49ad97aa001120904dc683769c88fd4cd29ecfd7d3b4bd279e5460761"
            ),
            "maximum_total_emergency_purchase": 0.0,
        },
        0.9: {
            "reserve": 0.0,
            "reserve_ratio": 0.0,
            "objective": 18448.853760028822,
            "regular_purchase_sha256": (
                "70bd22a49ad97aa001120904dc683769c88fd4cd29ecfd7d3b4bd279e5460761"
            ),
            "maximum_total_emergency_purchase": 0.0,
        },
        0.75: {
            "reserve": 179.7723016094747,
            "reserve_ratio": 0.13283467769592186,
            "objective": 18052.43504004278,
            "regular_purchase_sha256": (
                "16d9f77ed8bcf480eb400752168db6f21fbfa45bb1bed20cf16a5a85b6ba5c53"
            ),
            "maximum_total_emergency_purchase": 101.54192792748943,
        },
        0.5: {
            "reserve": 817.5526363071021,
            "reserve_ratio": 0.604093845219933,
            "objective": 11250.88067547729,
            "regular_purchase_sha256": (
                "3bb09ab6d58f7b21b5c9280d45a1f11443ee20374af3e99f6f0923f7c098e68e"
            ),
            "maximum_total_emergency_purchase": 562.2041649679923,
        },
    }
    expected_data_hashes = {
        (1.0, 1.0): "82a8bba99379ed27181057ce3c7a274ae57f5a4cf0b763d5476cc958c1a18dfb",
        (1.0, 4.0): "00d2c163fe2665c7d3bcb87874c5bb8cb8f38de07f058f265baffb10be0f1390",
        (1.0, 16.0): "0c33e07df369bb6d9030e68190743cba2de7e440a9e6aea8077c3ec878b44e63",
        (1.0, 64.0): "1930142dbba244f281692b515b0c6df153f57bd4db47353a3b7d43e4f0e56292",
        (0.9, 1.0): "03b7444913028ca54d2695318b6eb21dc03ca861faea2a1c7a877494ceea6ea3",
        (0.9, 4.0): "2ec265560c2b120dd970015eaa06ee0425b7ea7e9387e604a3fe647aa626c83b",
        (0.9, 16.0): "7f7a0ba62f50cfbcd087b3cc01386e2e2f7ce030287e3704cae9da1039f7a128",
        (0.9, 64.0): "dc4a09a3f217414fc0452e708e3775ddf56e03e9c7572b6a09b2e301dd3a4263",
        (0.75, 1.0): "4f2a118cd2aadf10b73db3a1d0910e1b39198ebf777850520e9d409622da40fe",
        (0.75, 4.0): "7824c4fe6de6f851f8a115e25653babab20ba0972de2e047ad1b381ec7cfbddd",
        (0.75, 16.0): "f0d36a449dbf359f11b31e96a5efd04e35402f0a715d7adb542bbe2537b77db4",
        (0.75, 64.0): "84e7c852f5f2b17d86972fbbfe153f6f9eefa7309a6f621ae6e157e7cf801c76",
        (0.5, 1.0): "d48c9ffaf312776f32839a6d87dc9d7f826b99f0961812842d984d1fb9f63fd1",
        (0.5, 4.0): "d0797c0d248d4bb51c1249a1144db24768a42ec53f7e12a79a998d918bdb6406",
        (0.5, 16.0): "c0fa11f005319430e0679ecc2e65286971756263cde6f5ac163fc3388191ce81",
        (0.5, 64.0): "03edc561e56835381a0b533a2acb4fab37210bed587c808e574453b76fd1e9ad",
    }
    expected_consistency = {
        (price, multiplier): (
            0.0
            if price == 0.75 and multiplier in {16.0, 64.0}
            else 1.8189894035458565e-12
            if price == 0.5
            else 3.637978807091713e-12
        )
        for price, multiplier in expected_pairs
    }
    for pair, row in rows_by_pair.items():
        price, multiplier = pair
        assert row["case_id"] == (
            f"price_scale_{price:g}__waste_multiplier_{multiplier:g}"
        )
        assert row["status"] == "optimal"
        assert row["data_sha256"] == expected_data_hashes[pair]
        assert row["consistency_difference"] == expected_consistency[pair]
        for field, expected in expected_by_price[price].items():
            assert row[field] == expected

    assert audit["waste_penalty_result"][
        "objective_and_reserve_invariant_within_each_price_scale"
    ] is True
    assert audit["waste_penalty_result"][
        "waste_penalty_is_decision_relevant_in_tested_grid"
    ] is False
    assert audit["waste_penalty_result"][
        "worst_case_disposal_channel_directly_verified"
    ] is False

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
    assert diagnosis["waste_penalty_is_decision_relevant_in_tested_grid"] is False
    assert diagnosis["worst_case_disposal_channel_directly_verified"] is False
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

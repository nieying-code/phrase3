from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import re
import statistics

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
AUDIT = ROOT / "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
SHA256 = re.compile(r"[0-9a-f]{64}")
EXPECTED_FINGERPRINTS = {
    "scientific_config_sha256": "02d50abd609acd9d93eca6b13f6195e6eee14330e3db5c5ca75e83d2e7b56612",
    "e3_component_sha256": "87f643fd3bf90f825251641c1bdeeb25f4aebb1ea23d052913b27e0b5fdf2924",
    "family_component_sha256": "b1f9278ee8a0085e80c418f33d04c92b943c215eaf9ca2cdb6144e8dcebdb68b",
    "runner_config_sha256": "c8d9efb59649b2a3e16839cdece7c38bc5a385358c354b72310c32134f49ad8e",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
EXPECTED_GROUP_COUNTS = {
    (1.1, "C0"): (0, 0, 0),
    (1.1, "C1"): (0, 0, 0),
    (1.1, "T03"): (6, 5, 6),
    (1.3, "C0"): (0, 0, 0),
    (1.3, "T03"): (10, 10, 7),
}

PRIMARY_CONTRASTS = (
    ("beta_1_1_T03_minus_C0_robust_autonomous_reserve_ratio", "C0"),
    ("beta_1_1_T03_minus_C1_robust_autonomous_reserve_ratio", "C1"),
)


def canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_audit() -> dict:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def _average_ranks(values: list[float]) -> list[float]:
    order = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    start = 0
    while start < len(order):
        end = start + 1
        while end < len(order) and values[order[end]] == values[order[start]]:
            end += 1
        average = (start + 1 + end) / 2.0
        for position in range(start, end):
            ranks[order[position]] = average
        start = end
    return ranks


def _wilcoxon_pratt_approx(differences: list[float]) -> dict[str, float]:
    absolute = [abs(value) for value in differences]
    ranks = _average_ranks(absolute)
    positive = sum(rank for rank, value in zip(ranks, differences) if value > 0)
    negative = sum(rank for rank, value in zip(ranks, differences) if value < 0)
    count = len(differences)
    zero_count = sum(value == 0 for value in differences)
    null_mean = count * (count + 1) / 4.0 - zero_count * (zero_count + 1) / 4.0
    variance_numerator = (
        count * (count + 1) * (2 * count + 1)
        - zero_count * (zero_count + 1) * (2 * zero_count + 1)
    )
    nonzero_tie_counts = {
        value: absolute.count(value) for value in set(absolute) if value != 0
    }
    tie_correction = sum(size**3 - size for size in nonzero_tie_counts.values())
    standard_error = math.sqrt((variance_numerator - tie_correction / 2.0) / 24.0)
    z_statistic = (positive - null_mean) / standard_error
    return {
        "statistic": min(positive, negative),
        "z_statistic": z_statistic,
        "raw_two_sided_p_value": math.erfc(abs(z_statistic) / math.sqrt(2.0)),
        "positive_rank_sum": positive,
        "negative_rank_sum": negative,
        "null_mean": null_mean,
        "standard_error": standard_error,
    }


def test_formal_mechanism_run_identity_and_artifact_mapping_are_exact():
    audit = load_audit()
    runs = audit["runs"]
    expected_cases = {
        (seed, beta, profile)
        for seed in range(2026081401, 2026081411)
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    }
    assert len(runs) == 50
    assert {(row["seed"], row["beta"], row["profile_id"]) for row in runs} == expected_cases
    assert len({row["run_id"] for row in runs}) == len({row["case_id"] for row in runs}) == 50
    for row in runs:
        assert row["run_id"] == f"formal_m2_v1_1_20260821_{row['case_id']}"
        assert row["tier_id"] == "M2F2"
        assert row["status"] == "optimal"
        assert row["parent_run_id"] is None
        assert row["git_sha"] == "a761e1f5c1c2049ddcba0a91e16d0c9e1fd1a70c"
        assert row["git_tree_sha"] == "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69"
        assert row["fingerprints"] == EXPECTED_FINGERPRINTS
        assert row["formal_orchestrator_sha256"] == (
            "a09fd3a71bc04ac748fb85c6acbcec2a387a3e589ba9cdd23c7753090c2322f1"
        )
        assert set(row["artifacts"]) == {
            "result_sha256", "manifest_sha256", "checkpoint_sha256",
            "status_summary_sha256", "heartbeat_sha256",
        }
        assert all(SHA256.fullmatch(value) for value in row["artifacts"].values())
    mapping = {row["run_id"]: row["artifacts"] for row in runs}
    assert canonical_sha256(mapping) == audit["run_artifact_mapping_sha256"] == (
        "e63e0db7269b2a252d11f9879f9477520a0777b9689c9d07f4f81545ff1037fe"
    )
    science_mapping = {row["run_id"]: row["science"] for row in runs}
    assert canonical_sha256(science_mapping) == audit["science_evidence_mapping_sha256"] == (
        "144709109d02812ea86bbf8b1600cea0df9403f8464cf9d94c97d98b890e03f8"
    )


def test_reserve_activation_endpoints_and_fixed_policies_recompute():
    runs = load_audit()["runs"]
    for row in runs:
        science = row["science"]
        budget = science["budget"]
        assert math.isclose(budget, row["beta"] * science["reference_budget"], abs_tol=1e-9)
        reserve = max(0.0, science["R_min_opt"] - science["R_min_feas"])
        ratio = reserve / budget
        assert math.isclose(reserve, science["R_disc_robust"], abs_tol=1e-9)
        assert math.isclose(ratio, science["R_disc_robust_ratio"], abs_tol=1e-12)
        assert science["numerical_activation"] is (ratio > 1e-4)
        assert science["substantive_activation"] is (ratio >= 0.01)
        assert science["moderate_activation"] is (
            science["substantive_activation"] and 0.05 <= ratio <= 0.50
        )
        assert science["minimum_endpoint_status"] == science["maximum_endpoint_status"] == "optimal"
        for field in (
            "minimum_endpoint_consistency_difference",
            "maximum_endpoint_consistency_difference",
        ):
            difference = science[field]
            assert math.isfinite(difference) and difference >= 0
            assert difference <= science["objective_tolerance"] + 1e-8
        for endpoint in science["endpoint_failure_counts"].values():
            assert endpoint == {"infeasible": 0, "solver_failure": 0, "missing": 0}
        assert science["training_scenario_count"] == science["scenario_identity_count"] == 100
        assert science["solver"] == "gurobi_direct"
        assert science["gurobipy_version"] == "13.0.2"
        assert science["gurobi_optimizer_version"] == "13.0.2"
        assert science["threads"] == 1
        policies = science["fixed_reserve_policies"]
        assert [item["rho"] for item in policies] == [0.0, 0.1, 0.3, 0.5]
        for policy in policies:
            expected = science["R_min_feas"] + policy["rho"] * (
                budget - science["R_min_feas"]
            )
            assert math.isclose(policy["reserve"], expected, abs_tol=1e-9)
            assert policy["status"] == "optimal"
            assert policy["regular_purchase_reoptimized"] is True


def test_c0_crn_plan_identity_and_cross_item_evidence_are_bounded():
    runs = load_audit()["runs"]
    crn_fields = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256",
    )
    for seed in range(2026081401, 2026081411):
        selected = [row for row in runs if row["seed"] == seed]
        for field in crn_fields:
            assert len({row["science"]["scenario_component_set_sha256"][field] for row in selected}) == 1
    for row in runs:
        science = row["science"]
        cross = science["cross_item_allocation"]
        assert cross["plan_source"] == "complete_extensive_model_R_min_opt_endpoint"
        assert math.isclose(cross["endpoint_reserve"], science["R_min_opt"], abs_tol=1e-9)
        assert cross["endpoint_regular_purchase_sha256"] == science["minimum_endpoint_regular_purchase_sha256"]
        assert math.isclose(cross["endpoint_exact_objective"], science["minimum_endpoint_exact_objective"], abs_tol=1e-8)
        assert cross["scenario_count"] == 100
        assert SHA256.fullmatch(cross["scenario_item_emergency_spend_sha256"])
        recomputed_gate = (
            cross["positive_total_emergency_spend_scenario_count"] >= 2
            and cross["both_items_each_positive_in_at_least_one_scenario"]
            and cross["item1_emergency_spend_share_range"] >= 1e-4
        )
        assert cross["gate_passed"] is recomputed_gate
        if row["profile_id"] == "C0":
            c0 = science["c0_equivalence"]
            assert c0["required"] is True and c0["status"] == "passed"
            assert c0["fulfillment_exactly_one"] is True
            assert c0["scenario_count_each_direction"] == 100
        if row["beta"] == 1.1 and row["profile_id"] == "T03":
            plans = science["first_stage_plan_identities"]
            assert set(plans) == {
                "endogenous_reserve", "zero_autonomous_reserve",
                "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
                "fixed_autonomous_reserve_0_50",
            }
            assert plans["endogenous_reserve"]["reserve_amount"] == science["R_min_opt"]
            assert plans["zero_autonomous_reserve"]["reserve_amount"] == science["R_min_feas"]
            assert all(SHA256.fullmatch(item["finalized_plan_artifact_sha256"]) for item in plans.values())
        else:
            assert science["first_stage_plan_identities"] is None


def test_frozen_primary_mechanism_statistics_recompute_from_ten_seed_pairs():
    audit = load_audit()
    analysis = audit["mechanism_statistical_analysis"]
    runs = {
        (row["seed"], row["beta"], row["profile_id"]): row
        for row in audit["runs"]
    }
    seeds = list(range(2026081401, 2026081411))
    assert analysis["status"] == "complete"
    assert analysis["independent_unit"] == "formal_training_seed"
    assert analysis["primary_outcome"] == "R_disc_robust_ratio"
    assert analysis["paired_difference_direction"] == "T03_minus_comparator"
    assert analysis["primary_beta"] == 1.1
    assert analysis["bootstrap"] == {
        "method": "paired_cluster_percentile",
        "cluster_unit": "formal_training_seed",
        "random_seed": 2026081499,
        "resamples": 10000,
        "confidence_level": 0.95,
        "point_estimator": "arithmetic_mean_of_ten_seed_level_paired_differences",
        "implementation": "numpy.random.Generator(numpy.random.PCG64(seed))",
        "numpy_version": "2.5.1",
        "index_sampling": "Generator.integers(0,10,size=(10000,10),endpoint=False)",
        "percentile_implementation": "numpy.percentile(method=linear)",
        "percentile_bounds": [2.5, 97.5],
    }
    assert analysis["wilcoxon_protocol"] == {
        "test": "paired_two_sided_signed_rank",
        "zero_method": "pratt",
        "method": "approx",
        "continuity_correction": False,
        "all_zero_differences_rule": "statistic_zero_p_value_one",
        "implementation": "project_audit_pratt_normal_approximation_v1",
        "normal_tail_implementation": "math.erfc(abs(z)/sqrt(2))",
    }
    assert analysis["multiple_testing"] == {
        "method": "holm",
        "family_size": 2,
        "familywise_alpha": 0.05,
        "tie_order": "contrast_declaration_order",
        "adjusted_p_value_rule": (
            "cumulative_max_of_(family_size-rank+1)*raw_p_capped_at_one"
        ),
    }

    raw_p_values = []
    for observed, (contrast_id, comparator) in zip(
        analysis["primary_contrasts"], PRIMARY_CONTRASTS, strict=True
    ):
        expected_pairs = []
        differences = []
        for seed in seeds:
            treatment = runs[(seed, 1.1, "T03")]["science"]["R_disc_robust_ratio"]
            baseline = runs[(seed, 1.1, comparator)]["science"]["R_disc_robust_ratio"]
            difference = treatment - baseline
            differences.append(difference)
            expected_pairs.append({
                "seed": seed,
                "treatment_profile": "T03",
                "comparator_profile": comparator,
                "treatment_R_disc_robust_ratio": treatment,
                "comparator_R_disc_robust_ratio": baseline,
                "paired_difference": difference,
            })
        assert observed["contrast_id"] == contrast_id
        assert observed["paired_seed_count"] == 10
        assert observed["paired_seed_differences"] == expected_pairs
        assert math.isclose(
            observed["arithmetic_mean_effect"], statistics.mean(differences), abs_tol=1e-15
        )
        assert math.isclose(
            observed["descriptive_median_effect"], statistics.median(differences), abs_tol=1e-15
        )
        generator = np.random.Generator(np.random.PCG64(2026081499))
        values = np.asarray(differences, dtype=float)
        bootstrap_means = values[
            generator.integers(0, 10, size=(10000, 10), endpoint=False)
        ].mean(axis=1)
        expected_ci = np.percentile(
            bootstrap_means, [2.5, 97.5], method="linear"
        ).tolist()
        assert np.allclose(observed["bootstrap_percentile_95_ci"], expected_ci, atol=1e-15)
        expected_wilcoxon = _wilcoxon_pratt_approx(differences)
        for field, value in expected_wilcoxon.items():
            assert math.isclose(observed["wilcoxon"][field], value, abs_tol=1e-15)
        raw_p_values.append(expected_wilcoxon["raw_two_sided_p_value"])

    order = sorted(range(2), key=lambda index: (raw_p_values[index], index))
    adjusted = [None, None]
    running_maximum = 0.0
    for rank, index in enumerate(order, start=1):
        running_maximum = max(
            running_maximum, min(1.0, (3 - rank) * raw_p_values[index])
        )
        adjusted[index] = running_maximum
        observed = analysis["primary_contrasts"][index]["wilcoxon"]
        assert observed["holm_rank"] == rank
        assert math.isclose(observed["holm_adjusted_p_value"], adjusted[index], abs_tol=1e-15)
        assert observed["holm_reject_at_familywise_alpha_0_05"] is (
            adjusted[index] <= 0.05
        )


def test_secondary_mechanism_results_are_descriptive_and_not_cross_budget_effects():
    audit = load_audit()
    analysis = audit["mechanism_statistical_analysis"]
    secondary = analysis["secondary_descriptive_unadjusted"]
    runs = {
        (row["seed"], row["beta"], row["profile_id"]): row
        for row in audit["runs"]
    }
    seeds = list(range(2026081401, 2026081411))
    assert secondary["inferential_status"] == (
        "descriptive_unadjusted_no_cross_beta_effect_estimation"
    )
    assert secondary["cross_budget_effect_claim_permitted"] is False
    beta_1_3 = secondary[
        "beta_1_3_T03_minus_C0_robust_autonomous_reserve_ratio"
    ]
    expected_differences = [
        {
            "seed": seed,
            "paired_difference": (
                runs[(seed, 1.3, "T03")]["science"]["R_disc_robust_ratio"]
                - runs[(seed, 1.3, "C0")]["science"]["R_disc_robust_ratio"]
            ),
        }
        for seed in seeds
    ]
    assert beta_1_3["paired_seed_differences"] == expected_differences
    values = [row["paired_difference"] for row in expected_differences]
    assert math.isclose(beta_1_3["arithmetic_mean_effect"], statistics.mean(values), abs_tol=1e-15)
    assert math.isclose(beta_1_3["descriptive_median_effect"], statistics.median(values), abs_tol=1e-15)
    assert beta_1_3["substantive_activation_count_T03"] == 10

    cross = secondary["beta_1_1_T03_cross_item_allocation_share_range"]
    expected_cross = [
        {
            "seed": seed,
            "item1_emergency_spend_share_range": runs[(seed, 1.1, "T03")][
                "science"
            ]["cross_item_allocation"]["item1_emergency_spend_share_range"],
            "gate_passed": runs[(seed, 1.1, "T03")]["science"][
                "cross_item_allocation"
            ]["gate_passed"],
        }
        for seed in seeds
    ]
    assert cross["seed_level_values"] == expected_cross
    assert cross["gate_passed_count"] == sum(row["gate_passed"] for row in expected_cross)


def test_group_summaries_progress_and_stop_boundary_recompute():
    audit = load_audit()
    runs = audit["runs"]
    recomputed = []
    for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03"))):
        for profile in profiles:
            selected = [row for row in runs if row["beta"] == beta and row["profile_id"] == profile]
            ratios = [row["science"]["R_disc_robust_ratio"] for row in selected]
            row = {
                "beta": beta,
                "profile_id": profile,
                "run_count": len(selected),
                "numerical_activation_count": sum(item["science"]["numerical_activation"] for item in selected),
                "substantive_activation_count": sum(item["science"]["substantive_activation"] for item in selected),
                "moderate_activation_count": sum(item["science"]["moderate_activation"] for item in selected),
                "R_disc_robust_ratio_min": min(ratios),
                "R_disc_robust_ratio_median": statistics.median(ratios),
                "R_disc_robust_ratio_max": max(ratios),
                "cross_item_allocation_gate_count": sum(item["science"]["cross_item_allocation"]["gate_passed"] for item in selected),
            }
            recomputed.append(row)
            assert (
                row["substantive_activation_count"],
                row["moderate_activation_count"],
                row["cross_item_allocation_gate_count"],
            ) == EXPECTED_GROUP_COUNTS[(beta, profile)]
    assert recomputed == audit["group_summaries"]
    aggregate = audit["aggregate"]
    assert aggregate["completed_primary_run_count"] == aggregate["optimal_primary_run_count"] == 50
    assert aggregate["minimum_endpoint_exact_recourse_evaluation_count"] == 5000
    assert aggregate["maximum_endpoint_exact_recourse_evaluation_count"] == 5000
    assert aggregate["fixed_policy_optimization_count"] == 200
    assert math.isclose(aggregate["total_wall_seconds"], sum(row["wall_seconds"] for row in runs), abs_tol=1e-9)
    assert aggregate["max_peak_memory_mb"] == max(row["peak_memory_mb"] for row in runs)
    assert aggregate["max_R_disc_robust_ratio"] == max(row["science"]["R_disc_robust_ratio"] for row in runs)
    progress = audit["progress"]
    assert progress["status"] == "complete"
    assert progress["required_primary_run_count"] == progress["completed_primary_run_count"] == 50
    for field in (
        "missing_case_ids", "invalid_primary_run_ids", "failed_primary_run_ids",
        "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids",
    ):
        assert progress[field] == []
    assert progress["common_random_numbers_verified"] is True
    assert progress["formal_mechanism_gate_passed"] is True
    assert progress["next_decision"] == "permit_mechanism_results_review_only"
    assert progress["formal_OOS_authorized"] is False
    assert audit["global_artifacts"] == {
        "formal_mechanism_run_registry_sha256": "d418a1a10e9a995365f38f0110c682fb70e709a7deb8127ec039d5d9f0958eb3",
        "formal_mechanism_progress_sha256": "5b02066db0a1bbe205042a9ab7abd454b678c81643e38c50459681e2ce5cab6e",
    }
    assert audit["stop_boundary"] == {
        "formal_mechanism_gate_passed": True,
        "next_decision": "permit_mechanism_results_review_only",
        "formal_OOS_authorized": False,
        "formal_OOS_runs_started": 0,
        "algorithm_performance_runs_started": 0,
        "M0_E3_runs_started": 0,
    }


def test_execution_tree_is_the_reviewed_merged_main_tree():
    baseline = load_audit()["execution_baseline"]
    assert baseline == {
        "execution_git_sha": "a761e1f5c1c2049ddcba0a91e16d0c9e1fd1a70c",
        "execution_git_tree_sha": "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69",
        "merged_main_sha": "9d836911de47cb4025078cb9412a8389b63992db",
        "merged_main_tree_sha": "c0d3c2b9b7bd772c9d451e834db7f51ef9ef0a69",
        "execution_tree_equals_merged_main_tree": True,
        "tracked_worktree_dirty_at_start": False,
        "untracked_execution_input_count_at_start": 0,
    }

import hashlib
import math
from pathlib import Path

import yaml


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml")


def _load_matrix() -> dict:
    with MATRIX_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    assert isinstance(payload, dict)
    return payload


def _compute_reference_budget(matrix: dict, tier: dict) -> float:
    if tier["id"] == "D0":
        with Path("configs/base.yaml").open("r", encoding="utf-8") as handle:
            legacy = yaml.safe_load(handle)
        return sum(
            price * demand * seasonality
            for price, seasonality in zip(
                legacy["scenario_generation"]["regular_price"],
                legacy["scenario_generation"]["demand_seasonality"],
                strict=True,
            )
            for demand in [legacy["scenario_generation"]["base_demand"]]
        )

    protocol = matrix["generator_protocol"]
    baseline = matrix["controlled_synthetic_baseline"]
    deterministic = protocol["deterministic_baselines"]
    periods = tier["periods"]
    archetypes = baseline["item_archetypes"][: tier["items"]]

    seasonality_spec = deterministic["demand_seasonality"]
    raw_seasonality = [
        1.0
        + seasonality_spec["sine_amplitude"] * math.sin(2.0 * math.pi * t / periods)
        + seasonality_spec["cosine_amplitude"]
        * math.cos(4.0 * math.pi * t / periods)
        for t in range(periods)
    ]
    raw_mean = sum(raw_seasonality) / periods
    seasonality = [value / raw_mean for value in raw_seasonality]

    price_spec = deterministic["regular_price"]
    total = 0.0
    for item in archetypes:
        for t in range(periods):
            expected_demand = (
                deterministic["first_item_base_demand_per_period"]
                * item["demand_multiplier"]
                * seasonality[t]
            )
            regular_price = (
                price_spec["base_first_item"]
                * item["regular_price_multiplier"]
                * (
                    1.0
                    + price_spec["trend_slope"] * t / (periods - 1)
                    + price_spec["sine_amplitude"]
                    * math.sin(2.0 * math.pi * t / periods)
                )
            )
            total += regular_price * expected_demand
    return total


def test_phase6_matrix_has_disjoint_reproducible_seed_sets() -> None:
    matrix = _load_matrix()
    seeds = matrix["seed_plan"]

    pilot = set(seeds["pilot_training_seeds"])
    training = set(seeds["formal_training_seeds"])
    testing = set(seeds["formal_test_seeds"])

    assert matrix["status"] == "candidate_for_freeze_pending_review"
    assert len(pilot) == 3
    assert len(training) == 10
    assert len(testing) == 10
    assert pilot.isdisjoint(training)
    assert pilot.isdisjoint(testing)
    assert training.isdisjoint(testing)


def test_phase6_generator_protocol_resolves_every_tier_and_reference_budget() -> None:
    matrix = _load_matrix()
    protocol = matrix["generator_protocol"]
    baseline = matrix["controlled_synthetic_baseline"]
    tiers = matrix["scale_tiers"]
    expected_budgets = matrix["budget_plan"]["reference_budget_by_tier"]
    tolerance = matrix["budget_plan"]["reference_budget_validation"][
        "absolute_tolerance"
    ]

    assert protocol["protocol_id"] == "phase6_controlled_synthetic_v1_0"
    assert protocol["tier_resolution_must_be_deterministic"] is True
    assert protocol["random_number_generation"]["numpy_version"] == "2.5.1"
    assert protocol["random_number_generation"]["normal_dtype"] == "float64"
    assert (
        sum(protocol["latent_factor_model"]["demand_variance_loadings"].values())
        == 1.0
    )
    canonical_base = Path("configs/base.yaml").read_text(encoding="utf-8").replace(
        "\r\n", "\n"
    )
    assert (
        hashlib.sha256(canonical_base.encode("utf-8")).hexdigest()
        == protocol["legacy_D0"]["canonical_lf_sha256"]
    )
    assert (
        protocol["legacy_D0"]["reference_budget_convention"]
        == "legacy_nominal_demand_baseline"
    )
    assert (
        protocol["legacy_D0"]["zero_truncation_expectation_correction_applied"]
        is False
    )
    assert (
        protocol["legacy_D0"][
            "strict_distribution_theoretical_expectation_claim_forbidden"
        ]
        is True
    )

    supported_periods = set(
        protocol["deterministic_baselines"]["demand_seasonality"][
            "applicable_period_counts"
        ]
    )
    for tier in tiers:
        assert tier["id"] in expected_budgets
        if tier["id"] != "D0":
            assert tier["id"] in protocol["applies_to_tiers"]
            assert tier["periods"] in supported_periods
            selected_items = baseline["item_archetypes"][: tier["items"]]
            assert len(selected_items) == tier["items"]
            assert all(item["shelf_life_periods"] > 0 for item in selected_items)
            assert (
                protocol["deterministic_baselines"]["initial_inventory"]["value"]
                == 0.0
            )
            assert (
                protocol["deterministic_baselines"]["storage_capacity"]["factor"]
                > 0.0
            )
        actual = _compute_reference_budget(matrix, tier)
        assert math.isclose(
            actual,
            expected_budgets[tier["id"]],
            rel_tol=0.0,
            abs_tol=tolerance,
        )


def test_phase6_matrix_freezes_scale_budget_and_exactness_gates() -> None:
    matrix = _load_matrix()
    tiers = matrix["scale_tiers"]
    tier_ids = [tier["id"] for tier in tiers]
    training_scenarios = [tier["training_scenarios"] for tier in tiers]

    assert tier_ids == ["D0", "V1", "V2", "P1", "P2", "P3", "P4"]
    assert len(tier_ids) == len(set(tier_ids))
    assert training_scenarios == sorted(training_scenarios)
    assert all(tier["out_of_sample_scenarios"] >= 5000 for tier in tiers)
    assert all(
        tier["formal_seed_count"]
        <= len(matrix["seed_plan"]["formal_training_seeds"])
        for tier in tiers
    )
    for tier in tiers:
        limits = tier["time_limits"]
        assert limits["solver_call_seconds"] < limits["ccg_budget_wall_seconds"]
        assert (
            limits["six_budget_sequence_wall_seconds"]
            == 6 * limits["ccg_budget_wall_seconds"]
        )

    formal_budgets = matrix["budget_plan"]["formal_factors"]
    assert formal_budgets == sorted(set(formal_budgets))
    assert len(formal_budgets) == 6
    expectation_sources = matrix["budget_plan"]["expectation_source_by_tier"]
    assert expectation_sources["D0"] == "legacy_nominal_demand_baseline"
    assert (
        expectation_sources["V1_to_P4"]
        == "frozen_generator_theoretical_expectation"
    )
    assert (
        matrix["budget_plan"][
            "D0_is_not_strict_distribution_theoretical_expectation"
        ]
        is True
    )
    assert matrix["budget_plan"]["training_sample_mean_forbidden"] is True

    gates = matrix["exactness_gates"]
    assert gates["extensive_vs_standard_ccg"]["objective_absolute_tolerance"] == 1e-5
    assert gates["cold_vs_warm"]["objective_relative_tolerance"] == 1e-7
    assert matrix["algorithm_comparison"]["full_candidate_oracle_required"] is True


def test_phase6_matrix_has_valid_sensitivity_and_oos_design() -> None:
    matrix = _load_matrix()
    ofat = matrix["sensitivity"]["one_factor_at_a_time"]

    unique_configurations = 1
    sensitivity_baseline = matrix["sensitivity"]["baseline_config"]
    for factor, specification in ofat.items():
        values = specification["values"]
        baseline = specification["baseline"]
        assert baseline in values
        assert baseline == sensitivity_baseline[factor]
        assert len(values) == 3
        unique_configurations += len(values) - 1
    assert unique_configurations == 23
    assert (
        matrix["sensitivity"]["baseline_source"]
        == "independent_E5_baseline_overrides_V2_item_shelf_life"
    )
    assert sensitivity_baseline["shelf_life_periods"] == 3
    assert (
        matrix["controlled_synthetic_baseline"]["item_archetypes"][0][
            "shelf_life_periods"
        ]
        == 6
    )

    out_of_sample = matrix["out_of_sample_evaluation"]
    assert out_of_sample["scenarios_per_training_seed"] >= 5000
    assert out_of_sample["independent_from_training"] is True
    assert out_of_sample["common_test_set_across_policies"] is True
    assert out_of_sample["reoptimization_on_test_set_forbidden"] is True
    assert out_of_sample["training_seed_count"] == 5
    assert "endogenous_reserve" in out_of_sample["policies"]
    required_metrics = {
        "plan_oos_status",
        "total_scenario_count",
        "optimal_evaluation_rate",
        "recourse_feasibility_rate",
        "infeasible_scenario_count",
        "solver_failure_count",
        "zero_reserve_flag",
    }
    assert required_metrics.issubset(out_of_sample["metrics"])
    assert (
        out_of_sample["aggregate_metric_rule"][
            "conditional_success_only_aggregates_forbidden"
        ]
        is True
    )
    assert (
        out_of_sample["aggregate_metric_rule"]["arbitrary_big_m_cost_forbidden"]
        is True
    )
    assert (
        out_of_sample["metric_definitions"]["reserve_utilization"][
            "value_when_reserve_at_or_below_tolerance"
        ]
        is None
    )
    accounting = out_of_sample["status_accounting"]
    assert accounting["mutually_exclusive_terminal_categories"] == [
        "optimal",
        "infeasible",
        "solver_failure",
    ]
    assert (
        accounting["count_identity"]
        == "total_scenario_count_equals_optimal_scenario_count_plus_infeasible_scenario_count_plus_solver_failure_count"
    )
    assert accounting["count_identity_must_hold_before_reporting"] is True
    assert (
        out_of_sample["metric_definitions"]["reported_service_level"]["aggregation"]
        == "demand_weighted_across_all_scenarios"
    )


def test_phase6_matrix_freezes_clustered_inference_and_completion_reporting() -> None:
    matrix = _load_matrix()
    reporting = matrix["statistical_reporting"]

    assert reporting["independent_experimental_unit"] == "training_seed"
    assert (
        reporting["technical_repetitions"]["aggregation_before_inference"]
        == "median"
    )
    assert (
        reporting["six_budget_summary_inference"]["cluster_unit"]
        == "entire_budget_sequence_within_training_seed"
    )
    assert (
        reporting["six_budget_summary_inference"]["within_seed_statistic"]
        == "median_log_cold_time_divided_by_warm_time_over_jointly_completed_budgets"
    )
    assert (
        reporting["six_budget_summary_inference"]["primary_across_seed_statistic"]
        == "median_of_within_seed_statistics"
    )
    assert reporting["extreme_tiers"]["P3"] == "descriptive_only"
    assert reporting["extreme_tiers"]["P4"] == "descriptive_only"
    completion_metrics = set(
        reporting["paired_completion_reporting"]["required"]
    )
    assert {
        "cold_completion_rate",
        "warm_completion_rate",
        "joint_pair_completion_rate",
        "conditional_speedup_on_jointly_completed_pairs",
    } == completion_metrics
    assert (
        reporting["H5_scene_similarity_analysis"]["association_statistic"]
        == "spearman_rank_correlation"
    )
    assert (
        reporting["H5_scene_similarity_analysis"]["confidence_interval"]
        == "cluster_bootstrap_by_training_seed"
    )
    uncertainty = reporting["uncertainty"]
    assert uncertainty["confidence_interval_method"] == "percentile"
    assert uncertainty["bootstrap_resamples"] == 10000
    assert len(set(uncertainty["bootstrap_random_seeds"].values())) == 3
    wilcoxon = reporting["optional_nonparametric_test"]
    assert wilcoxon["name"] == "wilcoxon_signed_rank"
    assert wilcoxon["seed_budget_rows_must_not_be_treated_as_independent"] is True
    assert (
        wilcoxon["fixed_budget_input"]
        == "one_paired_technical_median_per_training_seed"
    )
    assert (
        wilcoxon["six_budget_input"]
        == "one_within_seed_median_log_speedup_per_training_seed"
    )


def test_phase6_matrix_freezes_seed_selection_combined_scale_gates_and_timeouts() -> None:
    matrix = _load_matrix()
    tiers = {tier["id"]: tier for tier in matrix["scale_tiers"]}
    advancement = matrix["scale_advancement"]
    global_gate = advancement["all_conditions"]

    assert tiers["P3"]["formal_seed_selector"] == "first_5_formal_training_seeds"
    assert tiers["P4"]["formal_seed_selector"] == "first_3_formal_training_seeds"
    assert tiers["P3"]["activation_gate"]["rule_reference"] == "scale_advancement"
    assert tiers["P4"]["activation_gate"]["rule_reference"] == "scale_advancement"
    assert global_gate == {
        "joint_pair_completion_rate_minimum": 0.80,
        "max_algorithm_median_runtime_fraction_maximum": 0.75,
    }
    runtime_gate = advancement["runtime_fraction"]
    assert runtime_gate["eligible_pairs"] == "jointly_optimal_pairs_only"
    assert (
        runtime_gate["denominator"]
        == "tier_ccg_budget_wall_seconds_for_one_algorithm"
    )
    assert (
        runtime_gate["gate_statistic"]
        == "maximum_of_cold_statistic_and_warm_statistic"
    )
    assert runtime_gate["no_jointly_optimal_pairs"] == "gate_fails"

    timeout = matrix["timeout_protocol"]
    assert (
        timeout["paired_sequence_failure_rule"][
            "stop_pair_sequence_when_either_algorithm_is_nonoptimal"
        ]
        is True
    )
    assert (
        timeout["partial_result_retention"]["preserve_completed_budget_pairs"]
        is True
    )
    assert (
        timeout["partial_result_retention"][
            "preserve_current_partial_iteration_log"
        ]
        is True
    )
    workload = matrix["workload_estimation"]
    assert workload["E3_algorithm_executions"] == 1296
    assert (
        workload["pilot_throughput_gate"][
            "required_before_formal_seed_execution"
        ]
        is True
    )


def test_phase6_matrix_requires_exact_policy_evaluation_and_inventory_interaction() -> None:
    matrix = _load_matrix()
    comparison = matrix["model_comparison"]
    exact = comparison["training_exact_evaluation"]

    assert exact["required_for_all_policies"] is True
    assert exact["candidate_scenarios"] == "complete_training_set"
    assert exact["native_deterministic_objective_must_not_be_compared_directly"] is True
    assert comparison["endogenous_dominance_check"]["empirical_innovation_claim"] is False

    interaction = matrix["sensitivity"]["inventory_market_interaction"]
    assert set(interaction["factors"]) == {
        "shelf_life_periods",
        "supply_reduction_mean",
    }
    assert interaction["total_runs"] == 20

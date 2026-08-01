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
    assert matrix["schema_version"] == "2.1"
    assert matrix["matrix_id"] == "phase6_streamlined_experiments_v2_1"
    disposal = matrix["inventory_exit_protocol"]
    assert disposal["nonexpired_inventory_exit"] == "early_disposal"
    assert disposal["maximum_age_inventory_exit"] == "expired_waste"
    assert disposal["legacy_waste_field_semantics"] == "alias_of_total_disposal"
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

    assert tier_ids == ["D0", "V1", "V2", "P1", "P2"]
    assert matrix["generator_protocol"]["applies_to_tiers"] == [
        "V1",
        "V2",
        "P1",
        "P2",
    ]
    assert set(matrix["budget_plan"]["reference_budget_by_tier"]) == set(
        tier_ids
    )
    assert len(tier_ids) == len(set(tier_ids))
    assert training_scenarios == sorted(training_scenarios)
    assert all(tier["out_of_sample_scenarios"] == 2000 for tier in tiers)
    assert {
        tier["id"]: tier["formal_seed_count"] for tier in tiers
    } == {
        "D0": 1,
        "V1": 3,
        "V2": 10,
        "P1": 5,
        "P2": 3,
    }
    assert all(
        tier["formal_seed_count"]
        <= len(matrix["seed_plan"]["formal_training_seeds"])
        for tier in tiers
    )
    for tier in tiers:
        limits = tier["time_limits"]
        assert limits["solver_call_seconds"] < limits["ccg_budget_wall_seconds"]
        planned_budget_count = (
            len(matrix["budget_plan"]["legacy_absolute_budgets"])
            if tier["id"] == "D0"
            else len(matrix["budget_plan"]["formal_factors"])
        )
        assert limits["budget_sequence_wall_seconds"] == (
            planned_budget_count * limits["ccg_budget_wall_seconds"]
        )

    formal_budgets = matrix["budget_plan"]["formal_factors"]
    assert formal_budgets == sorted(set(formal_budgets))
    assert formal_budgets == [0.90, 1.10, 1.30]
    expectation_sources = matrix["budget_plan"]["expectation_source_by_tier"]
    assert expectation_sources["D0"] == "legacy_nominal_demand_baseline"
    assert (
        expectation_sources["V1_to_P2"]
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
    assert matrix["algorithm_comparison"]["tiers"] == [
        "V1",
        "V2",
        "P1",
        "P2",
    ]
    real_track = matrix["data_tracks"]["real_calibrated_synthetic"]
    assert real_track["required_for_core_method_claims"] is False
    assert real_track["optional_for_external_validity_extension"] is True


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
    assert unique_configurations == 11
    assert matrix["sensitivity"]["unique_ofat_configuration_count"] == 11
    assert set(ofat) == {
        "demand_cv",
        "emergency_price_markup_mean",
        "supply_reduction_mean",
        "shelf_life_periods",
        "storage_capacity_to_expected_period_demand",
    }
    assert matrix["sensitivity"]["budget_factors"] == [1.10]
    assert matrix["sensitivity"]["training_seed_count"] == 5
    assert (
        matrix["sensitivity"]["training_seed_selector"]
        == "first_5_formal_training_seeds"
    )
    assert "screening_factorial" not in matrix["sensitivity"]
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
    assert out_of_sample["scenarios_per_training_seed"] == 2000
    assert out_of_sample["evidence_role"] == "limited_descriptive_out_of_sample"
    assert out_of_sample["strong_significance_claims_forbidden"] is True
    assert (
        out_of_sample["not_a_substitute_for_V2_algorithm_timing_inference"]
        is True
    )
    assert out_of_sample["independent_from_training"] is True
    assert out_of_sample["common_test_set_across_policies"] is True
    assert out_of_sample["reoptimization_on_test_set_forbidden"] is True
    assert out_of_sample["training_seed_count"] == 5
    assert (
        out_of_sample["training_seed_selector"]
        == "first_5_formal_training_seeds"
    )
    assert (
        out_of_sample["test_seed_selector"]
        == "paired_first_5_formal_test_seeds"
    )
    assert out_of_sample["policies"] == [
        "deterministic_mean",
        "zero_reserve",
        "fixed_reserve_0_10",
        "fixed_reserve_0_30",
        "fixed_reserve_0_50",
        "endogenous_reserve",
    ]
    required_metrics = {
        "plan_oos_status",
        "total_scenario_count",
        "optimal_evaluation_rate",
        "recourse_feasibility_rate",
        "infeasible_scenario_count",
        "solver_failure_count",
        "zero_reserve_flag",
        "mean_expired_waste",
        "mean_early_disposal",
        "mean_total_disposal",
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
        reporting["budget_sequence_summary_inference"]["cluster_unit"]
        == "entire_budget_sequence_within_training_seed"
    )
    assert (
        reporting["budget_sequence_summary_inference"]["within_seed_statistic"]
        == "median_log_cold_time_divided_by_warm_time_over_jointly_completed_budgets"
    )
    assert (
        reporting["budget_sequence_summary_inference"][
            "primary_across_seed_statistic"
        ]
        == "median_of_within_seed_statistics"
    )
    assert reporting["tier_reporting_roles"] == {
        "V1": "correctness_only",
        "V2": "primary_inferential",
        "P1": "limited_inferential",
        "P2": "descriptive_only",
        "significance_tests_for_correctness_and_descriptive_tiers_forbidden": True,
    }
    completion_metrics = set(
        reporting["paired_completion_reporting"]["required"]
    )
    assert {
        "cold_completion_rate",
        "warm_completion_rate",
        "joint_pair_completion_rate",
        "conditional_speedup_on_jointly_completed_pairs",
    } == completion_metrics
    assert "H5_scene_similarity_analysis" not in reporting
    uncertainty = reporting["uncertainty"]
    assert uncertainty["confidence_interval_method"] == "percentile"
    assert uncertainty["bootstrap_resamples"] == 10000
    assert len(set(uncertainty["bootstrap_random_seeds"].values())) == 2
    wilcoxon = reporting["optional_nonparametric_test"]
    assert wilcoxon["name"] == "wilcoxon_signed_rank"
    assert wilcoxon["seed_budget_rows_must_not_be_treated_as_independent"] is True
    assert (
        wilcoxon["fixed_budget_input"]
        == "one_paired_technical_median_per_training_seed"
    )
    assert (
        wilcoxon["budget_sequence_input"]
        == "one_within_seed_median_log_speedup_per_training_seed"
    )


def test_phase6_matrix_freezes_seed_selection_combined_scale_gates_and_timeouts() -> None:
    matrix = _load_matrix()
    tiers = {tier["id"]: tier for tier in matrix["scale_tiers"]}
    advancement = matrix["scale_advancement"]
    global_gate = advancement["all_conditions"]

    assert tiers["V1"]["formal_seed_selector"] == "first_n_formal_training_seeds"
    assert tiers["V2"]["formal_seed_selector"] == "all_formal_training_seeds"
    assert tiers["P1"]["formal_seed_selector"] == "first_n_formal_training_seeds"
    assert tiers["P2"]["formal_seed_selector"] == "first_n_formal_training_seeds"
    assert tiers["P2"]["activation_gate"]["prior_tier"] == "P1"
    assert tiers["P2"]["activation_gate"]["rule_reference"] == "scale_advancement"
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
    algorithm_tiers = set(matrix["algorithm_comparison"]["tiers"])
    formal_budget_count = len(matrix["budget_plan"]["formal_factors"])
    calculated_executions = sum(
        tier["formal_seed_count"]
        * formal_budget_count
        * len(matrix["algorithm_comparison"]["algorithms"])
        * tier["timing_repetitions"]
        for tier in matrix["scale_tiers"]
        if tier["id"] in algorithm_tiers
    )
    calculated_ten_iteration_recourse = sum(
        tier["formal_seed_count"]
        * formal_budget_count
        * len(matrix["algorithm_comparison"]["algorithms"])
        * tier["timing_repetitions"]
        * tier["training_scenarios"]
        * 10
        for tier in matrix["scale_tiers"]
        if tier["id"] in algorithm_tiers
    )
    calculated_upper_recourse = calculated_ten_iteration_recourse * 20
    calculated_wall_hours = sum(
        tier["formal_seed_count"]
        * formal_budget_count
        * len(matrix["algorithm_comparison"]["algorithms"])
        * tier["timing_repetitions"]
        * tier["time_limits"]["ccg_budget_wall_seconds"]
        / 3600.0
        for tier in matrix["scale_tiers"]
        if tier["id"] in algorithm_tiers
    )
    assert calculated_executions == 246
    assert calculated_ten_iteration_recourse == 519000
    assert calculated_upper_recourse == 10380000
    assert calculated_wall_hours == 81
    assert workload["E3_algorithm_executions"] == calculated_executions
    assert (
        workload["E3_recourse_lp_calls_at_10_iterations_estimate"]
        == calculated_ten_iteration_recourse
    )
    assert (
        workload["E3_recourse_lp_calls_at_200_iterations_upper_bound"]
        == calculated_upper_recourse
    )
    assert (
        workload["E3_serial_budget_wall_upper_bound_hours"]
        == calculated_wall_hours
    )
    calculated_pilot_executions = (
        len(matrix["seed_plan"]["pilot_training_seeds"])
        * sum(
            formal_budget_count
            * len(matrix["algorithm_comparison"]["algorithms"])
            * tier["timing_repetitions"]
            for tier in matrix["scale_tiers"]
            if tier["id"] in algorithm_tiers
        )
    )
    assert (
        workload["E3_pilot_algorithm_executions"]
        == calculated_pilot_executions
        == 108
    )
    tiers_by_id = {
        tier["id"]: tier for tier in matrix["scale_tiers"]
    }
    exactness_plan_count = (
        len(matrix["budget_plan"]["legacy_absolute_budgets"])
        + sum(
            tiers_by_id[tier_id]["formal_seed_count"]
            * formal_budget_count
            for tier_id in matrix["exactness_gates"][
                "extensive_vs_standard_ccg"
            ]["tiers"]
            if tier_id != "D0"
        )
    )
    policy_plan_count = (
        tiers_by_id["V2"]["formal_seed_count"]
        * formal_budget_count
        * len(matrix["model_comparison"]["policies"])
    )
    oos = matrix["out_of_sample_evaluation"]
    oos_plan_count = (
        oos["training_seed_count"]
        * len(oos["budget_factors"])
        * len(oos["policies"])
    )
    sensitivity = matrix["sensitivity"]
    ofat_executions = (
        sensitivity["unique_ofat_configuration_count"]
        * sensitivity["training_seed_count"]
        * len(sensitivity["budget_factors"])
    )
    assert workload["E1_exactness_plan_count"] == exactness_plan_count == 45
    assert (
        workload["E1_extensive_and_standard_ccg_executions"]
        == 2 * exactness_plan_count
        == 90
    )
    assert workload["E2_policy_plan_count"] == policy_plan_count == 180
    assert workload["E2_training_exact_recourse_evaluations"] == (
        policy_plan_count * tiers_by_id["V2"]["training_scenarios"]
    )
    assert workload["E4_out_of_sample_plan_count"] == oos_plan_count == 90
    assert workload["E4_out_of_sample_recourse_evaluations"] == (
        oos_plan_count * oos["scenarios_per_training_seed"]
    )
    assert workload["E5_ofat_model_executions"] == ofat_executions == 55
    assert workload["E5_interaction_model_executions"] == (
        sensitivity["inventory_market_interaction"]["total_runs"]
    )
    assert workload["E5_total_model_executions"] == 75
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
    invariant = exact["relative_complete_recourse_invariant"]
    assert invariant["infeasible_recourse_for_any_policy_is_blocking"] is True
    assert invariant["violation_status"] == "unexpected_infeasible_recourse"
    oos_invariant = matrix["out_of_sample_evaluation"][
        "status_accounting"
    ]["relative_complete_recourse_invariant"]
    assert oos_invariant["infeasible_scenario_count_must_equal_zero"] is True
    assert oos_invariant["violation_status"] == "unexpected_infeasible_recourse"
    assert comparison["endogenous_dominance_check"]["empirical_innovation_claim"] is False
    assert comparison["tiers"] == ["V2"]
    assert comparison["policies"] == [
        "deterministic_mean",
        "zero_reserve",
        "fixed_reserve_0_10",
        "fixed_reserve_0_30",
        "fixed_reserve_0_50",
        "endogenous_reserve",
    ]

    interaction = matrix["sensitivity"]["inventory_market_interaction"]
    assert set(interaction["factors"]) == {
        "shelf_life_periods",
        "supply_reduction_mean",
    }
    assert interaction["total_runs"] == 20

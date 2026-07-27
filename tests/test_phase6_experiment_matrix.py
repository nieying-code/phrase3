from pathlib import Path

import yaml


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml")


def _load_matrix() -> dict:
    with MATRIX_PATH.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    assert isinstance(payload, dict)
    return payload


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
    assert (
        matrix["budget_plan"]["expectation_source"]
        == "frozen_generator_theoretical_expectation"
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
        "recourse_feasibility_rate",
        "infeasible_scenario_count",
        "solver_failure_count",
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


def test_phase6_matrix_freezes_seed_selection_combined_scale_gates_and_timeouts() -> None:
    matrix = _load_matrix()
    tiers = {tier["id"]: tier for tier in matrix["scale_tiers"]}
    global_gate = matrix["scale_advancement"]["all_conditions"]

    assert tiers["P3"]["formal_seed_selector"] == "first_5_formal_training_seeds"
    assert tiers["P4"]["formal_seed_selector"] == "first_3_formal_training_seeds"
    assert tiers["P3"]["activation_gate"]["all_conditions"] == global_gate
    assert tiers["P4"]["activation_gate"]["all_conditions"] == global_gate

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

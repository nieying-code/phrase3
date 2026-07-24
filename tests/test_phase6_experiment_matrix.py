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

    assert matrix["status"] == "frozen_for_implementation"
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

    formal_budgets = matrix["budget_plan"]["formal_factors"]
    assert formal_budgets == sorted(set(formal_budgets))
    assert len(formal_budgets) == 6

    gates = matrix["exactness_gates"]
    assert gates["extensive_vs_standard_ccg"]["objective_absolute_tolerance"] == 1e-5
    assert gates["cold_vs_warm"]["objective_relative_tolerance"] == 1e-7
    assert matrix["algorithm_comparison"]["full_candidate_oracle_required"] is True


def test_phase6_matrix_has_valid_sensitivity_and_oos_design() -> None:
    matrix = _load_matrix()
    ofat = matrix["sensitivity"]["one_factor_at_a_time"]

    unique_configurations = 1
    for specification in ofat.values():
        values = specification["values"]
        baseline = specification["baseline"]
        assert baseline in values
        assert len(values) == 3
        unique_configurations += len(values) - 1
    assert unique_configurations == 23

    out_of_sample = matrix["out_of_sample_evaluation"]
    assert out_of_sample["scenarios_per_training_seed"] >= 5000
    assert out_of_sample["independent_from_training"] is True
    assert out_of_sample["common_test_set_across_policies"] is True
    assert out_of_sample["reoptimization_on_test_set_forbidden"] is True
    assert out_of_sample["training_seed_count"] == 5
    assert "endogenous_reserve" in out_of_sample["policies"]

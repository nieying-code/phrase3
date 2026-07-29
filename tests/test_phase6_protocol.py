import math
from pathlib import Path

import pytest

from src.phase6_protocol import (
    Phase6ProtocolError,
    budget_values_for_tier,
    compute_reference_budget,
    generate_phase6_data,
    load_phase6_matrix,
    resolve_tier,
    validate_execution_seed,
)


MATRIX_PATH = Path("configs/phase6_experiment_matrix.yaml")


def test_phase6_protocol_resolves_all_tiers_and_reference_budgets() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    expected = matrix["budget_plan"]["reference_budget_by_tier"]
    tolerance = matrix["budget_plan"]["reference_budget_validation"][
        "absolute_tolerance"
    ]

    for tier_id, expected_value in expected.items():
        tier = resolve_tier(matrix, tier_id)
        actual = compute_reference_budget(
            matrix,
            tier_id,
            matrix_path=MATRIX_PATH,
        )
        assert tier.id == tier_id
        assert math.isclose(
            actual,
            float(expected_value),
            rel_tol=0.0,
            abs_tol=float(tolerance),
        )
        budgets = budget_values_for_tier(
            matrix,
            tier_id,
            matrix_path=MATRIX_PATH,
        )
        assert len(budgets) == (6 if tier_id == "D0" else 3)
        assert list(budgets) == sorted(budgets)


def test_phase6_controlled_generator_is_deterministic_and_complete() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    budget = budget_values_for_tier(
        matrix,
        "P1",
        matrix_path=MATRIX_PATH,
    )[2]
    first = generate_phase6_data(
        matrix,
        matrix_path=MATRIX_PATH,
        tier_id="P1",
        seed=2026072001,
        budget=budget,
    )
    repeated = generate_phase6_data(
        matrix,
        matrix_path=MATRIX_PATH,
        tier_id="P1",
        seed=2026072001,
        budget=budget,
    )
    changed = generate_phase6_data(
        matrix,
        matrix_path=MATRIX_PATH,
        tier_id="P1",
        seed=2026072002,
        budget=budget,
    )

    assert first.data.items == (
        "relief_food_1",
        "relief_food_2",
        "relief_food_3",
    )
    assert first.data.periods == 12
    assert len(first.data.scenarios) == 500
    assert first.data.demand == repeated.data.demand
    assert first.data.emergency_price == repeated.data.emergency_price
    assert first.data.emergency_supply == repeated.data.emergency_supply
    assert first.data.demand != changed.data.demand
    assert all(
        value == 0.0
        for values in first.data.initial_inventory.values()
        for value in values
    )
    for t in range(first.data.periods):
        expected_capacity = 1.5 * sum(
            first.theoretical_mean_demand[item][t]
            for item in first.data.items
        )
        assert first.data.storage_capacity[t] == pytest.approx(
            expected_capacity
        )
    first.data.validate()


def test_phase6_execution_seed_gate_blocks_formal_candidate_matrix() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    validate_execution_seed(
        matrix,
        tier_id="V1",
        seed=2026072001,
        execution_mode="pilot",
    )
    with pytest.raises(Phase6ProtocolError, match="formal seeds are blocked"):
        validate_execution_seed(
            matrix,
            tier_id="V1",
            seed=2026072401,
            execution_mode="formal",
        )
    with pytest.raises(Phase6ProtocolError, match="pilot mode must use V1"):
        validate_execution_seed(
            matrix,
            tier_id="D0",
            seed=2026072001,
            execution_mode="pilot",
        )


def test_phase6_formal_seed_selectors_use_declared_tier_counts() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    matrix["status"] = "frozen_for_formal_execution"

    allowed_by_tier = {
        "V1": matrix["seed_plan"]["formal_training_seeds"][:3],
        "V2": matrix["seed_plan"]["formal_training_seeds"],
        "P1": matrix["seed_plan"]["formal_training_seeds"][:5],
        "P2": matrix["seed_plan"]["formal_training_seeds"][:3],
    }
    for tier_id, allowed in allowed_by_tier.items():
        for seed in allowed:
            validate_execution_seed(
                matrix,
                tier_id=tier_id,
                seed=seed,
                execution_mode="formal",
            )
        first_disallowed = next(
            seed
            for seed in matrix["seed_plan"]["formal_training_seeds"]
            if seed not in allowed
        ) if len(allowed) < 10 else 99999999
        with pytest.raises(Phase6ProtocolError, match="is not allowed"):
            validate_execution_seed(
                matrix,
                tier_id=tier_id,
                seed=first_disallowed,
                execution_mode="formal",
            )
    validate_execution_seed(
        matrix,
        tier_id="D0",
        seed=matrix["seed_plan"]["development_seed"],
        execution_mode="formal",
    )
    with pytest.raises(Phase6ProtocolError, match="is not allowed"):
        validate_execution_seed(
            matrix,
            tier_id="D0",
            seed=matrix["seed_plan"]["formal_training_seeds"][0],
            execution_mode="formal",
        )


def test_phase6_D0_keeps_legacy_nominal_reference_convention() -> None:
    matrix = load_phase6_matrix(MATRIX_PATH)
    legacy = matrix["generator_protocol"]["legacy_D0"]
    assert legacy["reference_budget_convention"] == "legacy_nominal_demand_baseline"
    assert legacy["zero_truncation_expectation_correction_applied"] is False
    assert math.isclose(
        compute_reference_budget(matrix, "D0", matrix_path=MATRIX_PATH),
        853.5,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    )

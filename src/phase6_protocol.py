"""Strict resolver and controlled-data generator for the Phase 6 matrix."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any, Mapping

import numpy as np
import yaml

from .model_data import ProcurementData
from .scenario_generator import generate_synthetic_data


SUPPORTED_MATRIX_ID = "phase6_streamlined_experiments_v2_1"
SUPPORTED_GENERATOR_PROTOCOL = "phase6_controlled_synthetic_v1_0"
FORMAL_EXECUTION_STATUS = "frozen_for_formal_execution"


class Phase6ProtocolError(ValueError):
    """Raised when the frozen matrix cannot be resolved unambiguously."""


@dataclass(frozen=True)
class TierSpec:
    """Validated machine-readable scale-tier definition."""

    id: str
    items: int
    periods: int
    training_scenarios: int
    out_of_sample_scenarios: int
    formal_seed_count: int
    formal_seed_selector: str
    solver_call_seconds: float
    ccg_budget_wall_seconds: float
    budget_sequence_wall_seconds: float
    timing_repetitions: int


@dataclass(frozen=True)
class GeneratedPhase6Data:
    """Generated model data plus deterministic protocol metadata."""

    data: ProcurementData
    tier: TierSpec
    seed: int
    budget: float
    reference_budget: float
    budget_factor: float | None
    theoretical_mean_demand: Mapping[str, tuple[float, ...]]
    generator_protocol_id: str


def load_phase6_matrix(path: str | Path) -> dict[str, Any]:
    """Load and validate the supported frozen-candidate matrix."""

    matrix_path = Path(path)
    with matrix_path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise Phase6ProtocolError("phase 6 matrix root must be a mapping")
    if payload.get("matrix_id") != SUPPORTED_MATRIX_ID:
        raise Phase6ProtocolError(
            f"unsupported matrix_id: {payload.get('matrix_id')!r}; "
            f"expected {SUPPORTED_MATRIX_ID!r}"
        )
    protocol = payload.get("generator_protocol")
    if not isinstance(protocol, dict):
        raise Phase6ProtocolError("generator_protocol must be a mapping")
    if protocol.get("protocol_id") != SUPPORTED_GENERATOR_PROTOCOL:
        raise Phase6ProtocolError(
            f"unsupported generator protocol: {protocol.get('protocol_id')!r}"
        )
    _validate_matrix(payload, matrix_path)
    return payload


def _validate_matrix(matrix: Mapping[str, Any], matrix_path: Path) -> None:
    tiers = matrix.get("scale_tiers")
    if not isinstance(tiers, list) or not tiers:
        raise Phase6ProtocolError("scale_tiers must be a nonempty list")
    tier_ids = [str(tier["id"]) for tier in tiers]
    if len(tier_ids) != len(set(tier_ids)):
        raise Phase6ProtocolError("scale tier ids must be unique")

    protocol = matrix["generator_protocol"]
    weights = protocol["latent_factor_model"]["demand_variance_loadings"]
    if not math.isclose(
        sum(float(value) for value in weights.values()),
        1.0,
        rel_tol=0.0,
        abs_tol=1.0e-12,
    ):
        raise Phase6ProtocolError("demand variance loadings must sum to one")

    expected_numpy = str(protocol["random_number_generation"]["numpy_version"])
    if np.__version__ != expected_numpy:
        raise Phase6ProtocolError(
            f"NumPy {expected_numpy} is required by the frozen protocol; "
            f"found {np.__version__}"
        )

    legacy = protocol["legacy_D0"]
    legacy_path = matrix_path.parent.parent / str(legacy["source"])
    canonical = (
        legacy_path.read_text(encoding="utf-8")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .encode("utf-8")
    )
    actual_hash = hashlib.sha256(canonical).hexdigest()
    if actual_hash != str(legacy["canonical_lf_sha256"]):
        raise Phase6ProtocolError(
            "legacy D0 source hash does not match the frozen matrix"
        )

    for tier_id in tier_ids:
        tier = resolve_tier(matrix, tier_id)
        formal_seed_count = len(
            matrix["seed_plan"]["formal_training_seeds"]
        )
        if tier.formal_seed_selector == "all_formal_training_seeds":
            if tier.formal_seed_count != formal_seed_count:
                raise Phase6ProtocolError(
                    f"{tier.id} must select all {formal_seed_count} "
                    "formal training seeds"
                )
        elif tier.formal_seed_selector == "first_n_formal_training_seeds":
            if not 0 < tier.formal_seed_count <= formal_seed_count:
                raise Phase6ProtocolError(
                    f"{tier.id} has an invalid first-n formal seed count"
                )
        elif tier.formal_seed_selector == "development_seed_only":
            if tier.formal_seed_count != 1:
                raise Phase6ProtocolError(
                    f"{tier.id} development-only seed count must be one"
                )
        else:
            raise Phase6ProtocolError(
                f"unsupported formal seed selector for {tier.id}: "
                f"{tier.formal_seed_selector!r}"
            )
        if tier.id != "D0":
            supported_periods = {
                int(value)
                for value in protocol["deterministic_baselines"][
                    "demand_seasonality"
                ]["applicable_period_counts"]
            }
            if tier.periods not in supported_periods:
                raise Phase6ProtocolError(
                    f"period count {tier.periods} is unsupported for {tier.id}"
                )
        expected = float(
            matrix["budget_plan"]["reference_budget_by_tier"][tier.id]
        )
        actual = compute_reference_budget(matrix, tier.id, matrix_path=matrix_path)
        tolerance = float(
            matrix["budget_plan"]["reference_budget_validation"][
                "absolute_tolerance"
            ]
        )
        if not math.isclose(actual, expected, rel_tol=0.0, abs_tol=tolerance):
            raise Phase6ProtocolError(
                f"reference budget mismatch for {tier.id}: {actual} != {expected}"
            )
        planned_budget_count = len(
            matrix["budget_plan"][
                "legacy_absolute_budgets"
                if tier.id == "D0"
                else "formal_factors"
            ]
        )
        expected_sequence_limit = (
            planned_budget_count * tier.ccg_budget_wall_seconds
        )
        if not math.isclose(
            tier.budget_sequence_wall_seconds,
            expected_sequence_limit,
            rel_tol=0.0,
            abs_tol=1.0e-9,
        ):
            raise Phase6ProtocolError(
                f"{tier.id} budget sequence limit must equal "
                "planned budget count times the single-budget limit"
            )


def resolve_tier(matrix: Mapping[str, Any], tier_id: str) -> TierSpec:
    """Resolve one tier and validate its time-limit hierarchy."""

    matches = [
        tier for tier in matrix["scale_tiers"] if str(tier["id"]) == tier_id
    ]
    if len(matches) != 1:
        raise Phase6ProtocolError(f"unknown or duplicate tier: {tier_id}")
    raw = matches[0]
    limits = raw["time_limits"]
    result = TierSpec(
        id=tier_id,
        items=int(raw["items"]),
        periods=int(raw["periods"]),
        training_scenarios=int(raw["training_scenarios"]),
        out_of_sample_scenarios=int(raw["out_of_sample_scenarios"]),
        formal_seed_count=int(raw["formal_seed_count"]),
        formal_seed_selector=str(raw["formal_seed_selector"]),
        solver_call_seconds=float(limits["solver_call_seconds"]),
        ccg_budget_wall_seconds=float(limits["ccg_budget_wall_seconds"]),
        budget_sequence_wall_seconds=float(
            limits["budget_sequence_wall_seconds"]
        ),
        timing_repetitions=int(raw["timing_repetitions"]),
    )
    if min(
        result.items,
        result.periods,
        result.training_scenarios,
        result.out_of_sample_scenarios,
        result.timing_repetitions,
    ) <= 0:
        raise Phase6ProtocolError(f"tier {tier_id} contains nonpositive dimensions")
    if not (
        0.0
        < result.solver_call_seconds
        < result.ccg_budget_wall_seconds
        <= result.budget_sequence_wall_seconds
    ):
        raise Phase6ProtocolError(f"tier {tier_id} has invalid time limits")
    return result


def _seasonality(matrix: Mapping[str, Any], periods: int) -> tuple[float, ...]:
    specification = matrix["generator_protocol"]["deterministic_baselines"][
        "demand_seasonality"
    ]
    sine = float(specification["sine_amplitude"])
    cosine = float(specification["cosine_amplitude"])
    raw = tuple(
        1.0
        + sine * math.sin(2.0 * math.pi * t / periods)
        + cosine * math.cos(4.0 * math.pi * t / periods)
        for t in range(periods)
    )
    mean = sum(raw) / periods
    return tuple(value / mean for value in raw)


def _regular_price(
    matrix: Mapping[str, Any],
    *,
    periods: int,
    multiplier: float,
) -> tuple[float, ...]:
    specification = matrix["generator_protocol"]["deterministic_baselines"][
        "regular_price"
    ]
    base = float(specification["base_first_item"])
    trend = float(specification["trend_slope"])
    sine = float(specification["sine_amplitude"])
    return tuple(
        base
        * multiplier
        * (
            1.0
            + trend * t / (periods - 1)
            + sine * math.sin(2.0 * math.pi * t / periods)
        )
        for t in range(periods)
    )


def compute_reference_budget(
    matrix: Mapping[str, Any],
    tier_id: str,
    *,
    matrix_path: str | Path,
) -> float:
    """Compute D0 nominal or V1-P2 theoretical reference budget."""

    tier = resolve_tier(matrix, tier_id)
    if tier.id == "D0":
        legacy_path = Path(matrix_path).parent.parent / str(
            matrix["generator_protocol"]["legacy_D0"]["source"]
        )
        with legacy_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        generation = config["scenario_generation"]
        base_demand = float(generation["base_demand"])
        return sum(
            float(price) * base_demand * float(seasonality)
            for price, seasonality in zip(
                generation["regular_price"],
                generation["demand_seasonality"],
                strict=True,
            )
        )

    baseline = matrix["controlled_synthetic_baseline"]
    protocol = matrix["generator_protocol"]["deterministic_baselines"]
    archetypes = baseline["item_archetypes"][: tier.items]
    seasonality = _seasonality(matrix, tier.periods)
    total = 0.0
    for item in archetypes:
        prices = _regular_price(
            matrix,
            periods=tier.periods,
            multiplier=float(item["regular_price_multiplier"]),
        )
        for t in range(tier.periods):
            mean_demand = (
                float(protocol["first_item_base_demand_per_period"])
                * float(item["demand_multiplier"])
                * seasonality[t]
            )
            total += prices[t] * mean_demand
    return total


def budget_values_for_tier(
    matrix: Mapping[str, Any],
    tier_id: str,
    *,
    matrix_path: str | Path,
) -> tuple[float, ...]:
    """Return the exact ordered budget sequence for a tier."""

    if tier_id == "D0":
        return tuple(
            float(value)
            for value in matrix["budget_plan"]["legacy_absolute_budgets"]
        )
    reference = compute_reference_budget(
        matrix,
        tier_id,
        matrix_path=matrix_path,
    )
    return tuple(
        reference * float(factor)
        for factor in matrix["budget_plan"]["formal_factors"]
    )


def validate_matrix_execution_status(
    matrix: Mapping[str, Any],
    *,
    execution_mode: str,
) -> None:
    """Block every non-development experiment until the matrix is frozen."""

    if (
        execution_mode in {"pilot", "formal"}
        and matrix.get("status") != FORMAL_EXECUTION_STATUS
    ):
        raise Phase6ProtocolError(
            f"{execution_mode} execution is blocked until matrix status is "
            f"{FORMAL_EXECUTION_STATUS!r}"
        )


def validate_execution_seed(
    matrix: Mapping[str, Any],
    *,
    tier_id: str,
    seed: int,
    execution_mode: str,
) -> None:
    """Enforce development, pilot, and formal seed boundaries."""

    validate_matrix_execution_status(
        matrix,
        execution_mode=execution_mode,
    )
    tier = resolve_tier(matrix, tier_id)
    seed_plan = matrix["seed_plan"]
    if execution_mode == "development":
        allowed = {int(seed_plan["development_seed"])}
    elif execution_mode == "pilot":
        allowed = {int(value) for value in seed_plan["pilot_training_seeds"]}
        if tier.id == "D0":
            raise Phase6ProtocolError("pilot mode must use V1 or a larger tier")
    elif execution_mode == "formal":
        formal = [
            int(value) for value in seed_plan["formal_training_seeds"]
        ]
        if tier.formal_seed_selector == "all_formal_training_seeds":
            if tier.formal_seed_count != len(formal):
                raise Phase6ProtocolError(
                    f"{tier.id} formal_seed_count must equal the complete "
                    "formal seed list for all_formal_training_seeds"
                )
        elif tier.formal_seed_selector == "first_n_formal_training_seeds":
            formal = formal[: tier.formal_seed_count]
        elif tier.formal_seed_selector == "development_seed_only":
            formal = [int(seed_plan["development_seed"])]
        else:
            raise Phase6ProtocolError(
                f"unsupported formal seed selector for {tier.id}: "
                f"{tier.formal_seed_selector!r}"
            )
        allowed = set(formal)
    else:
        raise Phase6ProtocolError(
            "execution_mode must be development, pilot, or formal"
        )
    if int(seed) not in allowed:
        raise Phase6ProtocolError(
            f"seed {seed} is not allowed for {execution_mode} {tier_id}"
        )


def generate_phase6_data(
    matrix: Mapping[str, Any],
    *,
    matrix_path: str | Path,
    tier_id: str,
    seed: int,
    budget: float,
) -> GeneratedPhase6Data:
    """Generate one complete finite-scenario data set from the frozen protocol."""

    tier = resolve_tier(matrix, tier_id)
    reference = compute_reference_budget(
        matrix,
        tier_id,
        matrix_path=matrix_path,
    )
    factor = None if tier.id == "D0" else float(budget) / reference
    if budget <= 0.0:
        raise Phase6ProtocolError("budget must be positive")

    if tier.id == "D0":
        legacy_path = Path(matrix_path).parent.parent / str(
            matrix["generator_protocol"]["legacy_D0"]["source"]
        )
        with legacy_path.open("r", encoding="utf-8") as handle:
            config = yaml.safe_load(handle)
        config = deepcopy(config)
        config["project"]["seed"] = int(seed)
        config["dimensions"]["scenarios"] = tier.training_scenarios
        config["budget"]["total"] = float(budget)
        data = generate_synthetic_data(config)
        theoretical = {
            str(config["dimensions"]["items"][0]): tuple(
                float(config["scenario_generation"]["base_demand"])
                * float(value)
                for value in config["scenario_generation"][
                    "demand_seasonality"
                ]
            )
        }
        return GeneratedPhase6Data(
            data=data,
            tier=tier,
            seed=int(seed),
            budget=float(budget),
            reference_budget=reference,
            budget_factor=factor,
            theoretical_mean_demand=theoretical,
            generator_protocol_id="legacy_D0",
        )

    return _generate_controlled_data(
        matrix,
        tier=tier,
        seed=int(seed),
        budget=float(budget),
        reference_budget=reference,
        budget_factor=factor,
    )


def _generate_controlled_data(
    matrix: Mapping[str, Any],
    *,
    tier: TierSpec,
    seed: int,
    budget: float,
    reference_budget: float,
    budget_factor: float | None,
) -> GeneratedPhase6Data:
    baseline = matrix["controlled_synthetic_baseline"]
    protocol = matrix["generator_protocol"]
    deterministic = protocol["deterministic_baselines"]
    transformations = protocol["scenario_transformations"]
    loadings = protocol["latent_factor_model"]["demand_variance_loadings"]

    archetypes = baseline["item_archetypes"][: tier.items]
    items = tuple(str(item["id"]) for item in archetypes)
    scenarios = tuple(
        f"s{index:04d}" for index in range(tier.training_scenarios)
    )
    seasonality = _seasonality(matrix, tier.periods)
    base_demand = float(deterministic["first_item_base_demand_per_period"])
    mean_demand = {
        str(item["id"]): tuple(
            base_demand * float(item["demand_multiplier"]) * seasonality[t]
            for t in range(tier.periods)
        )
        for item in archetypes
    }
    regular_price = {
        str(item["id"]): _regular_price(
            matrix,
            periods=tier.periods,
            multiplier=float(item["regular_price_multiplier"]),
        )
        for item in archetypes
    }
    shelf_life = {
        str(item["id"]): int(item["shelf_life_periods"])
        for item in archetypes
    }
    initial_inventory = {
        item: tuple(0.0 for _ in range(shelf_life[item]))
        for item in items
    }
    capacity_factor = float(
        deterministic["storage_capacity"]["factor"]
    )
    storage_capacity = tuple(
        capacity_factor * sum(mean_demand[item][t] for item in items)
        for t in range(tier.periods)
    )

    demand_cv = float(baseline["demand_cv"])
    log_sigma = math.sqrt(math.log1p(demand_cv**2))
    markup_mean = float(baseline["emergency_price_markup_mean"])
    markup_sd = float(baseline["emergency_price_markup_sd"])
    supply_reduction = float(baseline["supply_reduction_mean"])
    supply_sd = float(baseline["supply_shock_sd"])
    supply_ratio = float(deterministic["base_emergency_supply_ratio"])
    demand_price_corr = float(baseline["demand_price_correlation"])
    demand_supply_corr = float(baseline["demand_supply_correlation"])
    price_residual_scale = math.sqrt(1.0 - demand_price_corr**2)
    supply_residual_scale = math.sqrt(1.0 - demand_supply_corr**2)
    markup_lower = float(
        transformations["emergency_price_markup"]["lower_bound"]
    )
    supply_lower = float(
        transformations["emergency_supply_factor"]["lower_bound"]
    )
    supply_upper = float(
        transformations["emergency_supply_factor"]["upper_bound"]
    )

    coefficient_common = math.sqrt(float(loadings["common_disaster"]))
    coefficient_item = math.sqrt(float(loadings["item"]))
    coefficient_period = math.sqrt(float(loadings["period"]))
    coefficient_idiosyncratic = math.sqrt(float(loadings["idiosyncratic"]))
    rng = np.random.Generator(np.random.PCG64DXSM(seed))

    demand: dict[str, dict[str, tuple[float, ...]]] = {}
    emergency_price: dict[str, dict[str, tuple[float, ...]]] = {}
    emergency_supply: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario in scenarios:
        common_factor = float(rng.standard_normal(dtype=np.float64))
        item_factors = {
            item: float(rng.standard_normal(dtype=np.float64))
            for item in items
        }
        period_factors = tuple(
            float(rng.standard_normal(dtype=np.float64))
            for _ in range(tier.periods)
        )
        demand[scenario] = {}
        emergency_price[scenario] = {}
        emergency_supply[scenario] = {}
        for item in items:
            demand_values: list[float] = []
            price_values: list[float] = []
            supply_values: list[float] = []
            for t in range(tier.periods):
                demand_residual = float(
                    rng.standard_normal(dtype=np.float64)
                )
                price_residual = float(
                    rng.standard_normal(dtype=np.float64)
                )
                supply_residual = float(
                    rng.standard_normal(dtype=np.float64)
                )
                demand_latent = (
                    coefficient_common * common_factor
                    + coefficient_item * item_factors[item]
                    + coefficient_period * period_factors[t]
                    + coefficient_idiosyncratic * demand_residual
                )
                price_latent = (
                    demand_price_corr * demand_latent
                    + price_residual_scale * price_residual
                )
                supply_latent = (
                    demand_supply_corr * demand_latent
                    + supply_residual_scale * supply_residual
                )
                d_value = mean_demand[item][t] * math.exp(
                    log_sigma * demand_latent - 0.5 * log_sigma**2
                )
                markup = max(
                    markup_lower,
                    markup_mean + markup_sd * price_latent,
                )
                p_value = regular_price[item][t] * (1.0 + markup)
                supply_factor = min(
                    supply_upper,
                    max(
                        supply_lower,
                        1.0 - supply_reduction + supply_sd * supply_latent,
                    ),
                )
                u_value = (
                    mean_demand[item][t] * supply_ratio * supply_factor
                )
                demand_values.append(d_value)
                price_values.append(p_value)
                supply_values.append(u_value)
            demand[scenario][item] = tuple(demand_values)
            emergency_price[scenario][item] = tuple(price_values)
            emergency_supply[scenario][item] = tuple(supply_values)

    penalty = protocol["penalty_protocol"]
    shortage_multiplier = float(baseline["shortage_penalty_multiplier"])
    waste_multiplier = float(baseline["waste_penalty_multiplier"])
    shortage_penalty = {
        item: shortage_multiplier
        * max(regular_price[item])
        * (1.0 + markup_mean + 3.0 * markup_sd)
        for item in items
    }
    waste_penalty = {
        item: waste_multiplier * max(regular_price[item])
        for item in items
    }
    if not penalty:
        raise Phase6ProtocolError("penalty_protocol must not be empty")

    data = ProcurementData(
        items=items,
        periods=tier.periods,
        scenarios=scenarios,
        budget=budget,
        shelf_life=shelf_life,
        initial_inventory=initial_inventory,
        storage_capacity=storage_capacity,
        regular_price=regular_price,
        demand=demand,
        emergency_price=emergency_price,
        emergency_supply=emergency_supply,
        shortage_penalty=shortage_penalty,
        waste_penalty=waste_penalty,
    )
    data.validate()
    return GeneratedPhase6Data(
        data=data,
        tier=tier,
        seed=seed,
        budget=budget,
        reference_budget=reference_budget,
        budget_factor=budget_factor,
        theoretical_mean_demand=mean_demand,
        generator_protocol_id=SUPPORTED_GENERATOR_PROTOCOL,
    )

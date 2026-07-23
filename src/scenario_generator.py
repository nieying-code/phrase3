"""Reproducible synthetic scenarios for phase-2 model development."""

from __future__ import annotations

import csv
import math
import random
from pathlib import Path
from typing import Any

import yaml

from .model_data import ProcurementData


def load_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("configuration root must be a mapping")
    return config


def _correlated_normal(driver: float, correlation: float, rng: random.Random) -> float:
    if not -1.0 <= correlation <= 1.0:
        raise ValueError("correlation must be in [-1, 1]")
    return correlation * driver + math.sqrt(max(0.0, 1.0 - correlation**2)) * rng.gauss(0, 1)


def generate_synthetic_data(config: dict[str, Any]) -> ProcurementData:
    """Build finite scenarios with seasonal and correlated market shocks."""

    rng = random.Random(int(config["project"]["seed"]))
    items = tuple(str(item) for item in config["dimensions"]["items"])
    periods = int(config["dimensions"]["periods"])
    scenario_count = int(config["dimensions"]["scenarios"])
    scenarios = tuple(f"s{index:04d}" for index in range(scenario_count))

    generation = config["scenario_generation"]
    seasonality = tuple(float(v) for v in generation["demand_seasonality"])
    if len(seasonality) != periods:
        raise ValueError("demand_seasonality length must equal periods")

    regular_price_raw = generation.get("regular_price", [2.0] * periods)
    regular_price_base = tuple(float(v) for v in regular_price_raw)
    if len(regular_price_base) != periods:
        raise ValueError("regular_price length must equal periods")

    base_demand = float(generation["base_demand"])
    demand_cv = float(generation["demand_cv"])
    price_corr = float(generation["demand_price_correlation"])
    supply_corr = float(generation["demand_supply_correlation"])
    markup_mean = float(generation["emergency_price_markup_mean"])
    markup_sd = float(generation["emergency_price_markup_sd"])
    reduction_mean = float(generation["supply_reduction_mean"])
    base_supply_ratio = float(generation.get("base_supply_ratio", 1.35))
    supply_shock_sd = float(generation.get("supply_shock_sd", 0.20))

    regular_price = {item: regular_price_base for item in items}
    demand: dict[str, dict[str, tuple[float, ...]]] = {}
    emergency_price: dict[str, dict[str, tuple[float, ...]]] = {}
    emergency_supply: dict[str, dict[str, tuple[float, ...]]] = {}

    for scenario in scenarios:
        demand[scenario] = {}
        emergency_price[scenario] = {}
        emergency_supply[scenario] = {}
        for item in items:
            d_values: list[float] = []
            p_values: list[float] = []
            u_values: list[float] = []
            for t in range(periods):
                demand_shock = rng.gauss(0, 1)
                price_shock = _correlated_normal(demand_shock, price_corr, rng)
                supply_shock = _correlated_normal(demand_shock, supply_corr, rng)

                seasonal_demand = base_demand * seasonality[t]
                d_value = max(0.0, seasonal_demand * (1.0 + demand_cv * demand_shock))
                markup = max(0.05, markup_mean + markup_sd * price_shock)
                p_value = regular_price_base[t] * (1.0 + markup)
                supply_factor = max(
                    0.05,
                    1.0 - reduction_mean + supply_shock_sd * supply_shock,
                )
                u_value = max(0.0, seasonal_demand * base_supply_ratio * supply_factor)

                d_values.append(d_value)
                p_values.append(p_value)
                u_values.append(u_value)

            demand[scenario][item] = tuple(d_values)
            emergency_price[scenario][item] = tuple(p_values)
            emergency_supply[scenario][item] = tuple(u_values)

    shelf_life = {
        item: int(config["inventory"]["shelf_life"][item])
        for item in items
    }
    initial_inventory = {
        item: tuple(float(v) for v in config["inventory"]["initial_inventory"][item])
        for item in items
    }
    storage_capacity = tuple(float(v) for v in config["inventory"]["storage_capacity"])
    if len(storage_capacity) != periods:
        raise ValueError("storage_capacity length must equal periods")

    max_reference_price = max(regular_price_base) * (
        1.0 + markup_mean + 3.0 * max(0.0, markup_sd)
    )
    scaling = config["cost_scaling"]
    shortage_penalty = {
        item: float(scaling["shortage_penalty_multiplier"]) * max_reference_price
        for item in items
    }
    waste_penalty = {
        item: float(scaling["waste_penalty_multiplier"]) * max(regular_price_base)
        for item in items
    }

    data = ProcurementData(
        items=items,
        periods=periods,
        scenarios=scenarios,
        budget=float(config["budget"]["total"]),
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
    return data


def write_scenarios_csv(data: ProcurementData, path: str | Path) -> None:
    """Write the generated finite scenarios in a transparent long format."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["scenario", "item", "period", "demand", "emergency_price", "emergency_supply"]
        )
        for scenario in data.scenarios:
            for item in data.items:
                for t in range(data.periods):
                    writer.writerow(
                        [
                            scenario,
                            item,
                            t + 1,
                            data.demand[scenario][item][t],
                            data.emergency_price[scenario][item][t],
                            data.emergency_supply[scenario][item][t],
                        ]
                    )

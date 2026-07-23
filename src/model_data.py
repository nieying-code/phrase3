"""Validated data structures for the phase-2 procurement models."""

from __future__ import annotations

from dataclasses import dataclass, replace
from statistics import fmean
from typing import Mapping


SeriesByItem = Mapping[str, tuple[float, ...]]
ScenarioSeries = Mapping[str, SeriesByItem]


@dataclass(frozen=True)
class ProcurementData:
    """Finite-scenario data for age-indexed relief procurement."""

    items: tuple[str, ...]
    periods: int
    scenarios: tuple[str, ...]
    budget: float
    shelf_life: Mapping[str, int]
    initial_inventory: Mapping[str, tuple[float, ...]]
    storage_capacity: tuple[float, ...]
    regular_price: SeriesByItem
    demand: ScenarioSeries
    emergency_price: ScenarioSeries
    emergency_supply: ScenarioSeries
    shortage_penalty: Mapping[str, float]
    waste_penalty: Mapping[str, float]

    def validate(self) -> None:
        if not self.items:
            raise ValueError("at least one item is required")
        if self.periods <= 0:
            raise ValueError("periods must be positive")
        if not self.scenarios:
            raise ValueError("at least one scenario is required")
        if self.budget < 0:
            raise ValueError("budget must be nonnegative")
        if len(self.storage_capacity) != self.periods:
            raise ValueError("storage_capacity length must equal periods")

        for value in self.storage_capacity:
            if value < 0:
                raise ValueError("storage capacities must be nonnegative")

        for item in self.items:
            life = self.shelf_life[item]
            if life <= 0:
                raise ValueError(f"shelf life must be positive for {item}")
            if len(self.initial_inventory[item]) != life:
                raise ValueError(f"initial_inventory length must equal shelf life for {item}")
            if len(self.regular_price[item]) != self.periods:
                raise ValueError(f"regular_price length must equal periods for {item}")
            if self.shortage_penalty[item] < 0 or self.waste_penalty[item] < 0:
                raise ValueError("penalties must be nonnegative")

            for scenario in self.scenarios:
                for name, values in (
                    ("demand", self.demand[scenario][item]),
                    ("emergency_price", self.emergency_price[scenario][item]),
                    ("emergency_supply", self.emergency_supply[scenario][item]),
                ):
                    if len(values) != self.periods:
                        raise ValueError(
                            f"{name}[{scenario}][{item}] length must equal periods"
                        )
                    if any(value < 0 for value in values):
                        raise ValueError(f"{name} values must be nonnegative")

    def subset(self, scenarios: tuple[str, ...]) -> "ProcurementData":
        """Return a copy restricted to an ordered scenario subset."""

        unknown = set(scenarios) - set(self.scenarios)
        if unknown:
            raise KeyError(f"unknown scenarios: {sorted(unknown)}")
        result = replace(
            self,
            scenarios=scenarios,
            demand={s: self.demand[s] for s in scenarios},
            emergency_price={s: self.emergency_price[s] for s in scenarios},
            emergency_supply={s: self.emergency_supply[s] for s in scenarios},
        )
        result.validate()
        return result

    def mean_scenario(self, name: str = "mean") -> "ProcurementData":
        """Collapse the finite set to one componentwise mean scenario."""

        def average(source: ScenarioSeries) -> dict[str, dict[str, tuple[float, ...]]]:
            return {
                name: {
                    item: tuple(
                        fmean(source[scenario][item][t] for scenario in self.scenarios)
                        for t in range(self.periods)
                    )
                    for item in self.items
                }
            }

        result = replace(
            self,
            scenarios=(name,),
            demand=average(self.demand),
            emergency_price=average(self.emergency_price),
            emergency_supply=average(self.emergency_supply),
        )
        result.validate()
        return result

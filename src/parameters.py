"""Dependency-free parameter primitives established in phase 1."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelDimensions:
    """Core dimensions for a finite-scenario, age-indexed model."""

    items: int
    periods: int
    scenarios: int
    shelf_life: int

    def validate(self) -> None:
        for name, value in (
            ("items", self.items),
            ("periods", self.periods),
            ("scenarios", self.scenarios),
            ("shelf_life", self.shelf_life),
        ):
            if value <= 0:
                raise ValueError(f"{name} must be positive, got {value}")


@dataclass(frozen=True)
class BudgetAllocation:
    """A first-stage allocation with residual funds assigned to reserve."""

    total_budget: float
    regular_commitment: float

    def validate(self, tolerance: float = 1.0e-9) -> None:
        if self.total_budget < -tolerance:
            raise ValueError("total_budget must be nonnegative")
        if self.regular_commitment < -tolerance:
            raise ValueError("regular_commitment must be nonnegative")
        if self.regular_commitment > self.total_budget + tolerance:
            raise ValueError("regular_commitment cannot exceed total_budget")

    @property
    def reserve(self) -> float:
        self.validate()
        return max(0.0, self.total_budget - self.regular_commitment)

    @property
    def reserve_ratio(self) -> float:
        self.validate()
        if self.total_budget == 0:
            return 0.0
        return self.reserve / self.total_budget

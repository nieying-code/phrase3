"""Tests for the exploratory reserve-activation diagnostic protocol."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import yaml

from src.model_data import ProcurementData
from src.run_reserve_activation_diagnostic import scaled_economic_data


CONFIG = Path("configs/phase6_reserve_activation_diagnostic.yaml")


def _data() -> ProcurementData:
    return ProcurementData(
        items=("item",),
        periods=2,
        scenarios=("s0",),
        budget=10.0,
        shelf_life={"item": 2},
        initial_inventory={"item": (0.0, 0.0)},
        storage_capacity=(10.0, 10.0),
        regular_price={"item": (1.0, 2.0)},
        demand={"s0": {"item": (3.0, 4.0)}},
        emergency_price={"s0": {"item": (2.0, 4.0)}},
        emergency_supply={"s0": {"item": (5.0, 6.0)}},
        shortage_penalty={"item": 20.0},
        waste_penalty={"item": 0.5},
    )


def test_scaled_economic_data_changes_only_requested_economics() -> None:
    original = _data()
    changed = scaled_economic_data(
        original,
        emergency_price_scale=0.75,
        waste_penalty_multiplier=4.0,
    )
    assert changed.emergency_price == {"s0": {"item": (1.5, 3.0)}}
    assert changed.waste_penalty == {"item": 2.0}
    for field in (
        "items",
        "periods",
        "scenarios",
        "budget",
        "shelf_life",
        "initial_inventory",
        "storage_capacity",
        "regular_price",
        "demand",
        "emergency_supply",
        "shortage_penalty",
    ):
        assert getattr(changed, field) == getattr(original, field)


def test_diagnostic_design_is_small_prespecified_and_nonformal() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["protocol_id"] == "phase6_reserve_activation_diagnostic_v1"
    assert config["status"] == "exploratory_diagnostic_only"
    assert config["design"] == {
        "tier_id": "V1",
        "seed": 20260723,
        "budget_factor": 1.10,
        "reserve_activation_tolerance": 1.0e-7,
        "consistency_tolerance": 1.0e-5,
        "solver_call_time_limit_seconds": 300,
        "solver_threads": 1,
    }
    assert config["reserve_frontier_ratios"] == [
        0.0,
        0.0025,
        0.005,
        0.01,
        0.02,
        0.05,
        0.10,
    ]
    assert config["mechanism_surface"] == {
        "emergency_price_scales": [1.0, 0.9, 0.75, 0.5],
        "waste_penalty_multipliers": [1.0, 4.0, 16.0, 64.0],
    }
    assert config["markup_attribution"]["markup_means"] == [0.15, 0.55]
    assert config["claim_boundary"] == {
        "formal_evidence": False,
        "changes_frozen_matrix": False,
        "replaces_e5": False,
        "permitted_use": "mechanism_diagnosis_and_route_selection_only",
        "positive_control_is_empirical_evidence": False,
    }


def test_scaled_economic_data_rejects_nonpositive_scales() -> None:
    original = _data()
    for price_scale, waste_multiplier in ((0.0, 1.0), (1.0, 0.0)):
        try:
            scaled_economic_data(
                original,
                emergency_price_scale=price_scale,
                waste_penalty_multiplier=waste_multiplier,
            )
        except ValueError:
            pass
        else:
            raise AssertionError("nonpositive diagnostic scale was accepted")


def test_procurement_data_replace_does_not_mutate_baseline() -> None:
    original = _data()
    changed = replace(original, shortage_penalty={"item": 99.0})
    assert original.shortage_penalty == {"item": 20.0}
    assert changed.shortage_penalty == {"item": 99.0}

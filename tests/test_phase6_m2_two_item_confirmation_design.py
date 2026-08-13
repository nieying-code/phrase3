from __future__ import annotations

import itertools
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_two_item_confirmation.yaml"


def test_two_item_confirmation_design_is_exact_and_not_executable() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert config["protocol_id"] == "phase6_m2_two_item_confirmation_design_v1_0"
    assert config["status"] == "candidate_design_pending_review"
    design = config["confirmation_preregistration"]
    assert design["execution_allowed_in_this_revision"] is False
    seeds = tuple(design["seeds"])
    betas = tuple(float(value) for value in design["beta"])
    profiles = tuple(design["profiles"])
    assert seeds == (2026081301, 2026081302, 2026081303, 2026081304, 2026081305)
    assert betas == (1.1, 1.3)
    assert profiles == ("C0", "C1", "T03")
    cases = set(itertools.product(seeds, betas, profiles))
    assert len(cases) == design["configuration_count"] == 30
    assert design["profiles"]["C0"]["enabled"] is False
    assert design["profiles"]["C0"]["loss_scale"] == 0.0
    assert design["profiles"]["C1"]["loss_scale"] == 0.2
    assert design["profiles"]["T03"]["loss_scale"] == 0.3


def test_confirmation_seeds_are_disjoint_from_all_existing_project_seeds() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    selected = {str(value) for value in config["confirmation_preregistration"]["seeds"]}
    observed: set[str] = set()
    for folder in (ROOT / "configs", ROOT / "docs", ROOT / "src", ROOT / "tests"):
        for path in folder.rglob("*"):
            if not path.is_file() or path.resolve() == CONFIG.resolve():
                continue
            if "phase6_m2_two_item_confirmation" in path.name:
                continue
            if path.suffix.lower() not in {".yaml", ".yml", ".json", ".md", ".py"}:
                continue
            observed.update(re.findall(r"\b20\d{8}\b", path.read_text(encoding="utf-8", errors="ignore")))
    assert selected.isdisjoint(observed)


def test_item_heterogeneity_and_shared_pool_evidence_are_frozen() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    model = config["scientific_model"]
    assert model["item_count"] == 2 and model["periods"] == 6
    items = model["items"]
    assert [item["id"] for item in items] == ["relief_food_1", "relief_food_2"]
    assert [item["shelf_life_periods"] for item in items] == [6, 4]
    assert [item["demand_multiplier"] for item in items] == [1.0, 0.75]
    assert [item["regular_price_multiplier"] for item in items] == [1.0, 1.2]
    assert [item["supply_vulnerability_multiplier"] for item in items] == [0.8, 1.2]
    assert model["shared_emergency_reserve_pool"] is True
    gate = config["machine_gates"]
    assert gate["per_beta_confirmation"] == {
        "C0_substantive_activation_seed_count_maximum": 0,
        "T03_substantive_activation_seed_count_minimum": 3,
        "T03_moderate_seed_count_minimum": 3,
        "T03_activation_seed_count_must_be_strictly_greater_than_C1": True,
        "cost_service_or_manual_trend_selection_forbidden": True,
    }
    cross = gate["shared_reserve_cross_item_evidence"]
    assert cross["minimum_seed_count"] == 3
    assert cross["both_items_each_have_positive_emergency_spend_in_at_least_one_scenario"] is True
    assert cross["minimum_scenarios_with_positive_total_emergency_spend"] == 2
    assert cross["minimum_absolute_item1_emergency_spend_share_range"] == 1e-4
    assert gate["overall_confirmation"]["formal_extension_authorized"] is False


def test_design_has_zero_execution_and_no_runner_artifact() -> None:
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert all(value in (False, 0) for value in config["execution_boundaries"].values())
    assert not (ROOT / "src/phase6_m2_two_item_confirmation.py").exists()
    assert not (ROOT / "src/run_phase6_m2_two_item_confirmation.py").exists()

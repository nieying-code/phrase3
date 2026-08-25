from __future__ import annotations

import copy
import csv
import json
from pathlib import Path

import pytest

from src.phase6_m2_algorithm_performance_formal_results import (
    canonical_sha,
    validate_compact_audit,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_formal_results_v1_1_audit.json"
CSV_PATH = ROOT / "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_formal_results_v1_1_seed_statistics.csv"


def _load() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def test_compact_evidence_independently_closes_20_40_240_and_statistics() -> None:
    audit = _load()
    validate_compact_audit(audit)
    assert audit["status"] == "passed"
    assert audit["aggregate"] == {
        "required_primary_sequence_count": 20,
        "completed_primary_sequence_count": 20,
        "required_budget_pair_count": 40,
        "completed_budget_pair_count": 40,
        "required_algorithm_execution_count": 240,
        "completed_algorithm_execution_count": 240,
        "negative_reported_gap_count": 36,
        "minimum_reported_gap": -1.4551915228366852e-11,
        "maximum_gap_identity_difference": 0.0,
        "maximum_objective_difference": 0.0,
        "maximum_sampled_peak_RSS_MiB": 93.6640625,
        "missing_case_ids": [], "duplicate_case_ids": [],
        "failed_primary_run_ids": [], "invalid_primary_runs": [],
        "diagnostic_run_ids": [], "common_random_number_mismatches": [],
        "formal_algorithm_performance_gate_passed": True,
        "other_experiments_authorized": False,
    }


def test_execution_identity_fingerprints_and_global_artifacts_are_locked() -> None:
    audit = _load()
    assert audit["execution_identity"] == {
        "branch": "main", "upstream_remote": "origin",
        "upstream_merge": "refs/heads/main",
        "head": "d6190e058c07b5c8ea962d8ca0b1757731c564ac",
        "remote_main": "d6190e058c07b5c8ea962d8ca0b1757731c564ac",
        "tree": "a3bed2cc3b0dfe671016a3bf64e5913fa77a7f71",
        "reviewed_runner_merge_commit": "1e855af3936cc19c6a6ab75a7b59efcf357a85b2",
    }
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "ce001f9fdce3eae0f9a14a99093186e90072fb945e546406305764e765bb0734",
        "e3_component_sha256": "2f615dee1e32ef1faab941229c809f133fb22ba162567686f51fda4daec3b7c4",
        "family_component_sha256": "bf2f5f6f451f0c9ce0e46b5cb72bffea6e8c3dc55dc5e44a55f85ba02e8765ee",
        "runner_config_sha256": "3063001a09d0441d4592dbfc5fcea2deffc6abadf04852cdd239fc4f421ab9c1",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
        "algorithm_performance_orchestrator_sha256": "9a8b8e863498d13dbdd0e4a80aba1c4a59b84eaa100c99c54afeebf8c48b5a11",
    }
    assert audit["global_artifacts"] == {
        "formal_projection_sha256": "23b0d08b3a9b51c5df84c1e30e80eb74beb6d3f6ba7d427105d96906f29aea72",
        "formal_run_registry_sha256": "b455c045968244567555d81692f7aba7fbfb392430fe6132b5f16c047f315271",
        "run_evidence_mapping_sha256": "94299372aa35d052719b3338bbc8cf55e1de52065ac42b30c0de5b7b6fdb7614",
    }


def test_pre_registered_estimands_and_interpretation_boundaries_are_exact() -> None:
    audit = _load()
    statistics = audit["formal_statistics"]
    assert statistics["primary_estimand"] == {
        "name": "T03_beta_1_3_cross_budget_transfer_speedup",
        "point_estimate": 1.0221078819791511,
        "bootstrap_95_percentile_CI": [1.0134009999283604, 1.595600165601707],
        "beta_1_1_excluded_because_no_prior_budget_transfer": True,
    }
    assert statistics["confirmatory_disruption_enhancement_estimand"] == {
        "name": "paired_T03_vs_C0_beta_1_3_speedup_ratio",
        "point_estimate": 1.0032042250569733,
        "bootstrap_95_percentile_CI": [0.8285805175720159, 1.0201143916525728],
    }
    assert statistics["secondary_end_to_end_two_budget_speedup"] == {
        "C0": 1.0913285526040228, "T03": 1.0175336241128825,
    }
    assert statistics["reliable_M2_T03_acceleration_gate_passed"] is True
    assert statistics["supply_disruption_enhances_warm_start_benefit_gate_passed"] is False
    assert audit["interpretation_boundaries"] == {
        "reliable_M2_T03_cross_budget_acceleration_supported": True,
        "supply_disruption_enhances_warm_start_benefit_supported": False,
        "M2_faster_than_M0_claim_permitted": False,
        "pure_SPW_effect_or_pure_warm_start_effect_claim_permitted": False,
    }


def test_seed_csv_is_bound_to_the_ten_seed_statistics() -> None:
    audit = _load()
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert [int(row["seed"]) for row in rows] == list(range(2026091101, 2026091111))
    source = {row["seed"]: row for row in audit["formal_statistics"]["seed_level_values"]}
    for row in rows:
        item = source[int(row["seed"])]
        assert float(row["T03_beta_1_3_speedup"]) == item["profiles"]["T03"]["beta_1_3"]["speedup_cold_over_warm"]
        assert float(row["paired_T03_minus_C0_beta_1_3_log_speedup"]) == item["paired_T03_minus_C0_beta_1_3_log_speedup"]


@pytest.mark.parametrize("field", ["reported_optimality_gap", "objective", "subprocess_wall_seconds"])
def test_repetition_evidence_tampering_is_rejected(field: str) -> None:
    audit = _load()
    tampered = copy.deepcopy(audit)
    method = tampered["runs"][0]["comparisons"][0]["methods"]["cold"][0]
    method[field] = -2.0 if field != "objective" else method[field] + 1.0
    with pytest.raises(ValueError):
        validate_compact_audit(tampered)


def test_no_adjacent_experiment_was_authorized_or_run() -> None:
    audit = _load()
    assert audit["execution_boundaries"] == {
        "M2_1_runs": 0, "M0_E3_runs": 0, "other_formal_experiment_runs": 0,
    }


@pytest.mark.parametrize(
    ("target", "replacement"),
    (
        ("transfer_list", []),
        ("transfer_count", 0),
        ("reuse_rate", 0.0),
        ("source_budget", 0.0),
        ("source_state", ["tampered_scenario"]),
        ("active_or_worst", []),
    ),
)
def test_synchronized_transfer_evidence_tampering_is_rejected(
    target: str, replacement: object,
) -> None:
    audit = _load()
    tampered = copy.deepcopy(audit)
    first, second = tampered["runs"][0]["comparisons"]
    warm = second["methods"]["warm"][0]
    if target == "transfer_list":
        warm["transferred_exact_scenarios"] = replacement
    elif target == "transfer_count":
        warm["transferred_exact_scenario_count"] = replacement
    elif target == "reuse_rate":
        warm["transferred_scenario_reuse_rate"] = replacement
    elif target == "source_budget":
        warm["transfer_source_budget"] = replacement
    elif target == "source_state":
        first["transferred_states"]["1"]["active_scenarios"] = replacement
        new_hash = canonical_sha(first["transferred_states"]["1"])
        first["transferred_states_sha256"]["1"] = new_hash
        warm["transfer_source_state_sha256"] = new_hash
    else:
        warm["transferred_scenarios_becoming_active_or_worst"] = replacement
        warm["transferred_scenarios_becoming_active_or_worst_count"] = len(replacement)
    with pytest.raises(ValueError):
        validate_compact_audit(tampered)

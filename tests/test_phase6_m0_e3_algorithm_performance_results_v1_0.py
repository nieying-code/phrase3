from __future__ import annotations

import csv
import copy
import hashlib
import json
import math
from pathlib import Path
import statistics

import numpy as np
import pytest

from src.phase6_m0_algorithm_performance_results import (
    PAIR_FIELDS,
    canonical_sha256,
    validate_compact_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "docs/handoffs/2026-08-23_phase6_m0_e3_algorithm_performance_results_v1_0_audit.json"
PAIR_PATH = ROOT / "docs/handoffs/2026-08-23_phase6_m0_e3_algorithm_performance_results_v1_0_pairs.csv"
SEEDS = tuple(range(2026072401, 2026072411))
TIER_SEEDS = {"V1": SEEDS[:3], "V2": SEEDS, "P1": SEEDS[:5], "P2": SEEDS[:3]}
TIER_EXECUTIONS = {"V1": 18, "V2": 180, "P1": 30, "P2": 18}
GLOBAL_HASHES = {
    "run_registry_sha256": "c97846af69f3b8ce26ac9bb2c02d058683b5656da1c8e4988983311b2d599430",
    "algorithm_performance_sha256": "3b2ab4da0a2bdc0c242670fd655d5013f3d2b398d3b239705c66e36fb055ab5d",
    "projection_sha256": "1449284052a02e485fb32b6abf76934a2d47adaa913d0aa5fc239c069658faa1",
    "status_summary_sha256": "1449284052a02e485fb32b6abf76934a2d47adaa913d0aa5fc239c069658faa1",
    "run_artifact_mapping_sha256": "300002d21cfeb2cf20c358533a9e122e4c4ea319dde3c98a42c6c1b5d5bfc94e",
    "technical_repetition_evidence_mapping_sha256": "113ab3ff80c8cd3494054a41a3e6973f223fe8040c5f0a5104c37413f52d4633",
}


def _audit() -> dict:
    return json.loads(AUDIT_PATH.read_text(encoding="utf-8"))


def _canonical_sha(value: object) -> str:
    data = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def _file_sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _percentile_ci(values: np.ndarray) -> list[float]:
    return [float(v) for v in np.percentile(values, [2.5, 97.5], method="linear")]


def test_exact_execution_identity_counts_and_artifacts() -> None:
    audit = _audit()
    assert audit["source"] == {
        "execution_git_sha": "23b1f1d01ee88d08c981b250dfeacbc8ebb9d20c",
        "execution_git_tree_sha": "e5cb644536a66c8bd65d8a74a98ceb0272cc667e",
        "run_id_prefix": "m0e3_formal_v1_20260823",
        "output_root": "outputs/phase6_m0_e3_algorithm_performance_v1_0",
    }
    assert audit["counts"] == {
        "primary_run_count": 21, "budget_pair_count": 63,
        "algorithm_execution_count": 246,
        "technical_repetition_record_count": 246,
        "tier_primary_run_counts": {key: len(value) for key, value in TIER_SEEDS.items()},
        "tier_algorithm_execution_counts": TIER_EXECUTIONS,
        "failed_primary_run_count": 0, "invalid_primary_run_count": 0,
        "duplicate_primary_run_count": 0, "diagnostic_run_count": 0,
    }
    expected_ids = {
        f"m0e3_formal_v1_20260823_M0_E3_{tier}_seed{seed}"
        for tier, seeds in TIER_SEEDS.items() for seed in seeds
    }
    assert {row["run_id"] for row in audit["runs"]} == expected_ids
    for row in audit["runs"]:
        assert row["seed"] in TIER_SEEDS[row["tier_id"]]
        assert row["status"] == "optimal" and row["execution_mode"] == "formal"
        assert row["budget_pair_count"] == 3
        assert row["algorithm_execution_count"] == (18 if row["tier_id"] == "V2" else 6)
        assert row["working_tree_dirty"] is False
        assert row["solver"] == {
            "preference": ["gurobi"], "selected": "gurobi_direct",
            "version": "13.0.2.0", "threads": 1,
        }
    mapping = {
        row["run_id"]: {
            key: row[key] for key in (
                "result_sha256", "manifest_sha256", "status_summary_sha256",
                "training_scenarios_sha256", "resolved_run_sha256",
            )
        } for row in audit["runs"]
    }
    assert _canonical_sha(mapping) == GLOBAL_HASHES["run_artifact_mapping_sha256"]
    assert audit["global_artifacts"] == GLOBAL_HASHES
    assert _file_sha(PAIR_PATH) == audit["compact_artifacts"]["budget_pair_csv_sha256"]


def test_pair_matrix_objectives_repetitions_and_numerical_closure() -> None:
    audit = _audit()
    pairs = audit["pairs"]
    assert len(pairs) == 63
    identities = {(row["tier_id"], row["seed"], row["budget_index"]) for row in pairs}
    expected = {(tier, seed, budget) for tier, seeds in TIER_SEEDS.items() for seed in seeds for budget in range(3)}
    assert identities == expected
    with PAIR_PATH.open(encoding="utf-8", newline="") as handle:
        csv_rows = list(csv.DictReader(handle))
    assert len(csv_rows) == 63
    audit_pairs = {(row["run_id"], row["budget_index"]): row for row in pairs}
    for row in csv_rows:
        pair = audit_pairs[(row["run_id"], int(row["budget_index"]))]
        assert all(row[field] == str(pair[field]) for field in PAIR_FIELDS)
    executions = 0
    for row in pairs:
        repetitions = 3 if row["tier_id"] == "V2" else 1
        assert row["timing_repetitions"] == repetitions
        executions += 2 * repetitions
        assert row["objective_difference"] == 0.0
        assert row["objective_difference"] <= row["consistency_tolerance"]
        assert math.isfinite(row["cold_gap"]) and math.isfinite(row["warm_gap"])
        assert row["cold_gap"] >= -row["consistency_tolerance"]
        assert row["warm_gap"] >= -row["consistency_tolerance"]
        assert row["cold_lower_bound"] <= row["cold_upper_bound"] + row["consistency_tolerance"]
        assert row["warm_lower_bound"] <= row["warm_upper_bound"] + row["consistency_tolerance"]
        assert row["cold_recourse_lp_solve_count"] == row["cold_iterations"] * row["training_scenario_count"]
        assert row["warm_recourse_lp_solve_count"] == row["warm_iterations"] * row["training_scenario_count"]
        assert 0.0 <= row["warm_scenario_reuse_rate"] <= 1.0
    assert executions == 246
    assert audit["aggregate"]["maximum_objective_difference"] == 0.0
    assert audit["aggregate"]["maximum_within_technical_repeat_objective_difference"] == 0.0
    assert audit["aggregate"]["all_objectives_within_frozen_tolerance"] is True


def test_all_246_technical_repetitions_reconstruct_medians_and_source_mapping() -> None:
    audit = _audit()
    validate_compact_evidence(audit)
    evidence = audit["technical_repetition_evidence"]
    assert len(evidence) == 63
    repetitions = []
    middle_budget_pairs = []
    for row in evidence:
        by_label = {
            f"{repetition['algorithm']}_r{repetition['repetition_index']:02d}": repetition
            for repetition in row["cold_repetitions"] + row["warm_repetitions"]
        }
        repetitions.extend(by_label[label] for label in row["execution_order"])
        expected_modes = ("cold", "warm") if row["budget_index"] % 2 == 0 else ("warm", "cold")
        expected_order = [
            f"{mode}_r{index:02d}"
            for mode in expected_modes
            for index in range(1, (3 if row["tier_id"] == "V2" else 1) + 1)
        ]
        assert row["execution_order"] == expected_order
        if row["budget_index"] == 1:
            middle_budget_pairs.append(row)
    assert len(repetitions) == 246
    assert [row["execution_index"] for row in repetitions] == list(range(1, 247))
    assert len(middle_budget_pairs) == 21
    assert all(row["execution_order"][0] == "warm_r01" for row in middle_budget_pairs)
    assert all(row["status"] == "optimal" for row in repetitions)
    assert all(math.isfinite(row["subprocess_wall_seconds"]) and row["subprocess_wall_seconds"] > 0 for row in repetitions)
    assert all(math.isfinite(row["objective"]) for row in repetitions)
    assert audit["aggregate"]["maximum_within_technical_repeat_objective_difference"] == 0.0

    mapping = {}
    for row in evidence:
        mapping.setdefault(row["run_id"], {
            "result_sha256": row["source_result_sha256"], "budget_pairs": [],
        })["budget_pairs"].append({
            "budget_index": row["budget_index"],
            "execution_order": row["execution_order"],
            "cold_repetitions": row["cold_repetitions"],
            "warm_repetitions": row["warm_repetitions"],
        })
    assert canonical_sha256(mapping) == GLOBAL_HASHES["technical_repetition_evidence_mapping_sha256"]


@pytest.mark.parametrize("field", ["time", "objective", "order", "source_result"])
def test_technical_repetition_tampering_is_rejected(field: str) -> None:
    audit = copy.deepcopy(_audit())
    row = audit["technical_repetition_evidence"][0]
    if field == "time":
        row["cold_repetitions"][0]["subprocess_wall_seconds"] += 0.125
    elif field == "objective":
        row["cold_repetitions"][0]["objective"] += 1.0
    elif field == "order":
        row["execution_order"] = list(reversed(row["execution_order"]))
    else:
        row["source_result_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        validate_compact_evidence(audit)


def test_frozen_seed_level_statistics_and_interpretation_boundaries() -> None:
    audit = _audit()
    pairs = audit["pairs"]
    summaries = audit["tier_summaries"]
    for tier, seeds in TIER_SEEDS.items():
        tier_rows = [row for row in pairs if row["tier_id"] == tier]
        seed_logs = []
        seed_diffs = []
        for seed in seeds:
            rows = [row for row in tier_rows if row["seed"] == seed]
            seed_logs.append(float(statistics.median(math.log(row["cold_seconds"] / row["warm_seconds"]) for row in rows)))
            seed_diffs.append(float(statistics.median(row["cold_seconds"] - row["warm_seconds"] for row in rows)))
        summary = summaries[tier]
        assert summary["within_seed_median_log_speedups"] == pytest.approx(seed_logs)
        assert summary["conditional_sequence_speedup"] == pytest.approx(math.exp(statistics.median(seed_logs)))
        assert summary["median_within_seed_cold_minus_warm_seconds"] == pytest.approx(statistics.median(seed_diffs))
        assert summary["cold_completion_rate"] == summary["warm_completion_rate"] == summary["joint_pair_completion_rate"] == 1.0
        if tier in {"V2", "P1"}:
            rng = np.random.Generator(np.random.PCG64DXSM(2026090602))
            values = np.asarray(seed_logs)
            draws = rng.integers(0, len(values), size=(10000, len(values)), endpoint=False)
            expected_ci = _percentile_ci(np.exp(np.median(values[draws], axis=1)))
            assert summary["sequence_speedup_bootstrap_95_percentile_CI"] == pytest.approx(expected_ci)
    assert summaries["V1"]["reporting_role"] == "correctness_only"
    assert summaries["V2"]["reporting_role"] == "primary_inferential"
    assert summaries["V2"]["sequence_speedup_bootstrap_95_percentile_CI"][0] < 1 < summaries["V2"]["sequence_speedup_bootstrap_95_percentile_CI"][1]
    assert summaries["P1"]["reporting_role"] == "limited_inferential"
    assert summaries["P2"]["reporting_role"] == "descriptive_only"
    assert audit["interpretation_boundaries"] == {
        "comparison": "complete_standard_CCG_cold_vs_complete_SPW_CCG_cross_budget_warm_workflows",
        "pure_SPW_effect_identified": False, "pure_warm_start_effect_identified": False,
        "M2_speed_comparison_performed": False, "P2_inference_permitted": False,
    }


def test_fingerprints_gate_and_stop_boundary() -> None:
    audit = _audit()
    assert audit["fingerprints"] == {
        "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
        "e3_component_sha256": "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e",
        "runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
        "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
        "algorithm_performance_orchestrator_sha256": "003b14b60ed06e1993bddcd2bd0704eafd9b2a7a7e8a42819a5c723c52f3f0cc",
    }
    assert audit["aggregate"]["M0_E3_algorithm_performance_gate_passed"] is True
    assert audit["stop_boundary"] == {
        "M2_performance_runs": 0, "M2_1_additional_runs": 0,
        "other_formal_experiments_started": False,
    }

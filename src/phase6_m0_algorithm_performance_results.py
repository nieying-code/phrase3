"""Build compact, reproducible evidence from finalized M0 E3 artifacts."""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

import numpy as np

from .reproducibility import sha256_file


EXPECTED_TIER_RUNS = {"V1": 3, "V2": 10, "P1": 5, "P2": 3}
EXPECTED_TIER_EXECUTIONS = {"V1": 18, "V2": 180, "P1": 30, "P2": 18}
PAIR_FIELDS = (
    "run_id", "tier_id", "seed", "budget_index", "budget",
    "timing_repetitions", "cold_seconds", "warm_seconds", "speedup_cold_over_warm",
    "cold_objective", "warm_objective", "objective_difference", "consistency_tolerance",
    "cold_iterations", "warm_iterations", "cold_initial_scenarios", "warm_initial_scenarios",
    "cold_final_scenarios", "warm_final_scenarios", "cold_master_seconds", "warm_master_seconds",
    "cold_oracle_seconds", "warm_oracle_seconds", "cold_peak_memory_mb", "warm_peak_memory_mb",
    "cold_lower_bound", "warm_lower_bound", "cold_upper_bound", "warm_upper_bound",
    "cold_gap", "warm_gap", "cold_master_solve_count", "warm_master_solve_count",
    "cold_recourse_lp_solve_count", "warm_recourse_lp_solve_count",
    "warm_reused_scenario_count", "warm_scenario_reuse_rate",
    "training_scenario_count",
)


def canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _median(values: Iterable[float]) -> float:
    return float(statistics.median(tuple(values)))


def _percentile_interval(values: np.ndarray) -> list[float]:
    return [
        float(value)
        for value in np.percentile(values, [2.5, 97.5], method="linear")
    ]


def _cluster_speedup_interval(seed_values: list[float], *, seed: int) -> list[float]:
    rng = np.random.Generator(np.random.PCG64DXSM(seed))
    source = np.asarray(seed_values, dtype=float)
    draws = rng.integers(0, len(source), size=(10000, len(source)), endpoint=False)
    statistics_ = np.exp(np.median(source[draws], axis=1))
    return _percentile_interval(statistics_)


def _fixed_budget_intervals(rows: list[dict[str, Any]]) -> dict[str, list[float]]:
    rng = np.random.Generator(np.random.PCG64DXSM(2026090601))
    result: dict[str, list[float]] = {}
    for budget_index in range(3):
        values = np.asarray([
            math.log(float(row["speedup_cold_over_warm"]))
            for row in rows if int(row["budget_index"]) == budget_index
        ])
        draws = rng.integers(0, len(values), size=(10000, len(values)), endpoint=False)
        result[str(budget_index)] = _percentile_interval(np.exp(np.median(values[draws], axis=1)))
    return result


def _representative(mode: dict[str, Any]) -> dict[str, Any]:
    representative = mode.get("representative")
    if not isinstance(representative, dict) or representative.get("status") != "optimal":
        raise ValueError("missing optimal representative repetition")
    return representative


def _pair_from_result(
    result: dict[str, Any], comparison: dict[str, Any],
    *, prior_historical_scenarios: set[str],
) -> dict[str, Any]:
    cold = _representative(comparison["cold"])
    warm = _representative(comparison["warm"])
    cold_ccg = cold["ccg_result"]
    warm_ccg = warm["ccg_result"]
    cold_seconds = _median(float(row["subprocess_wall_seconds"]) for row in comparison["cold"]["repetitions"])
    warm_seconds = _median(float(row["subprocess_wall_seconds"]) for row in comparison["warm"]["repetitions"])
    cold_objective = _median(float(row["ccg_result"]["objective"]) for row in comparison["cold"]["repetitions"])
    warm_objective = _median(float(row["ccg_result"]["objective"]) for row in comparison["warm"]["repetitions"])
    warm_initial = {str(value) for value in warm_ccg["initial_scenario_set"]}
    reused = len(warm_initial & prior_historical_scenarios)
    scenario_count = int(cold["scenario_count"])
    return {
        "run_id": result["run_id"],
        "tier_id": result["tier_id"],
        "seed": int(result["seed"]),
        "budget_index": int(comparison["budget_index"]),
        "budget": float(comparison["budget"]),
        "timing_repetitions": int(comparison["planned_repetitions"]),
        "cold_seconds": cold_seconds,
        "warm_seconds": warm_seconds,
        "speedup_cold_over_warm": cold_seconds / warm_seconds,
        "cold_objective": cold_objective,
        "warm_objective": warm_objective,
        "objective_difference": abs(cold_objective - warm_objective),
        "consistency_tolerance": float(comparison["consistency_tolerance"]),
        "cold_iterations": int(cold_ccg["iterations"]),
        "warm_iterations": int(warm_ccg["iterations"]),
        "cold_initial_scenarios": len(cold_ccg["initial_scenario_set"]),
        "warm_initial_scenarios": len(warm_ccg["initial_scenario_set"]),
        "cold_final_scenarios": len(cold_ccg["final_scenario_set"]),
        "warm_final_scenarios": len(warm_ccg["final_scenario_set"]),
        "cold_master_seconds": float(cold_ccg["master_runtime_seconds"]),
        "warm_master_seconds": float(warm_ccg["master_runtime_seconds"]),
        "cold_oracle_seconds": float(cold_ccg["oracle_runtime_seconds"]),
        "warm_oracle_seconds": float(warm_ccg["oracle_runtime_seconds"]),
        "cold_peak_memory_mb": float(cold["peak_memory_mb"]),
        "warm_peak_memory_mb": float(warm["peak_memory_mb"]),
        "cold_lower_bound": float(cold_ccg["lower_bound"]),
        "warm_lower_bound": float(warm_ccg["lower_bound"]),
        "cold_upper_bound": float(cold_ccg["upper_bound"]),
        "warm_upper_bound": float(warm_ccg["upper_bound"]),
        "cold_gap": float(cold_ccg["gap"]), "warm_gap": float(warm_ccg["gap"]),
        "cold_master_solve_count": int(cold_ccg["iterations"]),
        "warm_master_solve_count": int(warm_ccg["iterations"]),
        "cold_recourse_lp_solve_count": int(cold_ccg["iterations"]) * scenario_count,
        "warm_recourse_lp_solve_count": int(warm_ccg["iterations"]) * scenario_count,
        "warm_reused_scenario_count": reused,
        "warm_scenario_reuse_rate": (reused / len(warm_initial)) if warm_initial else 0.0,
        "training_scenario_count": scenario_count,
    }


def _tier_summary(rows: list[dict[str, Any]], tier_id: str) -> dict[str, Any]:
    tier = [row for row in rows if row["tier_id"] == tier_id]
    seeds = sorted({int(row["seed"]) for row in tier})
    within_seed_logs = []
    within_seed_differences = []
    for seed in seeds:
        seed_rows = [row for row in tier if int(row["seed"]) == seed]
        within_seed_logs.append(_median(math.log(float(row["speedup_cold_over_warm"])) for row in seed_rows))
        within_seed_differences.append(_median(float(row["cold_seconds"]) - float(row["warm_seconds"]) for row in seed_rows))
    summary = {
        "reporting_role": {
            "V1": "correctness_only", "V2": "primary_inferential",
            "P1": "limited_inferential", "P2": "descriptive_only",
        }[tier_id],
        "training_seed_count": len(seeds),
        "planned_pair_count": len(tier),
        "cold_completion_rate": 1.0,
        "warm_completion_rate": 1.0,
        "joint_pair_completion_rate": 1.0,
        "conditional_sequence_speedup": math.exp(_median(within_seed_logs)),
        "median_within_seed_cold_minus_warm_seconds": _median(within_seed_differences),
        "median_cold_seconds": _median(float(row["cold_seconds"]) for row in tier),
        "median_warm_seconds": _median(float(row["warm_seconds"]) for row in tier),
        "median_cold_iterations": _median(float(row["cold_iterations"]) for row in tier),
        "median_warm_iterations": _median(float(row["warm_iterations"]) for row in tier),
        "median_warm_scenario_reuse_rate_after_first_budget": _median(
            float(row["warm_scenario_reuse_rate"])
            for row in tier if int(row["budget_index"]) > 0
        ),
        "maximum_peak_memory_mb": max(max(float(row["cold_peak_memory_mb"]), float(row["warm_peak_memory_mb"])) for row in tier),
        "maximum_objective_difference": max(float(row["objective_difference"]) for row in tier),
        "within_seed_median_log_speedups": within_seed_logs,
    }
    if tier_id in {"V2", "P1"}:
        summary["sequence_speedup_bootstrap_95_percentile_CI"] = _cluster_speedup_interval(
            within_seed_logs, seed=2026090602,
        )
    if tier_id == "V2":
        summary["fixed_budget_speedup_bootstrap_95_percentile_CI"] = _fixed_budget_intervals(tier)
    return summary


def build_audit(*, root: Path, output_root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = output_root / "formal/primary/experiments/phase6"
    registry_path = base / "run_registry.csv"
    performance_path = base / "algorithm_performance.csv"
    projection_path = base / "algorithm_performance_projection.json"
    status_path = base / "algorithm_performance_status_summary.json"
    registry = _read_csv(registry_path)
    performance = _read_csv(performance_path)
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    if len(registry) != 21 or len(performance) != 246:
        raise ValueError("formal M0 E3 counts are not 21/246")
    if projection.get("M0_E3_algorithm_performance_gate_passed") is not True:
        raise ValueError("formal M0 E3 gate did not pass")
    if any(row["status"] != "optimal" or row["execution_mode"] != "formal" for row in registry):
        raise ValueError("registry contains a nonoptimal or nonformal primary")
    if any(row["status"] != "optimal" for row in performance):
        raise ValueError("performance table contains a nonoptimal execution")

    runs: list[dict[str, Any]] = []
    pairs: list[dict[str, Any]] = []
    expected_git = {"commit_sha": "23b1f1d01ee88d08c981b250dfeacbc8ebb9d20c", "tree_sha": "e5cb644536a66c8bd65d8a74a98ceb0272cc667e"}
    for row in registry:
        manifest_path = Path(row["manifest_path"])
        result_path = Path(row["result_path"])
        status_summary_path = result_path.parent / "status_summary.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest["artifact_state"] != "finalized" or manifest["git"]["commit_sha"] != expected_git["commit_sha"] or manifest["git"]["tree_sha"] != expected_git["tree_sha"]:
            raise ValueError("manifest execution identity mismatch")
        if manifest["result_sha256"] != sha256_file(result_path):
            raise ValueError("result hash mismatch")
        result = json.loads(result_path.read_text(encoding="utf-8"))
        if result["status"] != "optimal" or len(result["comparisons"]) != 3:
            raise ValueError("result is not a complete three-budget run")
        run_pairs = []
        prior_historical: set[str] = set()
        for comparison in result["comparisons"]:
            run_pairs.append(
                _pair_from_result(
                    result, comparison,
                    prior_historical_scenarios=prior_historical,
                )
            )
            prior_historical = {
                str(value)
                for value in comparison["transferred_state"]["historical_adversarial_scenarios"]
            }
        if any(pair["objective_difference"] > pair["consistency_tolerance"] for pair in run_pairs):
            raise ValueError("cold/warm objective mismatch")
        pairs.extend(run_pairs)
        runs.append({
            "run_id": row["run_id"], "tier_id": row["tier_id"], "seed": int(row["seed"]),
            "status": row["status"], "execution_mode": row["execution_mode"],
            "result_sha256": manifest["result_sha256"],
            "manifest_sha256": sha256_file(manifest_path),
            "status_summary_sha256": sha256_file(status_summary_path),
            "training_scenarios_sha256": manifest["training_scenarios_sha256"],
            "resolved_run_sha256": manifest["resolved_run_sha256"],
            "git_commit_sha": manifest["git"]["commit_sha"], "git_tree_sha": manifest["git"]["tree_sha"],
            "working_tree_dirty": manifest["git"]["working_tree_dirty"],
            "solver": manifest["solver"],
            "started_at_utc": result["started_at_utc"], "finished_at_utc": result["finished_at_utc"],
            "sequence_elapsed_seconds": result["sequence_elapsed_seconds"],
            "budget_pair_count": 3,
            "algorithm_execution_count": sum(2 * int(item["planned_repetitions"]) for item in result["comparisons"]),
        })
        del result
        gc.collect()

    tier_summaries = {tier: _tier_summary(pairs, tier) for tier in EXPECTED_TIER_RUNS}
    artifact_mapping = {
        row["run_id"]: {key: row[key] for key in (
            "result_sha256", "manifest_sha256", "status_summary_sha256",
            "training_scenarios_sha256", "resolved_run_sha256",
        )}
        for row in runs
    }
    total_worker_seconds = sum(float(row["wall_seconds"]) for row in performance)
    repetition_groups: dict[tuple[str, str, str, str], list[float]] = {}
    for row in performance:
        key = (row["tier_id"], row["seed"], row["budget_index"], row["algorithm"])
        repetition_groups.setdefault(key, []).append(float(row["objective"]))
    maximum_repeat_spread = max(max(values) - min(values) for values in repetition_groups.values())
    audit = {
        "audit_schema": "phase6_m0_e3_algorithm_performance_results_v1_0",
        "classification": "formal_M0_E3_algorithm_performance_results",
        "source": {
            "execution_git_sha": expected_git["commit_sha"], "execution_git_tree_sha": expected_git["tree_sha"],
            "run_id_prefix": "m0e3_formal_v1_20260823",
            "output_root": output_root.relative_to(root).as_posix(),
        },
        "fingerprints": {
            "scientific_config_sha256": "f709cad35c79619673beeaa7dbe9bf51d75700aee4b2d6dcd2b8eb0d639505b3",
            "e3_component_sha256": "20e1b80c1b117e8e801755d754f9005a8b386644c193dcb503396e4f3ec2cc5e",
            "runner_config_sha256": "3f176c3b64bc187ba94265866445a5518ffaf17abc642c9cd57c2abc531d9dcd",
            "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
            "algorithm_performance_orchestrator_sha256": "003b14b60ed06e1993bddcd2bd0704eafd9b2a7a7e8a42819a5c723c52f3f0cc",
        },
        "counts": {
            "primary_run_count": len(runs), "budget_pair_count": len(pairs),
            "algorithm_execution_count": len(performance),
            "tier_primary_run_counts": {tier: sum(row["tier_id"] == tier for row in runs) for tier in EXPECTED_TIER_RUNS},
            "tier_algorithm_execution_counts": {tier: sum(row["tier_id"] == tier for row in performance) for tier in EXPECTED_TIER_RUNS},
            "failed_primary_run_count": 0, "invalid_primary_run_count": 0,
            "duplicate_primary_run_count": 0, "diagnostic_run_count": 0,
        },
        "global_artifacts": {
            "run_registry_sha256": sha256_file(registry_path),
            "algorithm_performance_sha256": sha256_file(performance_path),
            "projection_sha256": sha256_file(projection_path),
            "status_summary_sha256": sha256_file(status_path),
            "run_artifact_mapping_sha256": canonical_sha256(artifact_mapping),
        },
        "runs": runs,
        "pairs": pairs,
        "tier_summaries": tier_summaries,
        "aggregate": {
            "total_worker_seconds": total_worker_seconds,
            "maximum_peak_memory_mb": max(float(row["peak_memory_mb"]) for row in performance),
            "maximum_objective_difference": max(float(row["objective_difference"]) for row in pairs),
            "maximum_within_technical_repeat_objective_difference": maximum_repeat_spread,
            "all_objectives_within_frozen_tolerance": True,
            "M0_E3_algorithm_performance_gate_passed": True,
        },
        "interpretation_boundaries": {
            "comparison": "complete_standard_CCG_cold_vs_complete_SPW_CCG_cross_budget_warm_workflows",
            "pure_SPW_effect_identified": False, "pure_warm_start_effect_identified": False,
            "M2_speed_comparison_performed": False, "P2_inference_permitted": False,
        },
        "stop_boundary": {
            "M2_performance_runs": 0, "M2_1_additional_runs": 0,
            "other_formal_experiments_started": False,
        },
    }
    return audit, pairs


def write_outputs(*, root: Path, output_root: Path, audit_path: Path, pairs_path: Path) -> dict[str, Any]:
    audit, pairs = build_audit(root=root, output_root=output_root)
    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with pairs_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PAIR_FIELDS, lineterminator="\n")
        writer.writeheader(); writer.writerows(pairs)
    audit["compact_artifacts"] = {
        "budget_pair_csv": pairs_path.relative_to(root).as_posix(),
        "budget_pair_csv_sha256": sha256_file(pairs_path),
    }
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return audit


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", default="outputs/phase6_m0_e3_algorithm_performance_v1_0")
    parser.add_argument("--audit", default="docs/handoffs/2026-08-23_phase6_m0_e3_algorithm_performance_results_v1_0_audit.json")
    parser.add_argument("--pairs", default="docs/handoffs/2026-08-23_phase6_m0_e3_algorithm_performance_results_v1_0_pairs.csv")
    args = parser.parse_args(argv)
    root = Path.cwd().resolve()
    audit = write_outputs(root=root, output_root=(root / args.output_root).resolve(), audit_path=root / args.audit, pairs_path=root / args.pairs)
    print(json.dumps({"status": "complete", "counts": audit["counts"], "aggregate": audit["aggregate"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

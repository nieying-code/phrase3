"""Build and validate compact evidence for the finalized M2 performance batch."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Mapping

from .phase6_m2_algorithm_performance_formal import (
    COMPONENT_FIELDS,
    GAP_NUMERICAL_PROTECTION,
    _canonical_sha,
    _method_metrics,
    compute_formal_statistics,
)
from .reproducibility import sha256_file


EXPECTED_SEEDS = tuple(range(2026091101, 2026091111))
EXPECTED_PROFILES = ("C0", "T03")
EXPECTED_BETAS = (1.1, 1.3)
EXPECTED_BUDGETS = (2571.372016574617, 3038.894201406366)


def canonical_sha(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _oracle_order(row: Mapping[str, Any]) -> list[str]:
    costs = row["ccg_result"]["exact_scenario_costs"]
    return list(costs)


def _compact_method(row: Mapping[str, Any]) -> dict[str, Any]:
    metrics = _method_metrics(row)
    order = _oracle_order(row)
    return {
        "repetition": int(row["repetition"]),
        "status": str(row["status"]),
        **metrics,
        "exact_oracle_scenario_count": len(order),
        "exact_oracle_scenario_order_sha256": canonical_sha(order),
        "transfer_source_state_sha256": row.get("transfer_source_state_sha256"),
        "transfer_source_budget": row.get("transfer_source_budget"),
        "transferred_exact_scenarios": list(row["transferred_exact_scenarios"]),
        "transferred_scenarios_becoming_active_or_worst": list(
            row["transferred_scenarios_becoming_active_or_worst"]
        ),
    }


def _compact_run(result_path: Path) -> dict[str, Any]:
    result = json.loads(result_path.read_text(encoding="utf-8"))
    comparisons = []
    for comparison in result["comparisons"]:
        methods = {
            name: [_compact_method(row) for row in comparison["methods"][name]]
            for name in ("cold", "warm")
        }
        cold_median = float(median(row["subprocess_wall_seconds"] for row in methods["cold"]))
        warm_median = float(median(row["subprocess_wall_seconds"] for row in methods["warm"]))
        comparisons.append({
            "budget_index": int(comparison["budget_index"]),
            "beta": float(comparison["beta"]),
            "budget": float(comparison["budget"]),
            "execution_order": list(comparison["execution_order"]),
            "status": str(comparison["status"]),
            "objective_tolerance": float(comparison["objective_tolerance"]),
            "maximum_objective_difference": float(comparison["maximum_objective_difference"]),
            "cold_median_seconds": cold_median,
            "warm_median_seconds": warm_median,
            "speedup_cold_over_warm": cold_median / warm_median,
            "methods": methods,
            "transferred_states_sha256": {
                key: _canonical_sha(value)
                for key, value in comparison["transferred_states"].items()
            },
        })
    run_dir = result_path.parent
    return {
        "run_id": result["run_id"], "case_id": result["case_id"],
        "tier_id": result["tier_id"], "execution_mode": result["execution_mode"],
        "seed": int(result["seed"]), "profile_id": result["profile_id"],
        "status": result["status"], "artifact_state": result["artifact_state"],
        "planned_algorithm_execution_count": int(result["planned_algorithm_execution_count"]),
        "completed_algorithm_execution_count": int(result["completed_algorithm_execution_count"]),
        "result_sha256": sha256_file(result_path),
        "manifest_sha256": sha256_file(run_dir / "manifest.json"),
        "status_summary_sha256": sha256_file(run_dir / "status_summary.json"),
        "fingerprints": result["fingerprints"],
        "execution_identity": result["execution_identity"],
        "comparisons": comparisons,
    }


def _derived(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values = []
    for run in runs:
        timing = []
        for comparison in run["comparisons"]:
            timing.append({
                "seed": run["seed"], "profile_id": run["profile_id"],
                "budget_index": comparison["budget_index"], "beta": comparison["beta"],
                "budget": comparison["budget"],
                "cold_median_seconds": comparison["cold_median_seconds"],
                "warm_median_seconds": comparison["warm_median_seconds"],
                "speedup_cold_over_warm": comparison["speedup_cold_over_warm"],
            })
        values.append({"derived": {"timing": timing}})
    return values


def _run_mapping(runs: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        run["run_id"]: {
            "result_sha256": run["result_sha256"],
            "manifest_sha256": run["manifest_sha256"],
            "status_summary_sha256": run["status_summary_sha256"],
            "comparisons": run["comparisons"],
        }
        for run in runs
    }


def validate_compact_audit(audit: Mapping[str, Any]) -> None:
    runs = list(audit["runs"])
    expected = {
        (seed, profile): f"M2AP2_formal_seed{seed}_profile{profile}"
        for seed in EXPECTED_SEEDS for profile in EXPECTED_PROFILES
    }
    if len(runs) != 20 or {(r["seed"], r["profile_id"]): r["case_id"] for r in runs} != expected:
        raise ValueError("formal 20-case identity mismatch")
    executions = pairs = negative_gaps = 0
    max_difference = 0.0
    fingerprints = runs[0]["fingerprints"]
    execution_identity = runs[0]["execution_identity"]
    for run in runs:
        if (
            run["status"] != "optimal" or run["artifact_state"] != "finalized"
            or run["tier_id"] != "M2AP2" or run["execution_mode"] != "formal"
            or run["planned_algorithm_execution_count"] != 12
            or run["completed_algorithm_execution_count"] != 12
            or run["fingerprints"] != fingerprints
            or run["execution_identity"] != execution_identity
            or len(run["comparisons"]) != 2
        ):
            raise ValueError("formal run closure mismatch")
        prior_states: dict[str, str] | None = None
        prior_components = prior_joint = None
        for index, comparison in enumerate(run["comparisons"]):
            pairs += 1
            expected_order = ["cold", "warm"] if index == 0 else ["warm", "cold"]
            if (
                comparison["budget_index"] != index or comparison["execution_order"] != expected_order
                or comparison["status"] != "optimal"
                or not math.isclose(comparison["beta"], EXPECTED_BETAS[index], abs_tol=1e-12)
                or not math.isclose(comparison["budget"], EXPECTED_BUDGETS[index], abs_tol=1e-9)
            ):
                raise ValueError("formal budget identity mismatch")
            methods = comparison["methods"]
            objectives = []
            identities = []
            for name in ("cold", "warm"):
                if len(methods[name]) != 3:
                    raise ValueError("technical repetition count mismatch")
                for repetition, row in enumerate(methods[name], 1):
                    executions += 1
                    if row["repetition"] != repetition or row["status"] != "optimal":
                        raise ValueError("technical repetition identity mismatch")
                    for field in (
                        "objective", "lower_bound", "upper_bound", "reported_optimality_gap",
                        "recomputed_upper_minus_lower", "optimality_gap", "subprocess_wall_seconds",
                        "sampled_peak_RSS_MiB", "master_runtime_seconds", "oracle_runtime_seconds",
                    ):
                        if not math.isfinite(float(row[field])):
                            raise ValueError("nonfinite method evidence")
                    if row["subprocess_wall_seconds"] <= 0 or row["reported_optimality_gap"] < -GAP_NUMERICAL_PROTECTION:
                        raise ValueError("invalid timing or gap")
                    if abs(row["reported_optimality_gap"] - row["recomputed_upper_minus_lower"]) > GAP_NUMERICAL_PROTECTION:
                        raise ValueError("gap does not match bounds")
                    expected_normalized = max(0.0, row["reported_optimality_gap"])
                    if row["optimality_gap"] != expected_normalized:
                        raise ValueError("gap normalization mismatch")
                    negative_gaps += int(row["reported_optimality_gap"] < 0)
                    if row["exact_oracle_scenario_count"] != 100:
                        raise ValueError("incomplete exact oracle")
                    if row["exact_oracle_scenario_order_sha256"] != row["component_set_sha256"]["scenario_order_sha256"]:
                        raise ValueError("oracle order identity mismatch")
                    if set(row["component_set_sha256"]) != set(COMPONENT_FIELDS):
                        raise ValueError("component identity incomplete")
                    if index == 0 or name == "cold":
                        if row["transfer_source_state_sha256"] is not None or row["transferred_exact_scenarios"]:
                            raise ValueError("unexpected transfer")
                    else:
                        key = str(repetition)
                        if row["transfer_source_state_sha256"] != prior_states[key] or not row["transferred_exact_scenarios"]:
                            raise ValueError("second-budget transfer mismatch")
                    objectives.append(row["objective"])
                    identities.append((row["joint_scenario_set_sha256"], row["component_set_sha256"]))
            if any(value != identities[0] for value in identities[1:]):
                raise ValueError("within-budget scenario identity mismatch")
            if prior_components is not None and identities[0] != (prior_joint, prior_components):
                raise ValueError("cross-budget scenario identity mismatch")
            difference = max(objectives) - min(objectives)
            if not math.isclose(difference, comparison["maximum_objective_difference"], abs_tol=1e-12):
                raise ValueError("objective difference mismatch")
            max_difference = max(max_difference, difference)
            cold = [r["subprocess_wall_seconds"] for r in methods["cold"]]
            warm = [r["subprocess_wall_seconds"] for r in methods["warm"]]
            if comparison["cold_median_seconds"] != float(median(cold)) or comparison["warm_median_seconds"] != float(median(warm)):
                raise ValueError("median timing mismatch")
            if comparison["speedup_cold_over_warm"] != comparison["cold_median_seconds"] / comparison["warm_median_seconds"]:
                raise ValueError("speedup mismatch")
            prior_states = comparison["transferred_states_sha256"]
            prior_joint, prior_components = identities[0]
    if (pairs, executions) != (40, 240):
        raise ValueError("formal workload closure mismatch")
    aggregate = audit["aggregate"]
    if (
        aggregate["completed_primary_sequence_count"] != 20
        or aggregate["completed_budget_pair_count"] != pairs
        or aggregate["completed_algorithm_execution_count"] != executions
        or aggregate["negative_reported_gap_count"] != negative_gaps
        or aggregate["maximum_objective_difference"] != max_difference
    ):
        raise ValueError("formal aggregate mismatch")
    rebuilt = compute_formal_statistics(_derived(runs), correctness_gate_passed=True)
    if rebuilt != audit["formal_statistics"]:
        raise ValueError("formal statistics mismatch")
    if canonical_sha(_run_mapping(runs)) != audit["global_artifacts"]["run_evidence_mapping_sha256"]:
        raise ValueError("run evidence mapping mismatch")


def build(*, execution_root: Path, audit_path: Path, csv_path: Path) -> dict[str, Any]:
    projection_path = execution_root / "formal_projection.json"
    registry_path = execution_root / "run_registry.json"
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    runs = sorted(
        (_compact_run(path) for path in (execution_root / "runs").glob("*/result.json")),
        key=lambda row: (row["seed"], row["profile_id"]),
    )
    formal_statistics = compute_formal_statistics(_derived(runs), correctness_gate_passed=True)
    all_methods = [
        method for run in runs for comparison in run["comparisons"]
        for name in ("cold", "warm") for method in comparison["methods"][name]
    ]
    audit = {
        "schema_version": "phase6_m2_algorithm_performance_formal_results_v1_1_audit_v1",
        "status": "passed",
        "classification": "formal_algorithm_performance_result_evidence",
        "runs": runs,
        "aggregate": {
            "required_primary_sequence_count": 20,
            "completed_primary_sequence_count": len(runs),
            "required_budget_pair_count": 40,
            "completed_budget_pair_count": sum(len(run["comparisons"]) for run in runs),
            "required_algorithm_execution_count": 240,
            "completed_algorithm_execution_count": len(all_methods),
            "negative_reported_gap_count": sum(m["reported_optimality_gap"] < 0 for m in all_methods),
            "minimum_reported_gap": min(m["reported_optimality_gap"] for m in all_methods),
            "maximum_gap_identity_difference": max(abs(m["reported_optimality_gap"] - m["recomputed_upper_minus_lower"]) for m in all_methods),
            "maximum_objective_difference": max(c["maximum_objective_difference"] for r in runs for c in r["comparisons"]),
            "maximum_sampled_peak_RSS_MiB": max(m["sampled_peak_RSS_MiB"] for m in all_methods),
            "missing_case_ids": projection["missing_case_ids"],
            "duplicate_case_ids": projection["duplicate_case_ids"],
            "failed_primary_run_ids": projection["failed_primary_run_ids"],
            "invalid_primary_runs": projection["invalid_primary_runs"],
            "diagnostic_run_ids": projection["diagnostic_run_ids"],
            "common_random_number_mismatches": projection["common_random_number_mismatches"],
            "formal_algorithm_performance_gate_passed": projection["formal_algorithm_performance_gate_passed"],
            "other_experiments_authorized": projection["other_experiments_authorized"],
        },
        "formal_statistics": formal_statistics,
        "fingerprints": projection["fingerprints"],
        "execution_identity": projection["execution_identity"],
        "global_artifacts": {
            "formal_projection_sha256": sha256_file(projection_path),
            "formal_run_registry_sha256": sha256_file(registry_path),
            "run_evidence_mapping_sha256": canonical_sha(_run_mapping(runs)),
        },
        "execution_boundaries": {
            "M2_1_runs": 0, "M0_E3_runs": 0, "other_formal_experiment_runs": 0,
        },
        "interpretation_boundaries": {
            "reliable_M2_T03_cross_budget_acceleration_supported": formal_statistics["reliable_M2_T03_acceleration_gate_passed"],
            "supply_disruption_enhances_warm_start_benefit_supported": formal_statistics["supply_disruption_enhances_warm_start_benefit_gate_passed"],
            "M2_faster_than_M0_claim_permitted": False,
            "pure_SPW_effect_or_pure_warm_start_effect_claim_permitted": False,
        },
    }
    validate_compact_audit(audit)
    audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(
            "seed", "C0_beta_1_1_speedup", "C0_beta_1_3_speedup", "C0_end_to_end_speedup",
            "T03_beta_1_1_speedup", "T03_beta_1_3_speedup", "T03_end_to_end_speedup",
            "paired_T03_minus_C0_beta_1_3_log_speedup",
        ))
        writer.writeheader()
        for row in formal_statistics["seed_level_values"]:
            writer.writerow({
                "seed": row["seed"],
                "C0_beta_1_1_speedup": row["profiles"]["C0"]["beta_1_1"]["speedup_cold_over_warm"],
                "C0_beta_1_3_speedup": row["profiles"]["C0"]["beta_1_3"]["speedup_cold_over_warm"],
                "C0_end_to_end_speedup": row["profiles"]["C0"]["end_to_end_two_budget_speedup"],
                "T03_beta_1_1_speedup": row["profiles"]["T03"]["beta_1_1"]["speedup_cold_over_warm"],
                "T03_beta_1_3_speedup": row["profiles"]["T03"]["beta_1_3"]["speedup_cold_over_warm"],
                "T03_end_to_end_speedup": row["profiles"]["T03"]["end_to_end_two_budget_speedup"],
                "paired_T03_minus_C0_beta_1_3_log_speedup": row["paired_T03_minus_C0_beta_1_3_log_speedup"],
            })
    return audit


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execution-root", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    args = parser.parse_args()
    build(execution_root=args.execution_root, audit_path=args.audit, csv_path=args.csv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

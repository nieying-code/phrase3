"""Run-level performance tables and conservative Phase 6 pilot projection."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import statistics
from typing import Any, Mapping

from .phase6_io import (
    atomic_write_csv as _atomic_write_csv,
    atomic_write_json as _atomic_write_json,
)
from .phase6_locking import exclusive_file_lock
from .reproducibility import sha256_file


PERFORMANCE_FIELDS = (
    "run_id",
    "execution_mode",
    "tier_id",
    "seed",
    "budget_index",
    "budget",
    "algorithm",
    "repetition",
    "status",
    "objective",
    "iterations",
    "scenario_count",
    "wall_seconds",
    "peak_memory_mb",
)


def update_algorithm_performance(
    output_root: Path,
    result: Mapping[str, Any],
) -> Path:
    """Upsert every worker repetition into the global performance table."""

    path = (
        output_root
        / "experiments"
        / "phase6"
        / "algorithm_performance.csv"
    )
    lock_path = path.parent / ".aggregate.lock"
    with exclusive_file_lock(lock_path):
        existing: list[dict[str, Any]] = []
        if path.exists():
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                existing = list(csv.DictReader(handle))
        run_id = str(result["run_id"])
        existing = [row for row in existing if row["run_id"] != run_id]
        for comparison in result["comparisons"]:
            planned_repetitions = int(
                comparison.get(
                    "planned_repetitions",
                    max(
                        len(comparison["cold"]["repetitions"]),
                        len(comparison["warm"]["repetitions"]),
                    ),
                )
            )
            for algorithm in ("cold", "warm"):
                mode = comparison[algorithm]
                actual = list(mode["repetitions"])
                unexecuted_status = mode.get("unexecuted_status")
                for repetition_index in range(1, planned_repetitions + 1):
                    repetition = (
                        actual[repetition_index - 1]
                        if repetition_index <= len(actual)
                        else {
                            "status": (
                                unexecuted_status
                                or "not_run_after_algorithm_failure"
                            ),
                            "ccg_result": None,
                        }
                    )
                    ccg = repetition.get("ccg_result")
                    existing.append(
                        {
                            "run_id": run_id,
                            "execution_mode": result["execution_mode"],
                            "tier_id": result["tier_id"],
                            "seed": result["seed"],
                            "budget_index": comparison["budget_index"],
                            "budget": comparison["budget"],
                            "algorithm": algorithm,
                            "repetition": repetition_index,
                            "status": repetition["status"],
                            "objective": (
                                ccg.get("objective")
                                if ccg is not None
                                else None
                            ),
                            "iterations": (
                                ccg.get("iterations")
                                if ccg is not None
                                else None
                            ),
                            "scenario_count": repetition.get(
                                "scenario_count"
                            ),
                            "wall_seconds": repetition.get(
                                "subprocess_wall_seconds"
                            ),
                            "peak_memory_mb": repetition.get(
                                "peak_memory_mb"
                            ),
                        }
                    )
        _atomic_write_csv(path, PERFORMANCE_FIELDS, existing)
    return path


def _run_throughput(result: Mapping[str, Any]) -> dict[str, float]:
    total_seconds = 0.0
    master_solves = 0
    recourse_lp_solves = 0
    peak_memory = 0.0
    algorithm_executions = 0
    for comparison in result["comparisons"]:
        for algorithm in ("cold", "warm"):
            for repetition in comparison[algorithm]["repetitions"]:
                ccg = repetition.get("ccg_result")
                if repetition["status"] != "optimal" or ccg is None:
                    continue
                seconds = float(repetition["subprocess_wall_seconds"])
                iterations = int(ccg["iterations"])
                scenarios = int(repetition["scenario_count"])
                total_seconds += seconds
                master_solves += iterations
                recourse_lp_solves += iterations * scenarios
                peak_memory = max(
                    peak_memory,
                    float(repetition.get("peak_memory_mb", 0.0)),
                )
                algorithm_executions += 1
    hours = total_seconds / 3600.0
    if hours <= 0.0:
        raise ValueError("pilot run has no positive worker time")
    return {
        "worker_hours": hours,
        "master_solves_per_hour": master_solves / hours,
        "recourse_lp_solves_per_hour": recourse_lp_solves / hours,
        "algorithm_executions_per_hour": algorithm_executions / hours,
        "completed_budget_pairs_per_hour": (
            sum(
                row.get("status") == "optimal"
                for row in result["comparisons"]
            )
            / hours
        ),
        "peak_memory_mb": peak_memory,
    }


def validate_e3_run_artifacts(
    row: Mapping[str, str],
) -> dict[str, Any]:
    """Verify an E3 registry row against finalized, hashed artifacts."""

    result_path = Path(str(row.get("result_path", "")))
    manifest_path = Path(str(row.get("manifest_path", "")))
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("E3 result or manifest is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_state") != "finalized":
        raise ValueError("E3 manifest is not finalized")
    if Path(str(manifest.get("result_path", ""))).resolve() != result_path.resolve():
        raise ValueError("E3 manifest result path mismatch")
    if manifest.get("result_sha256") != sha256_file(result_path):
        raise ValueError("E3 result SHA-256 mismatch")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    fingerprints = result.get("fingerprints") or {}
    exact_fields = {
        "run_id": result.get("run_id"),
        "parent_run_id": result.get("parent_run_id") or "",
        "execution_mode": result.get("execution_mode"),
        "tier_id": result.get("tier_id"),
        "seed": str(result.get("seed")),
        "status": result.get("status"),
        "planned_budget_count": str(result.get("planned_budget_count")),
        "completed_budget_count": str(result.get("completed_budget_count")),
        "scientific_config_sha256": fingerprints.get(
            "scientific_config_sha256"
        ),
        "runner_config_sha256": fingerprints.get("runner_config_sha256"),
        "e3_component_sha256": fingerprints.get("e3_component_sha256"),
        "environment_sha256": fingerprints.get("environment_sha256"),
    }
    for name, expected in exact_fields.items():
        if str(row.get(name, "")) != str(expected):
            raise ValueError(f"E3 registry/result mismatch for {name}")
        if name.endswith("sha256") and manifest.get(name) != expected:
            raise ValueError(f"E3 manifest/result mismatch for {name}")
    if manifest.get("run_id") != result.get("run_id"):
        raise ValueError("E3 manifest run_id mismatch")
    return result


def update_pilot_projection(
    *,
    output_root: Path,
    matrix: Mapping[str, Any],
    runner_config: Mapping[str, Any],
    matrix_sha256: str,
    scientific_config_sha256: str,
    runner_config_sha256: str,
    e3_component_sha256: str,
    environment_sha256: str,
) -> dict[str, Any]:
    """Rebuild fingerprinted pilot coverage without unit-invalid estimates."""

    base = output_root / "experiments" / "phase6"
    registry_path = base / "run_registry.csv"
    destination = base / "pilot_throughput_projection.json"
    required_tiers = [
        str(value)
        for value in runner_config["runner"][
            "pilot_projection_required_tiers"
        ]
    ]
    required_seeds = [
        int(value) for value in matrix["seed_plan"]["pilot_training_seeds"]
    ]
    lock_path = base / ".aggregate.lock"
    with exclusive_file_lock(lock_path):
        registry_rows: list[dict[str, str]] = []
        if registry_path.exists():
            with registry_path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                registry_rows = list(csv.DictReader(handle))

        matching = [
            row
            for row in registry_rows
            if (
                row["execution_mode"] == "pilot"
                and row["tier_id"] in required_tiers
                and int(row["seed"]) in required_seeds
                and row.get("scientific_config_sha256", "")
                == scientific_config_sha256
                and row["runner_config_sha256"]
                == runner_config_sha256
                and row.get("e3_component_sha256", "")
                == e3_component_sha256
                and row.get("environment_sha256", "")
                == environment_sha256
            )
        ]
        artifact_invalid: list[dict[str, Any]] = []
        verified_results: dict[str, dict[str, Any]] = {}
        valid_matching: list[dict[str, str]] = []
        for row in matching:
            try:
                verified_results[row["run_id"]] = validate_e3_run_artifacts(row)
            except Exception as exc:
                artifact_invalid.append(
                    {
                        "run_id": row.get("run_id"),
                        "tier_id": row.get("tier_id"),
                        "seed": row.get("seed"),
                        "status": "artifact_invalid",
                        "message": f"{type(exc).__name__}: {exc}",
                    }
                )
            else:
                valid_matching.append(row)
        primaries: dict[tuple[str, int], list[dict[str, str]]] = {}
        diagnostics: list[dict[str, Any]] = []
        for row in valid_matching:
            if row.get("parent_run_id", "").strip():
                diagnostics.append(
                    {
                        "run_id": row["run_id"],
                        "parent_run_id": row["parent_run_id"],
                        "tier_id": row["tier_id"],
                        "seed": int(row["seed"]),
                        "status": row["status"],
                    }
                )
                continue
            key = (row["tier_id"], int(row["seed"]))
            primaries.setdefault(key, []).append(row)

        missing: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        duplicate: list[dict[str, Any]] = []
        selected: dict[tuple[str, int], dict[str, str]] = {}
        for tier in required_tiers:
            for seed in required_seeds:
                key = (tier, seed)
                rows = primaries.get(key, [])
                if not rows:
                    missing.append({"tier_id": tier, "seed": seed})
                elif len(rows) > 1:
                    duplicate.append(
                        {
                            "tier_id": tier,
                            "seed": seed,
                            "run_ids": sorted(
                                row["run_id"] for row in rows
                            ),
                        }
                    )
                else:
                    selected[key] = rows[0]
                    completed_budgets = int(
                        rows[0].get("completed_budget_count", 0)
                    )
                    planned_budgets = int(
                        rows[0].get("planned_budget_count", 0)
                    )
                    if (
                        rows[0]["status"] != "optimal"
                        or planned_budgets <= 0
                        or completed_budgets != planned_budgets
                    ):
                        failed.append(
                            {
                                "tier_id": tier,
                                "seed": seed,
                                "run_id": rows[0]["run_id"],
                                "status": rows[0]["status"],
                                "completed_budget_count": completed_budgets,
                                "planned_budget_count": planned_budgets,
                            }
                        )

        runs: list[dict[str, Any]] = []
        rates: list[dict[str, float]] = []
        for (tier, seed), row in sorted(selected.items()):
            if (
                row["status"] != "optimal"
                or int(row.get("planned_budget_count", 0)) <= 0
                or int(row.get("completed_budget_count", 0))
                != int(row.get("planned_budget_count", 0))
            ):
                continue
            result = verified_results[row["run_id"]]
            throughput = _run_throughput(result)
            rates.append(throughput)
            runs.append(
                {
                    "run_id": row["run_id"],
                    "tier_id": tier,
                    "seed": seed,
                    **throughput,
                }
            )

        required_count = len(required_tiers) * len(required_seeds)
        if artifact_invalid:
            status = "pilot_failures"
        elif missing:
            status = "insufficient_pilot_coverage"
        elif failed:
            status = "pilot_failures"
        elif duplicate:
            status = "ambiguous_primary_runs"
        else:
            status = "projection_incomplete"
        payload: dict[str, Any] = {
            "matrix_id": matrix["matrix_id"],
            "matrix_status": matrix.get("status"),
            "matrix_sha256": matrix_sha256,
            "scientific_config_sha256": scientific_config_sha256,
            "runner_config_sha256": runner_config_sha256,
            "e3_component_sha256": e3_component_sha256,
            "environment_sha256": environment_sha256,
            "required_tiers": required_tiers,
            "required_seeds": required_seeds,
            "completed_run_count": len(runs),
            "required_run_count": required_count,
            "primary_completion_rate": len(runs) / required_count,
            "missing_runs": missing,
            "failed_primary_runs": failed,
            "artifact_invalid_runs": artifact_invalid,
            "duplicate_primary_runs": duplicate,
            "diagnostic_attempts": diagnostics,
            "runs": runs,
            "projection_method": (
                "experiment_family_specific_dimensionally_consistent_rates"
            ),
            "family_projection": {
                "E1": {
                    "status": "unavailable",
                    "reason": "extensive_and_ccg_gold_runner_not_implemented",
                },
                "E2": {
                    "status": "unavailable",
                    "reason": "six_policy_model_comparison_runner_not_implemented",
                },
                "E3": {
                    "status": (
                        "available_if_full_pilot_coverage"
                        if not missing and not failed and not duplicate
                        else "awaiting_complete_pilots"
                    ),
                    "work_unit": "recourse_lp_solve",
                },
                "E4": {
                    "status": "unavailable",
                    "reason": "out_of_sample_runner_not_implemented",
                },
                "E5": {
                    "status": "unavailable",
                    "reason": "sensitivity_runner_not_implemented",
                },
            },
            "compute_gate_passed": False,
            "status": status,
            "formal_execution_authorized": False,
        }
        if rates:
            payload["observed_median_rates"] = {
                key: statistics.median(row[key] for row in rates)
                for key in (
                    "master_solves_per_hour",
                    "recourse_lp_solves_per_hour",
                    "algorithm_executions_per_hour",
                    "completed_budget_pairs_per_hour",
                    "peak_memory_mb",
                )
            }
        if (
            not missing
            and not failed
            and not duplicate
            and not artifact_invalid
            and rates
        ):
            conservative_recourse_rate = min(
                row["recourse_lp_solves_per_hour"] for row in rates
            )
            payload["family_projection"]["E3"].update(
                {
                    "status": "projected",
                    "estimated_recourse_lp_calls": int(
                        matrix["workload_estimation"][
                            "E3_recourse_lp_calls_at_10_iterations_estimate"
                        ]
                    ),
                    "conservative_recourse_lp_solves_per_hour": (
                        conservative_recourse_rate
                    ),
                    "projected_wall_hours": (
                        float(
                            matrix["workload_estimation"][
                                "E3_recourse_lp_calls_at_10_iterations_estimate"
                            ]
                        )
                        / conservative_recourse_rate
                    ),
                }
            )
        _atomic_write_json(destination, payload)
    return payload


def validate_formal_projection(
    *,
    projection_path: Path,
    matrix_id: str,
    scientific_config_sha256: str,
    runner_config_sha256: str,
    e3_component_sha256: str,
    environment_sha256: str,
) -> dict[str, Any]:
    """Require a complete, current, explicitly authorized projection."""

    if not projection_path.exists():
        raise ValueError("formal execution requires a pilot projection file")
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    expected = {
        "matrix_id": matrix_id,
        "scientific_config_sha256": scientific_config_sha256,
        "runner_config_sha256": runner_config_sha256,
        "e3_component_sha256": e3_component_sha256,
        "environment_sha256": environment_sha256,
    }
    mismatches = {
        name: {"expected": value, "actual": payload.get(name)}
        for name, value in expected.items()
        if payload.get(name) != value
    }
    if mismatches:
        raise ValueError(
            f"pilot projection fingerprint mismatch: {mismatches}"
        )
    required = int(payload.get("required_run_count", 0))
    completed = int(payload.get("completed_run_count", 0))
    if required <= 0 or completed != required:
        raise ValueError(
            f"pilot coverage incomplete: {completed}/{required}"
        )
    if payload.get("failed_primary_runs"):
        raise ValueError("pilot projection contains failed primary runs")
    if payload.get("artifact_invalid_runs"):
        raise ValueError("pilot projection contains invalid artifacts")
    if payload.get("duplicate_primary_runs"):
        raise ValueError("pilot projection contains duplicate primary runs")
    if payload.get("missing_runs"):
        raise ValueError("pilot projection contains missing runs")
    if payload.get("status") != "passed":
        raise ValueError(
            f"pilot projection status is not passed: {payload.get('status')}"
        )
    if payload.get("compute_gate_passed") is not True:
        raise ValueError("pilot compute gate has not passed")
    if payload.get("formal_execution_authorized") is not True:
        raise ValueError("pilot projection does not authorize formal execution")
    return payload


def update_scale_advancement(
    *,
    output_root: Path,
    matrix: Mapping[str, Any],
    scientific_config_sha256: str,
    runner_config_sha256: str,
    e3_component_sha256: str,
    environment_sha256: str,
    source_tier: str = "P1",
    target_tier: str = "P2",
) -> dict[str, Any]:
    """Rebuild the fingerprinted P1-to-P2 formal advancement decision."""

    base = output_root / "experiments" / "phase6"
    destination = base / "scale_advancement.json"
    registry_path = base / "run_registry.csv"
    formal_seeds = [
        int(value) for value in matrix["seed_plan"]["formal_training_seeds"]
    ]
    tier_raw = next(
        item for item in matrix["scale_tiers"] if item["id"] == source_tier
    )
    expected_seeds = formal_seeds[: int(tier_raw["formal_seed_count"])]
    budget_count = len(matrix["budget_plan"]["formal_factors"])
    expected_pairs = len(expected_seeds) * budget_count
    rows: list[dict[str, str]] = []
    if registry_path.exists():
        with registry_path.open(
            "r", encoding="utf-8-sig", newline=""
        ) as handle:
            rows = list(csv.DictReader(handle))
    matching = [
        row
        for row in rows
        if (
            row.get("execution_mode") == "formal"
            and row.get("tier_id") == source_tier
            and int(row.get("seed") or -1) in expected_seeds
            and not row.get("parent_run_id", "").strip()
            and row.get("scientific_config_sha256")
            == scientific_config_sha256
            and row.get("runner_config_sha256") == runner_config_sha256
            and row.get("e3_component_sha256") == e3_component_sha256
            and row.get("environment_sha256") == environment_sha256
        )
    ]
    verified_results: dict[str, dict[str, Any]] = {}
    artifact_invalid: list[dict[str, str]] = []
    for row in matching:
        try:
            verified_results[row["run_id"]] = validate_e3_run_artifacts(row)
        except Exception as exc:
            artifact_invalid.append(
                {
                    "run_id": row.get("run_id", ""),
                    "message": f"{type(exc).__name__}: {exc}",
                }
            )
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in matching:
        grouped.setdefault(int(row["seed"]), []).append(row)
    missing = [seed for seed in expected_seeds if not grouped.get(seed)]
    duplicates = [
        seed for seed in expected_seeds if len(grouped.get(seed, [])) > 1
    ]
    failed = [
        seed
        for seed in expected_seeds
        if len(grouped.get(seed, [])) == 1
        and grouped[seed][0].get("status") != "optimal"
    ]
    joint_pairs = 0
    cold_fractions: list[float] = []
    warm_fractions: list[float] = []
    budget_wall = float(tier_raw["time_limits"]["ccg_budget_wall_seconds"])
    if not missing and not duplicates and not failed and not artifact_invalid:
        for seed in expected_seeds:
            result = verified_results[grouped[seed][0]["run_id"]]
            for comparison in result.get("comparisons", []):
                times: dict[str, float] = {}
                jointly_optimal = comparison.get("status") == "optimal"
                for algorithm in ("cold", "warm"):
                    repetitions = comparison.get(algorithm, {}).get(
                        "repetitions", []
                    )
                    valid = [
                        float(item["subprocess_wall_seconds"])
                        for item in repetitions
                        if item.get("status") == "optimal"
                        and item.get("subprocess_wall_seconds") is not None
                    ]
                    if len(valid) != int(
                        comparison.get("planned_repetitions", len(valid))
                    ):
                        jointly_optimal = False
                    elif valid:
                        times[algorithm] = statistics.median(valid)
                if jointly_optimal and set(times) == {"cold", "warm"}:
                    joint_pairs += 1
                    cold_fractions.append(times["cold"] / budget_wall)
                    warm_fractions.append(times["warm"] / budget_wall)
    completion_rate = (
        joint_pairs / expected_pairs if expected_pairs else 0.0
    )
    cold_median = (
        statistics.median(cold_fractions) if cold_fractions else None
    )
    warm_median = (
        statistics.median(warm_fractions) if warm_fractions else None
    )
    maximum_runtime_fraction = (
        max(cold_median, warm_median)
        if cold_median is not None and warm_median is not None
        else None
    )
    rules = matrix["scale_advancement"]["all_conditions"]
    coverage_complete = (
        not missing and not duplicates and not failed and not artifact_invalid
    )
    passed = (
        coverage_complete
        and completion_rate
        >= float(rules["joint_pair_completion_rate_minimum"])
        and maximum_runtime_fraction is not None
        and maximum_runtime_fraction
        <= float(rules["max_algorithm_median_runtime_fraction_maximum"])
    )
    payload = {
        "matrix_id": matrix["matrix_id"],
        "scientific_config_sha256": scientific_config_sha256,
        "runner_config_sha256": runner_config_sha256,
        "e3_component_sha256": e3_component_sha256,
        "environment_sha256": environment_sha256,
        "source_tier": source_tier,
        "target_tier": target_tier,
        "expected_seeds": expected_seeds,
        "missing_seeds": missing,
        "duplicate_seeds": duplicates,
        "failed_seeds": failed,
        "artifact_invalid_runs": artifact_invalid,
        "planned_pair_count": expected_pairs,
        "jointly_optimal_pair_count": joint_pairs,
        "joint_pair_completion_rate": completion_rate,
        "cold_median_runtime_fraction": cold_median,
        "warm_median_runtime_fraction": warm_median,
        "maximum_algorithm_median_runtime_fraction": (
            maximum_runtime_fraction
        ),
        "gate_passed": passed,
        "status": "passed" if passed else "not_passed",
    }
    _atomic_write_json(destination, payload)
    return payload


def validate_scale_advancement(
    *,
    advancement_path: Path,
    matrix_id: str,
    scientific_config_sha256: str,
    runner_config_sha256: str,
    e3_component_sha256: str,
    environment_sha256: str,
    source_tier: str,
    target_tier: str,
) -> dict[str, Any]:
    """Reject a target-tier formal run unless its prior-tier gate passed."""

    if not advancement_path.exists():
        raise ValueError("P2 formal execution requires scale advancement")
    payload = json.loads(advancement_path.read_text(encoding="utf-8"))
    expected = {
        "matrix_id": matrix_id,
        "scientific_config_sha256": scientific_config_sha256,
        "runner_config_sha256": runner_config_sha256,
        "e3_component_sha256": e3_component_sha256,
        "environment_sha256": environment_sha256,
        "source_tier": source_tier,
        "target_tier": target_tier,
    }
    mismatches = {
        key: {"expected": value, "actual": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise ValueError(f"scale advancement fingerprint mismatch: {mismatches}")
    if payload.get("status") != "passed" or payload.get("gate_passed") is not True:
        raise ValueError("P1 scale advancement gate has not passed")
    return payload


def append_failure_registry(
    path: Path,
    row: Mapping[str, Any],
) -> None:
    """Append a failure under the shared aggregate lock."""

    fields = (
        "run_id",
        "parent_run_id",
        "tier_id",
        "seed",
        "budget_index",
        "budget",
        "stage",
        "status",
        "message",
        "recorded_at_utc",
    )
    lock_path = path.parent / ".aggregate.lock"
    with exclusive_file_lock(lock_path):
        existing: list[dict[str, Any]] = []
        if path.exists():
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                existing = list(csv.DictReader(handle))
        existing.append({name: row.get(name) for name in fields})
        _atomic_write_csv(path, fields, existing)

"""Run-level performance tables and conservative Phase 6 pilot projection."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path
import statistics
from typing import Any, Mapping


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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_write_csv(
    path: Path,
    fieldnames: tuple[str, ...],
    rows: list[dict[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    os.replace(temporary, path)


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
    existing: list[dict[str, Any]] = []
    if path.exists():
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            existing = list(csv.DictReader(handle))
    run_id = str(result["run_id"])
    existing = [row for row in existing if row["run_id"] != run_id]
    for comparison in result["comparisons"]:
        for algorithm in ("cold", "warm"):
            for repetition_index, repetition in enumerate(
                comparison[algorithm]["repetitions"],
                start=1,
            ):
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
                        "scenario_count": repetition.get("scenario_count"),
                        "wall_seconds": repetition.get(
                            "subprocess_wall_seconds"
                        ),
                        "peak_memory_mb": repetition.get("peak_memory_mb"),
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
            len(result["comparisons"]) / hours
        ),
        "peak_memory_mb": peak_memory,
    }


def update_pilot_projection(
    *,
    output_root: Path,
    matrix: Mapping[str, Any],
    runner_config: Mapping[str, Any],
) -> dict[str, Any]:
    """Rebuild the pilot coverage and conservative workload projection."""

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
    selected: dict[tuple[str, int], dict[str, str]] = {}
    if registry_path.exists():
        with registry_path.open(
            "r",
            encoding="utf-8-sig",
            newline="",
        ) as handle:
            for row in csv.DictReader(handle):
                if (
                    row["execution_mode"] == "pilot"
                    and row["status"] == "optimal"
                    and row["tier_id"] in required_tiers
                    and int(row["seed"]) in required_seeds
                ):
                    key = (row["tier_id"], int(row["seed"]))
                    previous = selected.get(key)
                    if (
                        previous is None
                        or row["updated_at_utc"] > previous["updated_at_utc"]
                    ):
                        selected[key] = row

    missing = [
        {"tier_id": tier, "seed": seed}
        for tier in required_tiers
        for seed in required_seeds
        if (tier, seed) not in selected
    ]
    runs: list[dict[str, Any]] = []
    rates: list[dict[str, float]] = []
    for (tier, seed), row in sorted(selected.items()):
        result_path = Path(row["result_path"])
        result = json.loads(result_path.read_text(encoding="utf-8"))
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

    payload: dict[str, Any] = {
        "matrix_id": matrix["matrix_id"],
        "required_tiers": required_tiers,
        "required_seeds": required_seeds,
        "completed_run_count": len(runs),
        "required_run_count": len(required_tiers) * len(required_seeds),
        "missing_runs": missing,
        "runs": runs,
        "projection_method": (
            "minimum_observed_rate_across_required_tier_seed_pilots"
        ),
        "status": "insufficient_pilot_coverage" if missing else "evaluated",
        "formal_execution_authorized": False,
    }
    if not missing:
        conservative_master_rate = min(
            row["master_solves_per_hour"] for row in rates
        )
        conservative_recourse_rate = min(
            row["recourse_lp_solves_per_hour"] for row in rates
        )
        planned = {
            "E1": 252.0 / conservative_master_rate,
            "E2": 1440.0 / conservative_master_rate,
            "E3": 6_840_000.0 / conservative_recourse_rate,
            "E4": 600_000.0 / conservative_recourse_rate,
            "E5": 790.0 / conservative_master_rate,
        }
        total = sum(planned.values())
        maximum_family = max(planned.values())
        gate = matrix["workload_estimation"]["pilot_throughput_gate"]
        passed = (
            total <= float(gate["maximum_projected_total_wall_hours"])
            and maximum_family
            <= float(gate["maximum_projected_single_family_wall_hours"])
        )
        payload.update(
            {
                "conservative_master_solves_per_hour": (
                    conservative_master_rate
                ),
                "conservative_recourse_lp_solves_per_hour": (
                    conservative_recourse_rate
                ),
                "projected_family_wall_hours": planned,
                "projected_total_wall_hours": total,
                "projected_maximum_family_wall_hours": maximum_family,
                "compute_gate_passed": passed,
                "status": "passed" if passed else "failed",
                "formal_execution_authorized": (
                    passed
                    and matrix.get("status")
                    == "frozen_for_formal_execution"
                ),
            }
        )
    elif rates:
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
    _atomic_write_json(destination, payload)
    return payload

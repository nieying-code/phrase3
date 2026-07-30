"""Independent Phase 6 experiment-family protocols and reporting helpers.

This module intentionally stays outside ``PHASE6_E3_COMPONENT_FILES``.  It
adds E1/E2/E4/E5 work without changing the scientific fingerprint of the E3
cold/warm C&CG pilots.
"""

from __future__ import annotations

from copy import deepcopy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from time import sleep
from typing import Any, Iterable, Mapping, Sequence

import numpy as np

from .evaluation import EvaluationResult
from .model_data import ProcurementData
from .phase6_locking import exclusive_file_lock
from .phase6_protocol import (
    GeneratedPhase6Data,
    budget_values_for_tier,
    generate_phase6_data,
)
from .reproducibility import sha256_file


FAMILIES = ("E1", "E2", "E4", "E5")
POLICY_RATIOS = {
    "zero_reserve": 0.0,
    "fixed_reserve_0_10": 0.10,
    "fixed_reserve_0_30": 0.30,
    "fixed_reserve_0_50": 0.50,
}
FAMILY_REGISTRY_FIELDS = (
    "run_id",
    "parent_run_id",
    "family",
    "execution_mode",
    "tier_id",
    "seed",
    "status",
    "planned_work_units",
    "completed_work_units",
    "wall_seconds",
    "peak_memory_mb",
    "scientific_config_sha256",
    "family_config_sha256",
    "family_code_sha256",
    "environment_sha256",
    "started_at_utc",
    "updated_at_utc",
    "failure_stage",
    "failure_message",
    "result_path",
    "manifest_path",
)
FAMILY_COMPONENT_FILES = (
    "src/ccg.py",
    "src/evaluation.py",
    "src/extensive_model.py",
    "src/inventory_model.py",
    "src/model_common.py",
    "src/model_data.py",
    "src/parameters.py",
    "src/phase6_locking.py",
    "src/phase6_protocol.py",
    "src/phase6_runner.py",
    "src/recourse_model.py",
    "src/reproducibility.py",
    "src/scenario_generator.py",
    "src/phase6_families.py",
    "src/phase6_family_runner.py",
    "src/phase6_family_worker.py",
    "src/phase6_family_status.py",
    "src/run_phase6_family.py",
)
SCIENTIFIC_CONFIG_EXCLUDED_ROOT_FIELDS = (
    "status",
    "initial_draft_on",
    "revised_on",
)
ATOMIC_REPLACE_MAX_ATTEMPTS = 20
ATOMIC_REPLACE_RETRY_SECONDS = 0.05


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        for attempt in range(ATOMIC_REPLACE_MAX_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt + 1 == ATOMIC_REPLACE_MAX_ATTEMPTS:
                    raise
                sleep(ATOMIC_REPLACE_RETRY_SECONDS)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def _atomic_write_csv(
    path: Path,
    fieldnames: Sequence[str],
    rows: Iterable[Mapping[str, Any]],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}")
    with temporary.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    try:
        for attempt in range(ATOMIC_REPLACE_MAX_ATTEMPTS):
            try:
                os.replace(temporary, path)
                return
            except PermissionError:
                if attempt + 1 == ATOMIC_REPLACE_MAX_ATTEMPTS:
                    raise
                sleep(ATOMIC_REPLACE_RETRY_SECONDS)
    finally:
        if temporary.exists():
            try:
                temporary.unlink()
            except OSError:
                pass


def scientific_config_sha256(matrix: Mapping[str, Any]) -> str:
    """Return the lifecycle-independent scientific matrix fingerprint."""

    scientific = {
        key: value
        for key, value in matrix.items()
        if key not in SCIENTIFIC_CONFIG_EXCLUDED_ROOT_FIELDS
    }
    encoded = json.dumps(
        scientific,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def environment_sha256(locked_environment: Mapping[str, str]) -> str:
    """Hash the actual exact distribution versions used by a family run."""

    encoded = json.dumps(
        dict(sorted(locked_environment.items())),
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def family_code_sha256(project_root: Path) -> str:
    """Fingerprint every code dependency that can change family results."""

    digest = hashlib.sha256()
    for relative in FAMILY_COMPONENT_FILES:
        path = project_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"family component file is missing: {path}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def compact_failure(
    failure: Mapping[str, Any] | Any | None,
    *,
    message_limit: int = 1000,
) -> dict[str, Any] | None:
    """Return a bounded whitelist-only failure summary."""

    if failure is None:
        return None
    if not isinstance(failure, Mapping):
        return {"message": str(failure)[:message_limit]}
    fields = (
        "status",
        "stage",
        "message",
        "exception_type",
        "budget_index",
        "plan_index",
        "plan_id",
        "algorithm",
        "family",
    )
    compact: dict[str, Any] = {}
    for name in fields:
        value = failure.get(name)
        if value is None:
            continue
        if name == "message":
            compact[name] = str(value)[:message_limit]
        elif isinstance(value, str):
            compact[name] = value[:message_limit]
        elif isinstance(value, (int, float, bool)):
            compact[name] = value
        else:
            compact[name] = str(value)[:message_limit]
    return compact


def validate_family_run_artifacts(
    row: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Verify a registry row against its finalized result and manifest."""

    result_path = Path(str(row.get("result_path") or ""))
    manifest_path = Path(str(row.get("manifest_path") or ""))
    if not result_path.is_file():
        raise ValueError("family result artifact is missing")
    if not manifest_path.is_file():
        raise ValueError("family manifest artifact is missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if result.get("finalized") is not True:
        raise ValueError("family result is not finalized")
    if manifest.get("artifact_state") != "finalized":
        raise ValueError("family manifest is not finalized")
    if Path(str(manifest.get("result_path") or "")).resolve() != (
        result_path.resolve()
    ):
        raise ValueError("manifest result path does not match registry")
    if manifest.get("result_sha256") != sha256_file(result_path):
        raise ValueError("family result SHA-256 does not match manifest")
    scalar_checks = {
        "run_id": row.get("run_id"),
        "family": row.get("family"),
        "status": row.get("status"),
    }
    for name, expected in scalar_checks.items():
        if str(result.get(name)) != str(expected):
            raise ValueError(f"family result {name} does not match registry")
        if name != "status" and str(manifest.get(name)) != str(expected):
            raise ValueError(
                f"family manifest {name} does not match registry"
            )
    for name in ("planned_work_units", "completed_work_units"):
        if int(result.get(name, -1)) != int(row.get(name) or -2):
            raise ValueError(f"family result {name} does not match registry")
    if str(result.get("execution_mode") or "") != str(
        row.get("execution_mode") or ""
    ):
        raise ValueError(
            "family result execution_mode does not match registry"
        )
    try:
        result_seed = int(result["seed"])
        registry_seed = int(str(row.get("seed") or ""))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("family seed is not a valid integer") from exc
    if result_seed != registry_seed:
        raise ValueError("family result seed does not match registry")
    if str(result.get("parent_run_id") or "") != str(
        row.get("parent_run_id") or ""
    ):
        raise ValueError(
            "family result parent_run_id does not match registry"
        )
    try:
        result_wall_seconds = float(result["wall_seconds"])
        registry_wall_seconds = float(
            str(row.get("wall_seconds") or "")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "family wall_seconds is not a valid number"
        ) from exc
    if (
        not math.isfinite(result_wall_seconds)
        or not math.isfinite(registry_wall_seconds)
        or not math.isclose(
            result_wall_seconds,
            registry_wall_seconds,
            rel_tol=1e-12,
            abs_tol=1e-9,
        )
    ):
        raise ValueError(
            "family result wall_seconds does not match registry"
        )
    tier_ids = result.get("tier_ids")
    if not isinstance(tier_ids, list) or not tier_ids:
        raise ValueError("family result tier_ids is missing")
    result_tier_id = ",".join(str(value) for value in tier_ids)
    if result_tier_id != str(row.get("tier_id") or ""):
        raise ValueError("family result tier_ids does not match registry")
    fingerprints = result.get("fingerprints")
    if not isinstance(fingerprints, dict):
        raise ValueError("family result fingerprints are missing")
    for name in (
        "scientific_config_sha256",
        "family_config_sha256",
        "family_code_sha256",
        "environment_sha256",
    ):
        expected = str(row.get(name) or "")
        if str(fingerprints.get(name) or "") != expected:
            raise ValueError(f"family result {name} does not match registry")
        if str(manifest.get(name) or "") != expected:
            raise ValueError(f"family manifest {name} does not match registry")
    return result, manifest


def load_verified_plan_result(
    record: Mapping[str, Any],
) -> dict[str, Any]:
    """Load one worker result only when its recorded byte hash matches."""

    result_path = Path(str(record.get("result_path") or ""))
    expected_hash = str(record.get("result_sha256") or "")
    if not result_path.is_file() or not expected_hash:
        raise ValueError("family plan result artifact is incomplete")
    if sha256_file(result_path) != expected_hash:
        raise ValueError("family plan result SHA-256 mismatch")
    payload = json.loads(result_path.read_text(encoding="utf-8"))
    if payload.get("status") != "optimal":
        raise ValueError("family plan result is not optimal")
    if payload.get("plan_id") != record.get("plan_id"):
        raise ValueError("family plan result ID mismatch")
    return payload


def _formal_seeds(
    matrix: Mapping[str, Any],
    tier_id: str,
) -> tuple[int, ...]:
    raw = next(
        tier for tier in matrix["scale_tiers"] if tier["id"] == tier_id
    )
    if raw["formal_seed_selector"] == "development_seed_only":
        return (int(matrix["seed_plan"]["development_seed"]),)
    seeds = tuple(
        int(value) for value in matrix["seed_plan"]["formal_training_seeds"]
    )
    if raw["formal_seed_selector"] == "all_formal_training_seeds":
        return seeds
    return seeds[: int(raw["formal_seed_count"])]


def enumerate_e1_plans(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
) -> tuple[dict[str, Any], ...]:
    """Resolve all 45 extensive-versus-standard-C&CG plans."""

    plans: list[dict[str, Any]] = []
    for tier_id in matrix["exactness_gates"][
        "extensive_vs_standard_ccg"
    ]["tiers"]:
        budgets = budget_values_for_tier(
            matrix,
            str(tier_id),
            matrix_path=matrix_path,
        )
        for seed in _formal_seeds(matrix, str(tier_id)):
            for budget_index, budget in enumerate(budgets):
                plans.append(
                    {
                        "plan_id": (
                            f"E1_{tier_id}_{seed}_b{budget_index:02d}"
                        ),
                        "family": "E1",
                        "tier_id": str(tier_id),
                        "training_seed": seed,
                        "budget_index": budget_index,
                        "budget": float(budget),
                    }
                )
    return tuple(plans)


def enumerate_e2_plans(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
) -> tuple[dict[str, Any], ...]:
    """Resolve all 180 policy/training plans."""

    specification = matrix["model_comparison"]
    plans: list[dict[str, Any]] = []
    for tier_id in specification["tiers"]:
        budgets = budget_values_for_tier(
            matrix,
            str(tier_id),
            matrix_path=matrix_path,
        )
        factors = tuple(
            float(value) for value in specification["training_budget_factors"]
        )
        if len(budgets) != len(factors):
            raise ValueError("E2 budget factors do not match tier budgets")
        for seed in _formal_seeds(matrix, str(tier_id)):
            for budget_index, (factor, budget) in enumerate(
                zip(factors, budgets, strict=True)
            ):
                for policy in specification["policies"]:
                    plans.append(
                        {
                            "plan_id": (
                                f"E2_{tier_id}_{seed}_b{budget_index:02d}_"
                                f"{policy}"
                            ),
                            "family": "E2",
                            "tier_id": str(tier_id),
                            "training_seed": seed,
                            "budget_index": budget_index,
                            "budget_factor": factor,
                            "budget": float(budget),
                            "policy": str(policy),
                        }
                    )
    return tuple(plans)


def enumerate_e4_plans(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
) -> tuple[dict[str, Any], ...]:
    """Resolve the 90 trained-plan/sample-out pairs."""

    specification = matrix["out_of_sample_evaluation"]
    training = tuple(
        int(value) for value in matrix["seed_plan"]["formal_training_seeds"]
    )[: int(specification["training_seed_count"])]
    testing = tuple(
        int(value) for value in matrix["seed_plan"]["formal_test_seeds"]
    )[: int(specification["training_seed_count"])]
    if len(training) != len(testing):
        raise ValueError("E4 training and test seed counts differ")
    plans: list[dict[str, Any]] = []
    for tier_id in specification["tiers"]:
        budgets = budget_values_for_tier(
            matrix,
            str(tier_id),
            matrix_path=matrix_path,
        )
        factors = tuple(
            float(value) for value in specification["budget_factors"]
        )
        for training_seed, test_seed in zip(training, testing, strict=True):
            for budget_index, (factor, budget) in enumerate(
                zip(factors, budgets, strict=True)
            ):
                for policy in specification["policies"]:
                    e2_plan_id = (
                        f"E2_{tier_id}_{training_seed}_b{budget_index:02d}_"
                        f"{policy}"
                    )
                    plans.append(
                        {
                            "plan_id": (
                                f"E4_{tier_id}_{training_seed}_{test_seed}_"
                                f"b{budget_index:02d}_{policy}"
                            ),
                            "family": "E4",
                            "tier_id": str(tier_id),
                            "training_seed": training_seed,
                            "test_seed": test_seed,
                            "budget_index": budget_index,
                            "budget_factor": factor,
                            "budget": float(budget),
                            "policy": str(policy),
                            "source_e2_plan_id": e2_plan_id,
                        }
                    )
    return tuple(plans)


def sensitivity_configurations(
    matrix: Mapping[str, Any],
) -> tuple[dict[str, Any], ...]:
    """Resolve the 11 unique OFAT and four interaction configurations."""

    specification = matrix["sensitivity"]
    baseline = dict(specification["baseline_config"])
    configurations: list[dict[str, Any]] = [
        {
            "configuration_id": "baseline",
            "design": "ofat",
            "factor": "baseline",
            "value": None,
            "overrides": baseline,
        }
    ]
    for factor, raw in specification["one_factor_at_a_time"].items():
        baseline_value = raw["baseline"]
        for value in raw["values"]:
            if value == baseline_value:
                continue
            overrides = {**baseline, str(factor): value}
            configurations.append(
                {
                    "configuration_id": f"ofat_{factor}_{value}",
                    "design": "ofat",
                    "factor": str(factor),
                    "value": value,
                    "overrides": overrides,
                }
            )
    interaction = specification["inventory_market_interaction"]["factors"]
    for shelf_life in interaction["shelf_life_periods"]:
        for supply_reduction in interaction["supply_reduction_mean"]:
            configurations.append(
                {
                    "configuration_id": (
                        f"interaction_life_{shelf_life}_"
                        f"supply_{supply_reduction}"
                    ),
                    "design": "interaction",
                    "factor": "shelf_life_periods_x_supply_reduction_mean",
                    "value": [shelf_life, supply_reduction],
                    "overrides": {
                        **baseline,
                        "shelf_life_periods": shelf_life,
                        "supply_reduction_mean": supply_reduction,
                    },
                }
            )
    ofat = [row for row in configurations if row["design"] == "ofat"]
    interaction_rows = [
        row for row in configurations if row["design"] == "interaction"
    ]
    if len(ofat) != int(specification["unique_ofat_configuration_count"]):
        raise ValueError("E5 OFAT configuration count is inconsistent")
    if len(interaction_rows) != int(
        specification["inventory_market_interaction"]["runs_per_seed"]
    ):
        raise ValueError("E5 interaction configuration count is inconsistent")
    return tuple(configurations)


def enumerate_e5_plans(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
) -> tuple[dict[str, Any], ...]:
    """Resolve all 75 E5 sensitivity model executions."""

    specification = matrix["sensitivity"]
    seeds = tuple(
        int(value) for value in matrix["seed_plan"]["formal_training_seeds"]
    )[: int(specification["training_seed_count"])]
    tier_id = str(specification["tier"])
    reference = float(matrix["budget_plan"]["reference_budget_by_tier"][tier_id])
    factor = float(specification["budget_factors"][0])
    budget = reference * factor
    plans: list[dict[str, Any]] = []
    for seed in seeds:
        for configuration in sensitivity_configurations(matrix):
            plans.append(
                {
                    "plan_id": (
                        f"E5_{tier_id}_{seed}_"
                        f"{configuration['configuration_id']}"
                    ),
                    "family": "E5",
                    "tier_id": tier_id,
                    "training_seed": seed,
                    "budget_factor": factor,
                    "budget": budget,
                    **configuration,
                }
            )
    return tuple(plans)


def enumerate_family_plans(
    matrix: Mapping[str, Any],
    family: str,
    *,
    matrix_path: Path,
) -> tuple[dict[str, Any], ...]:
    """Resolve one complete formal experiment family."""

    normalized = family.upper()
    dispatch = {
        "E1": enumerate_e1_plans,
        "E2": enumerate_e2_plans,
        "E4": enumerate_e4_plans,
        "E5": enumerate_e5_plans,
    }
    if normalized not in dispatch:
        raise ValueError(f"unsupported Phase 6 family: {family}")
    return dispatch[normalized](matrix, matrix_path=matrix_path)


def apply_sensitivity_overrides(
    matrix: Mapping[str, Any],
    overrides: Mapping[str, Any],
) -> dict[str, Any]:
    """Return a generator matrix with one fully resolved E5 configuration."""

    resolved = deepcopy(matrix)
    baseline = resolved["controlled_synthetic_baseline"]
    for name in (
        "demand_cv",
        "emergency_price_markup_mean",
        "emergency_price_markup_sd",
        "supply_reduction_mean",
        "supply_shock_sd",
        "demand_price_correlation",
        "demand_supply_correlation",
        "shortage_penalty_multiplier",
        "waste_penalty_multiplier",
    ):
        baseline[name] = overrides[name]
    life = int(overrides["shelf_life_periods"])
    for archetype in baseline["item_archetypes"]:
        archetype["shelf_life_periods"] = life
    resolved["generator_protocol"]["deterministic_baselines"][
        "storage_capacity"
    ]["factor"] = float(
        overrides["storage_capacity_to_expected_period_demand"]
    )
    return resolved


def generate_oos_data(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
    tier_id: str,
    test_seed: int,
    budget: float,
) -> GeneratedPhase6Data:
    """Generate the independent 2,000-scenario E4 test set."""

    resolved = deepcopy(matrix)
    count = int(
        resolved["out_of_sample_evaluation"]["scenarios_per_training_seed"]
    )
    tier = next(
        row for row in resolved["scale_tiers"] if row["id"] == tier_id
    )
    tier["training_scenarios"] = count
    return generate_phase6_data(
        resolved,
        matrix_path=matrix_path,
        tier_id=tier_id,
        seed=int(test_seed),
        budget=float(budget),
    )


def _fractional_cvar(values: Sequence[float], tail_probability: float) -> float:
    if not values:
        raise ValueError("CVaR requires at least one value")
    if not 0.0 < tail_probability <= 1.0:
        raise ValueError("tail_probability must be in (0, 1]")
    ordered = sorted((float(value) for value in values), reverse=True)
    mass = tail_probability * len(ordered)
    complete = int(math.floor(mass))
    fraction = mass - complete
    total = sum(ordered[:complete])
    if fraction > 0.0:
        total += fraction * ordered[complete]
    return total / mass


def aggregate_oos_evaluation(
    data: ProcurementData,
    evaluation: EvaluationResult,
    *,
    reserve: float,
    shortage_tolerance: float = 1.0e-7,
    reserve_tolerance: float = 1.0e-9,
) -> dict[str, Any]:
    """Apply the frozen E4 status accounting and aggregate definitions."""

    total = len(data.scenarios)
    optimal = sum(
        result.status == "optimal"
        for result in evaluation.scenario_results.values()
    )
    infeasible = sum(
        result.status == "infeasible"
        for result in evaluation.scenario_results.values()
    )
    solver_failure = total - optimal - infeasible
    if total != optimal + infeasible + solver_failure:
        raise AssertionError("E4 terminal-category count identity failed")
    if solver_failure and infeasible:
        status = "incomplete_solver_failure_and_infeasible"
    elif solver_failure:
        status = "incomplete_solver_failure"
    elif infeasible:
        status = "contains_infeasible_recourse"
    else:
        status = "complete_feasible"
    result: dict[str, Any] = {
        "plan_oos_status": status,
        "total_scenario_count": total,
        "optimal_scenario_count": optimal,
        "optimal_evaluation_rate": optimal / total if total else None,
        "recourse_feasibility_rate": (
            optimal / total if total and solver_failure == 0 else None
        ),
        "infeasible_scenario_count": infeasible,
        "solver_failure_count": solver_failure,
        "zero_reserve_flag": reserve <= reserve_tolerance,
    }
    aggregate_names = (
        "mean_total_cost",
        "median_total_cost",
        "total_cost_p90",
        "total_cost_p95",
        "total_cost_p99",
        "total_cost_cvar95",
        "maximum_total_cost",
        "mean_shortage",
        "shortage_probability",
        "service_level",
        "mean_waste",
        "mean_emergency_spend",
        "reserve_utilization",
    )
    if status != "complete_feasible":
        result.update({name: None for name in aggregate_names})
        return result

    total_costs: list[float] = []
    shortages: list[float] = []
    wastes: list[float] = []
    spends: list[float] = []
    total_demand = 0.0
    total_shortage = 0.0
    for scenario in data.scenarios:
        recourse = evaluation.scenario_results[scenario]
        if recourse.objective is None or recourse.emergency_spend is None:
            raise AssertionError("optimal E4 recourse is missing cost values")
        shortage = sum(
            sum(float(value) for value in values)
            for values in recourse.shortage.values()
        )
        waste = sum(
            sum(float(value) for value in values)
            for values in recourse.waste.values()
        )
        demand = sum(
            sum(float(value) for value in data.demand[scenario][item])
            for item in data.items
        )
        total_costs.append(evaluation.regular_cost + recourse.objective)
        shortages.append(shortage)
        wastes.append(waste)
        spends.append(recourse.emergency_spend)
        total_demand += demand
        total_shortage += shortage
    array = np.asarray(total_costs, dtype=float)
    result.update(
        {
            "mean_total_cost": float(np.mean(array)),
            "median_total_cost": float(np.median(array)),
            "total_cost_p90": float(np.quantile(array, 0.90, method="linear")),
            "total_cost_p95": float(np.quantile(array, 0.95, method="linear")),
            "total_cost_p99": float(np.quantile(array, 0.99, method="linear")),
            "total_cost_cvar95": _fractional_cvar(total_costs, 0.05),
            "maximum_total_cost": max(total_costs),
            "mean_shortage": statistics.fmean(shortages),
            "shortage_probability": (
                sum(value > shortage_tolerance for value in shortages) / total
            ),
            "service_level": (
                1.0 - total_shortage / total_demand
                if total_demand > 0.0
                else 1.0
            ),
            "mean_waste": statistics.fmean(wastes),
            "mean_emergency_spend": statistics.fmean(spends),
            "reserve_utilization": (
                statistics.fmean(spend / reserve for spend in spends)
                if reserve > reserve_tolerance
                else None
            ),
        }
    )
    return result


def upsert_family_registry(
    output_root: Path,
    row: Mapping[str, Any],
) -> Path:
    """Upsert one immutable family-run summary under a process lock."""

    path = (
        output_root
        / "experiments"
        / "phase6"
        / "family_run_registry.csv"
    )
    lock_path = path.parent / ".aggregate.lock"
    with exclusive_file_lock(lock_path):
        existing: list[dict[str, Any]] = []
        if path.exists():
            with path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                existing = list(csv.DictReader(handle))
        run_id = str(row["run_id"])
        if any(current.get("run_id") == run_id for current in existing):
            raise ValueError(
                f"family registry already contains immutable run_id {run_id}"
            )
        existing.append(
            {name: row.get(name) for name in FAMILY_REGISTRY_FIELDS}
        )
        _atomic_write_csv(path, FAMILY_REGISTRY_FIELDS, existing)
    return path


def update_family_projection(
    *,
    output_root: Path,
    matrix: Mapping[str, Any],
    scientific_config_hash: str,
    family_config_hash: str,
    family_code_hash: str,
    environment_hash: str,
) -> dict[str, Any]:
    """Add dimensionally consistent E1/E2/E4/E5 rates to the E3 gate."""

    base = output_root / "experiments" / "phase6"
    projection_path = base / "pilot_throughput_projection.json"
    registry_path = base / "family_run_registry.csv"
    if not projection_path.exists():
        raise ValueError("E3 pilot projection does not exist")
    with exclusive_file_lock(base / ".aggregate.lock"):
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
        rows: list[dict[str, str]] = []
        if registry_path.exists():
            with registry_path.open(
                "r", encoding="utf-8-sig", newline=""
            ) as handle:
                rows = list(csv.DictReader(handle))
        fingerprint_candidates = [
            row for row in rows
            if (
                row.get("scientific_config_sha256")
                == scientific_config_hash
                and row.get("family_config_sha256")
                == family_config_hash
                and row.get("family_code_sha256") == family_code_hash
                and row.get("environment_sha256") == environment_hash
            )
        ]
        artifact_errors: dict[str, str] = {}
        for row in fingerprint_candidates:
            try:
                validate_family_run_artifacts(row)
            except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                artifact_errors[str(row.get("run_id"))] = (
                    f"{type(exc).__name__}: {exc}"
                )
        matching = [
            row for row in fingerprint_candidates
            if (
                row.get("execution_mode") == "pilot"
                and not row.get("parent_run_id", "").strip()
            )
        ]
        workload = matrix["workload_estimation"]
        work_units = {
            "E1": int(workload["E1_exactness_plan_count"]),
            "E2": int(workload["E2_policy_plan_count"]),
            "E4": int(workload["E4_out_of_sample_plan_count"]),
            "E5": int(workload["E5_total_model_executions"]),
        }
        family_projection: dict[str, Any] = {}
        required_seeds = tuple(
            int(value)
            for value in matrix["seed_plan"]["pilot_training_seeds"]
        )
        for family in FAMILIES:
            family_artifact_errors = {
                str(row.get("run_id")): artifact_errors[
                    str(row.get("run_id"))
                ]
                for row in fingerprint_candidates
                if (
                    row.get("family") == family
                    and str(row.get("run_id")) in artifact_errors
                )
            }
            candidates = [
                row for row in matching if row.get("family") == family
            ]
            by_seed = {
                seed: [
                    row
                    for row in candidates
                    if int(row.get("seed") or -1) == seed
                ]
                for seed in required_seeds
            }
            missing = [
                seed for seed, rows_for_seed in by_seed.items()
                if not rows_for_seed
            ]
            duplicate = {
                str(seed): sorted(row["run_id"] for row in rows_for_seed)
                for seed, rows_for_seed in by_seed.items()
                if len(rows_for_seed) > 1
            }
            unique = [
                rows_for_seed[0]
                for rows_for_seed in by_seed.values()
                if len(rows_for_seed) == 1
            ]
            failed = [
                row["run_id"]
                for row in unique
                if (
                    row["run_id"] in artifact_errors
                    or
                    row.get("status") != "optimal"
                    or float(row.get("wall_seconds") or 0.0) <= 0.0
                    or int(row.get("completed_work_units") or 0)
                    != int(row.get("planned_work_units") or -1)
                )
            ]
            successful = [
                row for row in unique if row["run_id"] not in failed
            ]
            if family_artifact_errors:
                family_projection[family] = {
                    "status": "family_pilot_failure",
                    "failed_run_ids": sorted(family_artifact_errors),
                    "artifact_errors": family_artifact_errors,
                }
                continue
            if missing:
                family_projection[family] = {
                    "status": "awaiting_family_pilot",
                    "work_unit": "complete_family_plan",
                    "required_seeds": list(required_seeds),
                    "missing_seeds": missing,
                }
                continue
            if duplicate:
                family_projection[family] = {
                    "status": "ambiguous_family_pilots",
                    "duplicate_primary_runs": duplicate,
                }
                continue
            if failed:
                family_projection[family] = {
                    "status": "family_pilot_failure",
                    "failed_run_ids": sorted(failed),
                    "artifact_errors": {
                        run_id: artifact_errors[run_id]
                        for run_id in sorted(failed)
                        if run_id in artifact_errors
                    },
                }
                continue
            rates = [
                int(row["completed_work_units"])
                / (float(row["wall_seconds"]) / 3600.0)
                for row in successful
            ]
            conservative_rate = min(rates)
            family_projection[family] = {
                "status": "projected",
                "work_unit": "complete_family_plan",
                "pilot_run_ids": sorted(row["run_id"] for row in successful),
                "pilot_seeds": list(required_seeds),
                "conservative_work_units_per_hour": conservative_rate,
                "planned_work_units": work_units[family],
                "projected_wall_hours": (
                    work_units[family] / conservative_rate
                ),
            }
        projection["family_projection"].update(family_projection)
        projected = [
            value["projected_wall_hours"]
            for value in projection["family_projection"].values()
            if value.get("status") == "projected"
        ]
        all_families_projected = all(
            projection["family_projection"].get(family, {}).get("status")
            == "projected"
            for family in ("E1", "E2", "E3", "E4", "E5")
        )
        total_hours = sum(projected) if all_families_projected else None
        thresholds = workload["pilot_throughput_gate"]
        time_gate = (
            all_families_projected
            and total_hours is not None
            and total_hours
            <= float(thresholds["maximum_projected_total_wall_hours"])
            and max(projected)
            <= float(
                thresholds["maximum_projected_single_family_wall_hours"]
            )
        )
        e3_complete = (
            int(projection.get("completed_run_count", 0))
            == int(projection.get("required_run_count", 0))
            and not projection.get("missing_runs")
            and not projection.get("failed_primary_runs")
            and not projection.get("duplicate_primary_runs")
        )
        compute_gate = bool(time_gate and e3_complete)
        frozen = matrix.get("status") == "frozen_for_formal_execution"
        projection.update(
            {
                "family_scientific_config_sha256": scientific_config_hash,
                "family_config_sha256": family_config_hash,
                "family_code_sha256": family_code_hash,
                "family_environment_sha256": environment_hash,
                "projected_total_wall_hours": total_hours,
                "compute_gate_passed": compute_gate,
                "formal_execution_authorized": bool(
                    compute_gate and frozen
                ),
                "status": (
                    "passed"
                    if compute_gate and frozen
                    else "matrix_not_frozen"
                    if compute_gate
                    else "projection_incomplete"
                ),
            }
        )
        _atomic_write_json(projection_path, projection)
    return projection

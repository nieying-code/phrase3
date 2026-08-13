"""Safe executor and projection for the frozen M2C2 confirmation matrix."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import asdict, dataclass, fields, replace
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import yaml

from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes, sha256_lf_text_file
from .phase6_locking import exclusive_file_lock
from .model_data import ProcurementData
from .phase6_m2 import (
    M2_E3_COMPONENT_FILES,
    M2_FAMILY_COMPONENT_FILES,
    DisruptedProcurementData,
    GeneratedM2Data,
    _normal_cdf,
    _sha256_payload,
    fulfillment_statistics,
    joint_scenario_identities,
    m2_model_context,
    reconstruct_frozen_demand_latent,
    resolve_supply_disruption_profile,
    solve_m2_endogenous_extensive,
    solve_m2_fixed_reserve,
)
from .phase6_m2_development import (
    DevelopmentCase,
    DevelopmentStageError,
    PeakRSSSampler,
    _decision_sha256,
    _failure_counts,
    _native_failure_status,
    _require_optimal,
    compact_failure,
    validate_run_id,
)
from .phase6_protocol import (
    GeneratedPhase6Data,
    TierSpec,
    _regular_price,
    _seasonality,
    generate_phase6_data,
    load_phase6_matrix,
    resolve_tier,
)
from .phase6_m1 import (
    analyze_reserve_interval,
    objective_tolerance,
    solve_minimum_feasible_reserve,
    solve_reserve_face_point,
)
from .evaluation import evaluate_first_stage
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2c2_confirmation_v1_0"
RUNNER_NAMESPACE = PROTOCOL_ID
OUTPUT_ROOT = "outputs/phase6_m2c2_confirmation_v1_0"
READY_STATUS = "frozen_for_confirmation_execution"
APPROVAL_PATH = "configs/phase6_m2c2_confirmation_approval.yaml"
PARENT_AUDIT_PATH = "docs/handoffs/2026-08-13_phase6_m2_threshold_refinement_grid_audit.json"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256", "e3_component_sha256",
    "family_component_sha256", "runner_config_sha256", "environment_sha256",
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "tier_id", "seed", "beta",
    "profile_id", "status", "wall_seconds", "peak_memory_mb",
    *FINGERPRINT_FIELDS, "result_path", "manifest_path", "manifest_sha256",
    "failure_stage", "updated_at_utc",
)
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2c2_confirmation.py",
    "src/run_phase6_m2c2_confirmation.py",
    "src/phase6_m2c2_confirmation_status.py",
    "configs/phase6_m2_two_item_confirmation.yaml",
    "configs/phase6_m2c2_confirmation_runner.yaml",
    PARENT_AUDIT_PATH,
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


@dataclass(frozen=True)
class ConfirmationCase:
    case_id: str
    tier_id: str
    seed: int
    beta: float
    profile_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_confirmation_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("unsupported M2C2 confirmation protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE or payload.get("output_root") != OUTPUT_ROOT:
        raise ValueError("M2C2 confirmation identity mismatch")
    raw = payload.get("confirmation_preregistration") or {}
    if tuple(raw.get("seeds", ())) != (2026081301, 2026081302, 2026081303, 2026081304, 2026081305):
        raise ValueError("unexpected M2C2 confirmation seeds")
    if tuple(float(v) for v in raw.get("beta", ())) != (1.1, 1.3):
        raise ValueError("unexpected M2C2 confirmation beta values")
    profiles = raw.get("profiles") or {}
    if tuple(profiles) != ("C0", "C1", "T03"):
        raise ValueError("M2C2 profiles must be C0/C1/T03")
    expected = {
        "C0": {"enabled": False, "loss_scale": 0.0, "recovery_fraction": 0.0, "role": "no_disruption_control"},
        "C1": {"enabled": True, "loss_scale": 0.2, "recovery_fraction": 0.0, "role": "light_disruption_control"},
        "T03": {"enabled": True, "loss_scale": 0.3, "recovery_fraction": 0.0, "role": "threshold_neighborhood_treatment"},
    }
    if profiles != expected:
        raise ValueError("unexpected frozen M2C2 profiles")
    if int(raw.get("configuration_count", -1)) != 30:
        raise ValueError("M2C2 confirmation matrix must contain 30 cases")
    if payload.get("scientific_model", {}).get("tier_id") != "M2C2":
        raise ValueError("M2C2 tier identity is missing")
    if payload.get("execution_boundaries", {}).get("runner_implemented") is not True:
        raise ValueError("M2C2 runner implementation is not enabled")
    return payload


def build_confirmation_cases(config: Mapping[str, Any]) -> tuple[ConfirmationCase, ...]:
    raw = config["confirmation_preregistration"]
    cases = tuple(
        ConfirmationCase(
            case_id=f"M2C2_seed{seed}_beta{float(beta):.2f}_profile{profile}".replace(".", "p"),
            tier_id="M2C2", seed=int(seed), beta=float(beta), profile_id=str(profile),
        )
        for seed in raw["seeds"] for beta in raw["beta"] for profile in raw["profiles"]
    )
    if len(cases) != 30 or len({case.case_id for case in cases}) != 30:
        raise ValueError("M2C2 cases are not a unique 30-case Cartesian product")
    return cases


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def confirmation_fingerprints(root: Path, config_path: Path, runner_path: Path) -> dict[str, str]:
    config = load_confirmation_config(config_path)
    scientific = {k: v for k, v in config.items() if k not in LIFECYCLE_FIELDS}
    scientific_hash = hashlib.sha256(json.dumps(
        scientific, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": scientific_hash,
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def load_parent_evidence(root: Path, expected_sha256: str) -> dict[str, Any]:
    path = root / PARENT_AUDIT_PATH
    if sha256_file(path) != expected_sha256:
        raise ValueError("approved parent M2 audit hash mismatch")
    audit = json.loads(path.read_text(encoding="utf-8"))
    projection = audit.get("projection") or {}
    if projection.get("overall_decision") != "permit_separate_multi_item_design_PR_only":
        raise ValueError("parent M2 decision does not permit a two-item design")
    expected = [
        {"beta": 1.1, "profile_id": "T03"},
        {"beta": 1.3, "profile_id": "T03"},
    ]
    if projection.get("eligible_moderate_combinations") != expected:
        raise ValueError("parent M2 eligible combinations mismatch")
    if projection.get("formal_extension_authorized") is not False or audit.get("formal_extension_authorized") is not False:
        raise ValueError("parent M2 evidence must not authorize formal execution")
    return audit


def _science_config(root: Path, confirmation: Mapping[str, Any]) -> dict[str, Any]:
    parent_path = root / "configs/phase6_m2_supply_disruption.yaml"
    parent = yaml.safe_load(parent_path.read_text(encoding="utf-8"))
    combined = deepcopy(parent)
    combined["disruption_profiles"] = {
        key: {
            field: value[field]
            for field in ("enabled", "loss_scale", "recovery_fraction")
        }
        for key, value in confirmation["confirmation_preregistration"]["profiles"].items()
    }
    return combined


def apply_m2c2_supply_disruption(
    generated: GeneratedPhase6Data,
    *,
    profile: Any,
    demand_latent: Mapping[str, Mapping[str, Sequence[float]]],
    item_vulnerability_multiplier: Mapping[str, float],
) -> GeneratedM2Data:
    """M2C2-only heterogeneous fulfillment without changing the M2 baseline."""
    data = generated.data
    denominator = max(1, data.periods - 1)
    rates: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario in data.scenarios:
        rates[scenario] = {}
        for item in data.items:
            vulnerability = float(item_vulnerability_multiplier[item])
            if not math.isfinite(vulnerability) or vulnerability <= 0.0:
                raise ValueError("M2C2 vulnerability must be finite and positive")
            if not profile.enabled:
                rates[scenario][item] = tuple(1.0 for _ in range(data.periods))
                continue
            values = []
            for t in range(data.periods):
                severity = _normal_cdf(float(demand_latent[scenario][item][t]))
                recovery = 1.0 - profile.recovery_fraction * t / denominator
                alpha = 1.0 - profile.loss_scale * vulnerability * severity * recovery
                values.append(min(1.0, max(0.0, alpha)))
            rates[scenario][item] = tuple(values)
    base_fields = {field.name: getattr(data, field.name) for field in fields(ProcurementData)}
    disrupted = DisruptedProcurementData(
        **base_fields,
        regular_fulfillment_rate=rates,
        m2_demand_latent=demand_latent,
    )
    disrupted.validate()
    wrapped = replace(generated, data=disrupted)
    identities = joint_scenario_identities(disrupted, demand_latent)
    set_hash = _sha256_payload([identities[s].as_dict() for s in disrupted.scenarios])
    return GeneratedM2Data(
        wrapped,
        profile,
        fulfillment_statistics(disrupted),
        identities,
        set_hash,
    )


def _confirmation_component_hashes(generated: GeneratedM2Data) -> dict[str, str]:
    """Component hashes, including the ordered scenario identity sequence."""
    return {
        **generated.component_set_sha256,
        "scenario_order_sha256": _sha256_payload(list(generated.data.scenarios)),
    }


def _m2c2_matrix(matrix: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(matrix)
    template = next(item for item in result["scale_tiers"] if item["id"] == "V1")
    tier = deepcopy(template)
    tier.update(id="M2C2", label="two_item_confirmation", items=2)
    result["scale_tiers"] = [*result["scale_tiers"], tier]
    result["budget_plan"]["reference_budget_by_tier"]["M2C2"] = float(
        config["two_item_deterministic_baseline"]["reference_budget"]["exact_value"]
    )
    return result


def recompute_m2c2_deterministic_baseline(
    matrix: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    model = config["scientific_model"]
    periods = int(model["periods"])
    seasonality = _seasonality(matrix, periods)
    total = 0.0
    period_demand = [0.0] * periods
    base = float(config["two_item_deterministic_baseline"]["reference_budget"]["first_item_base_demand_per_period"])
    for item in model["items"]:
        prices = _regular_price(
            matrix,
            periods=periods,
            multiplier=float(item["regular_price_multiplier"]),
        )
        for t in range(periods):
            mean = base * float(item["demand_multiplier"]) * seasonality[t]
            total += prices[t] * mean
            period_demand[t] += mean
    factor = float(config["two_item_deterministic_baseline"]["storage_capacity"]["factor"])
    return {
        "reference_budget": total,
        "budgets": {str(beta): beta * total for beta in (1.1, 1.3)},
        "storage_capacity": [factor * value for value in period_demand],
    }


def _validate_m2c2_baseline(matrix: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    actual = recompute_m2c2_deterministic_baseline(matrix, config)
    frozen = config["two_item_deterministic_baseline"]
    tolerance = 1.0e-9
    if not math.isclose(actual["reference_budget"], float(frozen["reference_budget"]["exact_value"]), rel_tol=0.0, abs_tol=tolerance):
        raise ValueError("M2C2 reference budget mismatch")
    for beta in (1.1, 1.3):
        if not math.isclose(actual["budgets"][str(beta)], float(frozen["budgets_by_beta"][str(beta)]), rel_tol=0.0, abs_tol=tolerance):
            raise ValueError("M2C2 budget mismatch")
    if any(not math.isclose(a, float(b), rel_tol=0.0, abs_tol=tolerance) for a, b in zip(actual["storage_capacity"], frozen["storage_capacity"]["values"], strict=True)):
        raise ValueError("M2C2 storage capacity mismatch")
    return actual


def _cross_item_metrics(data: Any, endpoint: Any, tolerance: float) -> dict[str, Any]:
    scenario_spend: dict[str, dict[str, float]] = {}
    shares: list[float] = []
    item_positive = {item: False for item in data.items}
    positive_total = 0
    for scenario, recourse in endpoint.evaluation.scenario_results.items():
        item_spend = {
            item: sum(
                float(data.emergency_price[scenario][item][t])
                * float(recourse.emergency_purchase[item][t])
                for t in range(data.periods)
            )
            for item in data.items
        }
        total = sum(item_spend.values())
        scenario_spend[scenario] = {**item_spend, "total": total}
        for item, value in item_spend.items():
            item_positive[item] = item_positive[item] or value > tolerance
        if total > tolerance:
            positive_total += 1
            shares.append(item_spend[data.items[0]] / total)
    share_range = max(shares) - min(shares) if len(shares) >= 2 else 0.0
    return {
        "plan_source": "complete_extensive_model_R_min_opt_endpoint",
        "scenario_count": len(scenario_spend),
        "scenario_item_emergency_spend": scenario_spend,
        "positive_total_emergency_spend_scenario_count": positive_total,
        "both_items_each_positive_in_at_least_one_scenario": all(item_positive.values()),
        "item1_emergency_spend_share_range": share_range,
        "gate_passed": (
            positive_total >= 2
            and all(item_positive.values())
            and share_range >= 1.0e-4
        ),
    }


def _evaluation_max_difference(left: Any, right: Any) -> float:
    if left.status != "optimal" or right.status != "optimal":
        raise ValueError("C0 equivalence exact recourse evaluation is non-optimal")
    if set(left.exact_scenario_costs) != set(right.exact_scenario_costs):
        raise ValueError("C0 equivalence scenario identities mismatch")
    return max(
        abs(left.exact_scenario_costs[name] - right.exact_scenario_costs[name])
        for name in left.exact_scenario_costs
    )


def _evaluate_c0_equivalence(
    *, base_data: Any, c0_data: Any, c0_optimum: Any,
    c0_minimum: Any, c0_maximum: Any, absolute: float, relative: float,
    seconds: float,
) -> dict[str, Any]:
    baseline = analyze_reserve_interval(
        base_data,
        absolute_tolerance=absolute,
        relative_tolerance=relative,
        solver_preference=("gurobi",),
        time_limit_seconds=seconds,
        solver_threads=1,
    )
    if baseline.status != "optimal":
        raise DevelopmentStageError(
            "C0_no_disruption_equivalence",
            baseline.status,
            "baseline reserve interval failed",
        )
    base_minimum = baseline.minimum_tolerance_optimal
    base_maximum = baseline.maximum_tolerance_optimal
    if base_minimum is None or base_maximum is None:
        raise RuntimeError("baseline reserve interval endpoints are missing")
    c0_on_base = evaluate_first_stage(
        base_data, c0_minimum.regular_purchase, float(c0_minimum.reserve),
        time_limit_seconds=seconds, solver_threads=1,
    )
    with m2_model_context():
        base_on_c0 = evaluate_first_stage(
            c0_data, base_minimum.regular_purchase, float(base_minimum.reserve),
            time_limit_seconds=seconds, solver_threads=1,
        )
    c0_native = c0_minimum.evaluation
    base_native = base_minimum.evaluation
    max_c0_to_base = _evaluation_max_difference(c0_native, c0_on_base)
    max_base_to_c0 = _evaluation_max_difference(base_native, base_on_c0)
    objective_difference = abs(
        float(c0_optimum.objective) - float(baseline.optimum.objective)
    )
    interval_differences = {
        "minimum": abs(float(c0_minimum.reserve) - float(base_minimum.reserve)),
        "maximum": abs(float(c0_maximum.reserve) - float(base_maximum.reserve)),
    }
    tolerance = max(
        objective_tolerance(
            float(c0_optimum.objective),
            absolute_tolerance=absolute,
            relative_tolerance=relative,
        ),
        objective_tolerance(
            float(baseline.optimum.objective),
            absolute_tolerance=absolute,
            relative_tolerance=relative,
        ),
    )
    passed = (
        objective_difference <= tolerance
        and max(interval_differences.values()) <= tolerance
        and max_c0_to_base <= tolerance
        and max_base_to_c0 <= tolerance
        and all(
            float(c0_data.regular_fulfillment_rate[s][i][t]) == 1.0
            for s in c0_data.scenarios
            for i in c0_data.items
            for t in range(c0_data.periods)
        )
    )
    return {
        "required": True,
        "status": "passed" if passed else "failed",
        "robust_objective_difference": objective_difference,
        "reserve_interval_endpoint_differences": interval_differences,
        "M2C0_plan_evaluated_in_no_disruption_max_scenario_cost_difference": max_c0_to_base,
        "no_disruption_plan_evaluated_in_M2C0_max_scenario_cost_difference": max_base_to_c0,
        "fulfillment_exactly_one": True,
        "scenario_count_each_direction": len(c0_native.exact_scenario_costs),
    }


def execute_confirmation_science(**kwargs: Any) -> dict[str, Any]:
    root = kwargs["project_root"]
    config = kwargs["config"]
    case: ConfirmationCase = kwargs["case"]
    progress = kwargs["progress"]
    matrix = _m2c2_matrix(kwargs["matrix"], config)
    baseline = _validate_m2c2_baseline(matrix, config)
    reference = baseline["reference_budget"]
    budget = baseline["budgets"][str(case.beta)]
    progress("scenario_generation", {"budget": budget, "reference_budget": reference})
    base_generated = generate_phase6_data(
        matrix,
        matrix_path=kwargs["matrix_path"],
        tier_id="M2C2",
        seed=case.seed,
        budget=budget,
    )
    expected_capacity = tuple(baseline["storage_capacity"])
    if any(not math.isclose(a, b, rel_tol=0.0, abs_tol=1.0e-9) for a, b in zip(base_generated.data.storage_capacity, expected_capacity, strict=True)):
        raise ValueError("generated M2C2 storage capacity mismatch")
    m2_config = _science_config(root, config)
    latent = reconstruct_frozen_demand_latent(matrix, base_generated)
    vulnerability = {
        item["id"]: float(item["supply_vulnerability_multiplier"])
        for item in config["scientific_model"]["items"]
    }
    generated = apply_m2c2_supply_disruption(
        base_generated,
        profile=resolve_supply_disruption_profile(m2_config, case.profile_id),
        demand_latent=latent,
        item_vulnerability_multiplier=vulnerability,
    )
    data = generated.data
    seconds = float(base_generated.tier.solver_call_seconds)
    absolute = 1.0e-5
    relative = 1.0e-7
    progress("minimum_feasible_reserve", {})
    floor = solve_minimum_feasible_reserve(data, solver_threads=1, time_limit_seconds=seconds)
    _require_optimal("minimum_feasible_reserve", floor.status, f"minimum feasible reserve failed: {floor.status}")
    progress("complete_extensive_optimum", {})
    optimum = solve_m2_endogenous_extensive(data, solver_threads=1, time_limit_seconds=seconds, consistency_tolerance=absolute)
    _require_optimal("complete_extensive_optimum", _native_failure_status(optimum), f"complete extensive optimum failed: {optimum.status}")
    if optimum.objective is None or optimum.master.objective is None:
        raise RuntimeError("complete extensive optimum returned no objective")
    tolerance = objective_tolerance(float(optimum.objective), absolute_tolerance=absolute, relative_tolerance=relative)
    common = dict(
        data=data,
        master_optimum=float(optimum.master.objective),
        exact_optimum=float(optimum.objective),
        tolerance=tolerance,
        solver_preference=("gurobi",),
        time_limit_seconds=seconds,
        solver_threads=1,
        feasibility_tolerance=1.0e-7,
        optimality_tolerance=1.0e-7,
    )
    progress("minimum_tolerance_optimal_reserve", {})
    with m2_model_context():
        minimum = solve_reserve_face_point(direction="min", **common)
    _require_optimal("minimum_tolerance_optimal_reserve", _native_failure_status(minimum), f"minimum optimal reserve failed: {minimum.status}")
    progress("maximum_tolerance_optimal_reserve", {})
    with m2_model_context():
        maximum = solve_reserve_face_point(direction="max", **common)
    _require_optimal("maximum_tolerance_optimal_reserve", _native_failure_status(maximum), f"maximum optimal reserve failed: {maximum.status}")
    fixed = []
    for rho in (0.0, 0.1, 0.3, 0.5):
        progress(f"fixed_total_reserve_{rho:.1f}", {"rho": rho})
        solution = solve_m2_fixed_reserve(data, reserve_ratio=rho, solver_threads=1, time_limit_seconds=seconds, consistency_tolerance=absolute)
        _require_optimal(f"fixed_total_reserve_{rho:.1f}", _native_failure_status(solution), f"fixed reserve rho={rho} failed: {solution.status}")
        fixed.append({
            "rho": rho,
            "reserve": solution.reserve,
            "objective": solution.objective,
            "regular_purchase_sha256": _decision_sha256(solution.master.regular_purchase),
            "regular_purchase_reoptimized": True,
            "status": solution.status,
        })
    endpoint_counts = {"minimum": _failure_counts(minimum.evaluation), "maximum": _failure_counts(maximum.evaluation)}
    if any(sum(values.values()) for values in endpoint_counts.values()):
        raise RuntimeError("M2C2 endpoint exact recourse evaluation is incomplete")
    ratio = max(0.0, float(minimum.reserve) - float(floor.reserve)) / budget
    science = {
        "tier_id": "M2C2", "seed": case.seed, "beta": case.beta,
        "profile_id": case.profile_id, "budget": budget,
        "reference_budget": reference, "storage_capacity": list(expected_capacity),
        "R_star": optimum.reserve, "R_min_feas": floor.reserve,
        "R_min_opt": minimum.reserve, "R_max_opt": maximum.reserve,
        "R_min_robust_opt": max(0.0, float(minimum.reserve) - float(floor.reserve)),
        "R_min_robust_opt_ratio": ratio,
        "numerical_activation": ratio > 1.0e-4,
        "substantive_activation": ratio >= 0.01,
        "moderate_activation": 0.05 <= ratio <= 0.50,
        "objective_tolerance": tolerance,
        "complete_extensive_objective": optimum.objective,
        "minimum_endpoint_status": minimum.status,
        "maximum_endpoint_status": maximum.status,
        "minimum_endpoint_exact_objective": minimum.exact_objective,
        "maximum_endpoint_exact_objective": maximum.exact_objective,
        "minimum_endpoint_consistency_difference": abs(float(minimum.exact_objective) - float(optimum.objective)),
        "maximum_endpoint_consistency_difference": abs(float(maximum.exact_objective) - float(optimum.objective)),
        "minimum_endpoint_regular_purchase_sha256": _decision_sha256(minimum.regular_purchase),
        "maximum_endpoint_regular_purchase_sha256": _decision_sha256(maximum.regular_purchase),
        "fixed_reserve_policies": fixed,
        "fulfillment_statistics": generated.statistics.as_dict(),
        "joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
        "scenario_component_set_sha256": _confirmation_component_hashes(generated),
        "scenario_identity_count": len(generated.scenario_identities),
        "endpoint_failure_counts": endpoint_counts,
        "cross_item_allocation": _cross_item_metrics(data, minimum, 1.0e-7),
        "c0_alpha_exactly_one": case.profile_id != "C0" or all(float(v) == 1.0 for s in data.scenarios for i in data.items for v in data.regular_fulfillment_rate[s][i]),
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }
    # The complete C0 equivalence computation is deliberately an explicit
    # scientific stage, so a runner cannot treat zero activation as sufficient.
    if case.profile_id == "C0":
        progress("C0_no_disruption_equivalence", {})
        science["c0_equivalence"] = _evaluate_c0_equivalence(
            base_data=base_generated.data,
            c0_data=data,
            c0_optimum=optimum,
            c0_minimum=minimum,
            c0_maximum=maximum,
            absolute=absolute,
            relative=relative,
            seconds=seconds,
        )
        if science["c0_equivalence"]["status"] != "passed":
            raise RuntimeError("C0 failed full no-disruption equivalence")
    else:
        science["c0_equivalence"] = {
            "required": False,
            "status": "not_applicable",
        }
    return science


def validate_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_confirmation_config(config_path)
    if config.get("status") != READY_STATUS:
        raise RuntimeError("M2C2 confirmation matrix is not frozen")
    if not authorize:
        raise PermissionError("--authorize-confirmation-execution is required")
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("M2C2 confirmation runner identity mismatch")
    execution = runner.get("execution") or {}
    if execution.get("confirmation_execution_requires_explicit_authorization") is not True:
        raise RuntimeError("explicit authorization guard is disabled")
    if execution.get("M0_M1_or_single_item_M2_authorization_forbidden") is not True:
        raise RuntimeError("M2C2 authorization isolation guard mismatch")
    if execution.get("formal_extension_authorized") is not False:
        raise RuntimeError("M2C2 formal-extension isolation guard mismatch")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    expected_metadata = {
        "approval_id": "phase6_m2c2_confirmation_execution_v1_0",
        "status": READY_STATUS, "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": RUNNER_NAMESPACE, "matrix_case_count": 30,
        "explicit_cli_authorization_required": True,
        "formal_extension_authorized": False,
        "accept_prior_track_authorization": False,
    }
    if any(approval.get(k) != v for k, v in expected_metadata.items()):
        raise RuntimeError("M2C2 confirmation approval metadata mismatch")
    actual = confirmation_fingerprints(root, config_path, runner_path)
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("M2C2 confirmation fingerprint mismatch")
    matrix = load_phase6_matrix(root / "configs/phase6_experiment_matrix.yaml")
    baseline = _validate_m2c2_baseline(matrix, config)
    parent = load_parent_evidence(root, config["parent_evidence"]["threshold_audit_sha256"])
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [config_path, runner_path, approval_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    return {
        "config": config, "runner": runner, "approval": approval,
        "fingerprints": actual, "parent_evidence": parent,
        "deterministic_baseline": baseline,
        "locked_environment": validate_locked_environment(root), "source": source,
    }


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_registry(root: Path, row: Mapping[str, Any]) -> None:
    path = root / "confirmation/confirmation_run_registry.csv"
    with exclusive_file_lock(root / "confirmation/.registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("M2C2 confirmation run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _validate_artifact(row: Mapping[str, str]) -> dict[str, Any]:
    result_path, manifest_path = Path(row["result_path"]), Path(row["manifest_path"])
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256_file(result_path) != manifest["result_sha256"]:
        raise ValueError("result hash mismatch")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("finalized") is not True or result.get("run_id") != row["run_id"]:
        raise ValueError("result is not finalized or identity mismatches")
    if manifest.get("artifact_state") != "finalized":
        raise ValueError("manifest is not finalized")
    if manifest.get("run_id") != row["run_id"] or manifest.get("case_id") != row["case_id"]:
        raise ValueError("manifest identity mismatches registry")
    if result.get("case_id") != row["case_id"] or result.get("status") != row["status"]:
        raise ValueError("result identity or status mismatches registry")
    case = result.get("case") or {}
    if (
        case.get("tier_id") != row["tier_id"]
        or int(case.get("seed")) != int(row["seed"])
        or not math.isclose(float(case.get("beta")), float(row["beta"]), rel_tol=0.0, abs_tol=1e-12)
        or case.get("profile_id") != row["profile_id"]
    ):
        raise ValueError("result case identity mismatches registry")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("result parent identity mismatches registry")
    wall = float(row["wall_seconds"])
    if not math.isfinite(wall) or not math.isclose(wall, float(result["wall_seconds"]), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("result wall time mismatches registry")
    if result.get("fingerprints") != {key: row[key] for key in FINGERPRINT_FIELDS}:
        raise ValueError("result fingerprints mismatch registry")
    if manifest.get("fingerprints") != result.get("fingerprints"):
        raise ValueError("manifest fingerprints mismatch result")
    directory = result_path.parent
    for name, field in (
        ("checkpoint.json", "checkpoint_sha256"),
        ("status_summary.json", "status_summary_sha256"),
        ("heartbeat.json", "heartbeat_sha256"),
    ):
        path = directory / name
        if not path.is_file() or manifest.get(field) != sha256_file(path):
            raise ValueError(f"terminal artifact mismatch: {name}")
    return result


def _derive_science(science: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    budget = float(science["budget"])
    ratio = max(0.0, float(science["R_min_opt"]) - float(science["R_min_feas"])) / budget
    tolerance = float(science["objective_tolerance"])
    optimum = float(science["complete_extensive_objective"])
    for endpoint in ("minimum", "maximum"):
        if science[f"{endpoint}_endpoint_status"] != "optimal":
            raise ValueError("reserve-face endpoint is not optimal")
        if abs(float(science[f"{endpoint}_endpoint_exact_objective"]) - optimum) > tolerance + 1e-8:
            raise ValueError("reserve-face endpoint exceeds tolerance")
    counts = science["endpoint_failure_counts"]
    if any(int(value) for endpoint in counts.values() for value in endpoint.values()):
        raise ValueError("endpoint exact recourse is incomplete")
    policies = science["fixed_reserve_policies"]
    if [float(item["rho"]) for item in policies] != [0.0, 0.1, 0.3, 0.5]:
        raise ValueError("fixed reserve policies are incomplete")
    if any(item["status"] != "optimal" or item["regular_purchase_reoptimized"] is not True for item in policies):
        raise ValueError("fixed reserve policy evidence is incomplete")
    floor = float(science["R_min_feas"])
    for item in policies:
        expected_reserve = floor + float(item["rho"]) * (budget - floor)
        if not math.isclose(
            float(item["reserve"]), expected_reserve, rel_tol=0.0, abs_tol=1.0e-8
        ):
            raise ValueError("fixed autonomous reserve formula is inconsistent")
        if not re.fullmatch(r"[0-9a-f]{64}", str(item["regular_purchase_sha256"])):
            raise ValueError("fixed reserve procurement decision hash is invalid")
    moderate_interval = config["reserve_identification"]["moderate_autonomous_reserve_ratio_interval"]
    cross = science.get("cross_item_allocation") or {}
    if cross.get("plan_source") != "complete_extensive_model_R_min_opt_endpoint":
        raise ValueError("cross-item allocation uses the wrong first-stage plan")
    if int(cross.get("scenario_count", -1)) != 50:
        raise ValueError("cross-item allocation must use all 50 training scenarios")
    spend = cross.get("scenario_item_emergency_spend") or {}
    if len(spend) != 50:
        raise ValueError("cross-item scenario spending evidence is incomplete")
    positive_tolerance = 1.0e-7
    item_names = ("relief_food_1", "relief_food_2")
    item_positive = {item: False for item in item_names}
    shares = []
    for values in spend.values():
        total = sum(float(values[item]) for item in item_names)
        if not math.isclose(float(values["total"]), total, rel_tol=0.0, abs_tol=1.0e-8):
            raise ValueError("cross-item scenario total spending is inconsistent")
        for item in item_names:
            item_positive[item] = item_positive[item] or float(values[item]) > positive_tolerance
        if total > positive_tolerance:
            shares.append(float(values[item_names[0]]) / total)
    share_range = max(shares) - min(shares) if len(shares) >= 2 else 0.0
    cross_gate = (
        len(shares) >= 2
        and all(item_positive.values())
        and share_range >= 1.0e-4
    )
    c0 = science.get("c0_equivalence") or {}
    c0_passed = False
    if science.get("profile_id") == "C0":
        endpoint_interval = c0.get("reserve_interval_endpoint_differences") or {}
        c0_passed = bool(
            c0.get("required") is True
            and c0.get("fulfillment_exactly_one") is True
            and int(c0.get("scenario_count_each_direction", -1)) == 50
            and float(c0.get("robust_objective_difference", math.inf)) <= tolerance + 1e-8
            and float(endpoint_interval.get("minimum", math.inf)) <= tolerance + 1e-8
            and float(endpoint_interval.get("maximum", math.inf)) <= tolerance + 1e-8
            and float(c0.get("M2C0_plan_evaluated_in_no_disruption_max_scenario_cost_difference", math.inf)) <= tolerance + 1e-8
            and float(c0.get("no_disruption_plan_evaluated_in_M2C0_max_scenario_cost_difference", math.inf)) <= tolerance + 1e-8
        )
        if not c0_passed:
            raise ValueError("C0 full no-disruption equivalence is incomplete")
    return {
        "ratio": ratio,
        "numerical": ratio > float(config["reserve_identification"]["numerical_activation_ratio_strictly_greater_than"]),
        "substantive": ratio >= float(config["reserve_identification"]["substantive_activation_ratio_greater_than_or_equal_to"]),
        "moderate": float(moderate_interval[0]) <= ratio <= float(moderate_interval[1]),
        "components": dict(science["scenario_component_set_sha256"]),
        "cross_item_gate": cross_gate,
        "cross_item_positive_scenario_count": len(shares),
        "cross_item_share_range": share_range,
        "c0_equivalence_passed": c0_passed,
    }


def update_projection(
    *, output_root: Path, config: Mapping[str, Any], fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    base = output_root / "confirmation"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [row for row in _read_registry(base / "confirmation_run_registry.csv")
                if all(row.get(key) == value for key, value in fingerprints.items())]
        verified: dict[tuple[int, float, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        invalid, invalid_diagnostics, diagnostics, duplicates = [], [], [], []
        failed_primary_run_ids: list[str] = []
        for row in rows:
            try:
                result = _validate_artifact(row)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"])
                    continue
                case = result["case"]
                identity = (int(case["seed"]), float(case["beta"]), str(case["profile_id"]))
                if identity in verified:
                    duplicates.append(result["case_id"])
                    continue
                if result["status"] == "optimal":
                    verified[identity] = (result, _derive_science(result["science"], config))
                else:
                    failed_primary_run_ids.append(row["run_id"])
            except Exception:
                (invalid_diagnostics if row.get("parent_run_id") else invalid).append(row["run_id"])

        combinations, by_beta_profile = [], {}
        seeds = (2026081301, 2026081302, 2026081303, 2026081304, 2026081305)
        for beta in (1.1, 1.3):
            for profile in ("C0", "C1", "T03"):
                entries = [verified.get((seed, beta, profile)) for seed in seeds]
                derived = [entry[1] for entry in entries if entry]
                complete = len(derived) == 5
                substantive = sum(item["substantive"] for item in derived)
                moderate = sum(item["moderate"] for item in derived)
                cross_item = sum(item["cross_item_gate"] for item in derived)
                item = {
                    "beta": beta, "profile_id": profile,
                    "completed_seed_count": len(derived),
                    "substantive_activation_seed_count": substantive,
                    "moderate_seed_count": moderate,
                    "cross_item_gate_seed_count": cross_item,
                    "C0_equivalence_seed_count": sum(item["c0_equivalence_passed"] for item in derived),
                    "run_ids": [entry[0]["run_id"] for entry in entries if entry],
                }
                combinations.append(item); by_beta_profile[(beta, profile)] = item

        beta_assessments = []
        for beta in (1.1, 1.3):
            crn_checks = []
            for seed in seeds:
                anchor_entry = verified.get((seed, beta, "C0"))
                anchor = anchor_entry[1]["components"] if anchor_entry else {}
                for profile in ("C1", "T03"):
                    entry = verified.get((seed, beta, profile))
                    fields = (
                        "latent_draw_sha256", "demand_sha256",
                        "emergency_price_sha256", "emergency_supply_sha256",
                        "scenario_order_sha256",
                    )
                    match = bool(entry) and all(entry[1]["components"][field] == anchor[field] for field in fields)
                    crn_checks.append({"seed": seed, "profile_id": profile, "verified": match})
            crn_verified = all(item["verified"] for item in crn_checks)
            c0, c1, t03 = (by_beta_profile[(beta, profile)] for profile in ("C0", "C1", "T03"))
            complete_beta = all(item["completed_seed_count"] == 5 for item in (c0, c1, t03))
            passed = bool(
                complete_beta and crn_verified
                and c0["substantive_activation_seed_count"] == 0
                and c0["C0_equivalence_seed_count"] == 5
                and t03["substantive_activation_seed_count"] >= 3
                and t03["moderate_seed_count"] >= 3
                and t03["substantive_activation_seed_count"] > c1["substantive_activation_seed_count"]
                and t03["cross_item_gate_seed_count"] >= 3
            )
            beta_assessments.append({
                "beta": beta,
                "status": "passed" if passed else "failed",
                "common_random_number_checks": crn_checks,
                "common_random_numbers_verified": crn_verified,
                "C0_substantive_activation_seed_count": c0["substantive_activation_seed_count"],
                "C0_equivalence_seed_count": c0["C0_equivalence_seed_count"],
                "C1_substantive_activation_seed_count": c1["substantive_activation_seed_count"],
                "T03_substantive_activation_seed_count": t03["substantive_activation_seed_count"],
                "T03_moderate_seed_count": t03["moderate_seed_count"],
                "T03_cross_item_gate_seed_count": t03["cross_item_gate_seed_count"],
                "confirmation_gate_passed": passed,
            })

        finalization_failure_run_ids = sorted(
            path.parent.name
            for name in ("runner_exception.json", "registry_failure.json", "projection_failure.json")
            for path in (base / "runs").glob(f"*/{name}")
        ) if (base / "runs").is_dir() else []
        crn_verified = all(item["common_random_numbers_verified"] for item in beta_assessments)
        complete = (
            len(verified) == 30 and not invalid and not duplicates and not diagnostics
            and not invalid_diagnostics and not failed_primary_run_ids
            and not finalization_failure_run_ids and crn_verified
        )
        passing_betas = [item["beta"] for item in beta_assessments if item["confirmation_gate_passed"]]
        decision = (
            "incomplete_or_invalid" if not complete else
            "two_item_confirmation_not_established_and_stop" if not passing_betas else
            "permit_separate_formal_extension_design_PR_only"
        )
        scope = (
            "no_formal_design" if not passing_betas else
            "single_beta_only_budget_effect_claims_forbidden" if len(passing_betas) == 1 else
            "both_betas_budget_moderation_comparison_allowed"
        )
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints), "required_primary_run_count": 30,
            "verified_primary_run_count": len(verified), "invalid_primary_run_ids": sorted(invalid),
            "invalid_diagnostic_run_ids": sorted(invalid_diagnostics),
            "diagnostic_run_ids": sorted(diagnostics), "duplicate_case_ids": sorted(set(duplicates)),
            "failed_primary_run_ids": sorted(failed_primary_run_ids),
            "finalization_failure_run_ids": finalization_failure_run_ids,
            "combinations": combinations,
            "beta_assessments": beta_assessments,
            "common_random_numbers_verified": crn_verified,
            "passing_betas": passing_betas,
            "claim_scope": scope,
            "overall_decision": decision,
            "confirmation_gate_passed": complete and bool(passing_betas),
            "formal_extension_authorized": False, "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "confirmation_projection.json", payload)
        return payload


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (output_root / "confirmation/runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("run path escapes controlled root")
    return path


def _write_terminal_diagnostic(
    directory: Path, *, run_id: str, case_id: str, stage: str,
    status: str, error: BaseException,
) -> None:
    """Best-effort bounded evidence for failures outside the scientific solve."""
    failure = {
        "stage": stage, "status": status,
        "message": f"{type(error).__name__}: {error}"[:1000],
        "exception_type": type(error).__name__,
    }
    payload = {
        "run_id": run_id, "case_id": case_id, "status": status,
        "current_stage": stage, "completed_stage_count": 0,
        "failure": failure, "updated_at_utc": utc_now(),
    }
    for path, value in (
        (directory / "runner_exception.json", payload),
        (directory / "status_summary.json", payload),
        (directory / "heartbeat.json", payload),
    ):
        try:
            atomic_write_json(path, value)
        except Exception:
            pass


def _validate_diagnostic_parent(
    output_root: Path, *, case_id: str, parent_run_id: str,
) -> None:
    validate_run_id(parent_run_id)
    rows = _read_registry(output_root / "confirmation/confirmation_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1:
        raise ValueError("diagnostic parent_run_id must identify one existing run")
    parent = matches[0]
    if parent.get("parent_run_id", "").strip():
        raise ValueError("diagnostic parent must be a primary run")
    if parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must belong to the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must be a failed, timed-out, or interrupted run")


def run_case(
    *, root: Path, output_root: Path, matrix_path: Path, config: Mapping[str, Any],
    fingerprints: Mapping[str, str],
    locked_environment: Mapping[str, str], source: Mapping[str, Any], case: ConfirmationCase,
    run_id: str, parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_confirmation_science,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    if parent_run_id is not None:
        validate_run_id(parent_run_id)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("M2C2 confirmation run_id is immutable")
        started = perf_counter(); stages = []; failure = None; science = None; status = "running"
        sampler = PeakRSSSampler(); sampler.start()
        checkpoint = directory / "checkpoint.json"
        status_path, heartbeat = directory / "status_summary.json", directory / "heartbeat.json"
        def progress(stage: str, details: Mapping[str, Any]) -> None:
            stages.append({"stage": stage, **details, "updated_at_utc": utc_now()})
            atomic_write_json(checkpoint, {"run_id":run_id,"case":case.as_dict(),"status":"running","completed_stages":stages[:-1],"current_stage":stage,"updated_at_utc":utc_now()})
            compact = {"run_id": run_id, "case_id": case.case_id, "status": "running", "current_stage": stage, "completed_stage_count": max(0, len(stages)-1), "failure": None}
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
        try:
            matrix = load_phase6_matrix(matrix_path)
            science = science_executor(project_root=root, matrix=matrix, matrix_path=matrix_path, config=config, case=case, progress=progress)
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"; failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": "KeyboardInterrupt", "exception_type": "KeyboardInterrupt"}
        except Exception as exc:
            status = "timeout" if isinstance(exc, TimeoutError) or "time_limit" in str(exc) else "stage_failure"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": f"{type(exc).__name__}: {exc}"[:1000], "exception_type": type(exc).__name__}
        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(solver_preference=("gurobi",), project_root=root, solver_threads=1)
            result = {"run_id": run_id, "parent_run_id": parent_run_id, "case_id": case.case_id, "case": case.as_dict(), "status": status, "finalized": True, "science": science, "stages": stages, "failure": failure, "wall_seconds": wall, "peak_memory_mb": peak, "fingerprints": dict(fingerprints), "git_sha": source["commit_sha"], "git_tree_sha": source["tree_sha"], "finished_at_utc": utc_now()}
            result_path, manifest_path = directory / "result.json", directory / "manifest.json"
            compact = {"run_id": run_id, "case_id": case.case_id, "status": status, "current_stage": failure.get("stage") if failure else None, "completed_stage_count": len(stages), "failure": compact_failure(failure), "updated_at_utc": utc_now()}
            finalization_stage = "artifact_finalization"
            atomic_write_json(checkpoint, {"run_id":run_id,"case":case.as_dict(),"status":status,"completed_stages":stages,"failure":compact_failure(failure),"updated_at_utc":utc_now()})
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {"artifact_state": "finalized", "run_id": run_id, "case_id": case.case_id, "result_sha256": sha256_file(result_path), "checkpoint_sha256":sha256_file(checkpoint), "status_summary_sha256": sha256_file(status_path), "heartbeat_sha256": sha256_file(heartbeat), "fingerprints": dict(fingerprints), "source": dict(source), "locked_environment": dict(locked_environment), "runtime_context": runtime})
            row = {"run_id": run_id, "parent_run_id": parent_run_id or "", "case_id": case.case_id, "tier_id": case.tier_id, "seed": case.seed, "beta": case.beta, "profile_id": case.profile_id, "status": status, "wall_seconds": wall, "peak_memory_mb": peak, **dict(fingerprints), "result_path": str(result_path.resolve()), "manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256_file(manifest_path), "failure_stage": failure.get("stage") if failure else "", "updated_at_utc": result["finished_at_utc"]}
            finalization_stage = "registry_finalization"
            _write_registry(output_root, row)
            finalization_stage = "projection_finalization"
            projection = update_projection(output_root=output_root, config=config, fingerprints=fingerprints)
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="interrupted", error=exc)
            raise
        except Exception as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="runner_exception", error=exc)
            raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "projection": projection}


def run_matrix(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_confirmation_science,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_preflight(root=root, config_path=config_path, runner_path=runner_path, approval_path=approval_path, authorize=authorize)
    cases = build_confirmation_cases(preflight["config"])
    all_case_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary execution must run the complete frozen 30-case matrix")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("diagnostic execution requires exactly one case_id and parent_run_id")
    requested = set(case_ids or all_case_ids)
    if requested - all_case_ids:
        raise ValueError("unknown M2C2 confirmation case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OUTPUT_ROOT; results = []
    with exclusive_file_lock(output_root / "confirmation/.serial-execution.lock", timeout_seconds=1.0):
        existing = output_root / "confirmation"
        if parent_run_id is None and existing.exists() and any(path.name != ".serial-execution.lock" for path in existing.iterdir()):
            raise RuntimeError("primary M2C2 matrix requires an empty controlled output root")
        if parent_run_id is not None:
            _validate_diagnostic_parent(output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id)
        for case in selected:
            result = run_case(root=root, output_root=output_root, matrix_path=root / "configs/phase6_experiment_matrix.yaml", config=preflight["config"], fingerprints=preflight["fingerprints"], locked_environment=preflight["locked_environment"], source=preflight["source"], case=case, run_id=f"{run_id_prefix}_{case.case_id}", parent_run_id=parent_run_id, science_executor=science_executor)
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

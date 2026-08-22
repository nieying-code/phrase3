"""Safe, non-authorized runner for the frozen M2.1 endpoint-selection pilot."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import yaml

from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_families import aggregate_oos_evaluation, generate_oos_data
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes, sha256_lf_text_file
from .phase6_locking import exclusive_file_lock
from .phase6_m1 import objective_tolerance, solve_minimum_feasible_reserve, solve_reserve_face_point
from .phase6_m2 import (
    M2_E3_COMPONENT_FILES,
    M2_FAMILY_COMPONENT_FILES,
    m2_model_context,
    reconstruct_frozen_demand_latent,
    resolve_supply_disruption_profile,
    solve_m2_endogenous_extensive,
    solve_m2_fixed_reserve,
)
from .phase6_m2_1_endpoint_selection import (
    CANDIDATE_IDS,
    PLAN_IDENTITY_FIELDS,
    SCENARIO_IDENTITY_FIELDS,
    TEST_STRATEGIES,
    build_seed_triplets,
    load_m2_1_config,
    reserve_candidates,
    select_validation_candidate,
    validate_minimum_endpoint_control_binding,
    validate_selected_minimum_test_difference,
    validate_shared_scenario_identity,
)
from .phase6_m2_development import (
    DevelopmentStageError,
    PeakRSSSampler,
    _decision_sha256,
    _failure_counts,
    _native_failure_status,
    _require_optimal,
    compact_failure,
    validate_run_id,
)
from .phase6_m2_formal_extension import (
    _confirmation_component_hashes,
    _confirmation_config,
    _plan_payload,
    _science_config_for_formal,
    _validate_formal_baseline_before_generation,
    _write_plan_artifacts,
)
from .phase6_m2_formal_oos import _evaluate_plan_with_wall_limit
from .phase6_m2c2_confirmation import apply_m2c2_supply_disruption
from .phase6_protocol import generate_phase6_data, load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_1_endpoint_selection_pilot_v1_0"
RUNNER_NAMESPACE = "phase6_m2_1_endpoint_selection_pilot_v1_0"
OUTPUT_ROOT = "outputs/phase6_m2_1_endpoint_selection_pilot_v1_0"
READY_STATUS = "frozen_for_pilot_execution"
PILOT_CONFIG_PATH = "configs/phase6_m2_1_pilot.yaml"
RUNNER_CONFIG_PATH = "configs/phase6_m2_1_pilot_runner.yaml"
APPROVAL_PATH = "configs/phase6_m2_1_pilot_approval.yaml"
DESIGN_CONFIG_PATH = "configs/phase6_m2_1_endpoint_selection.yaml"
FORMAL_BASE_CONFIG_PATH = "configs/phase6_m2_formal_extension.yaml"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256", "e3_component_sha256", "family_component_sha256",
    "runner_config_sha256", "environment_sha256",
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "run_kind", "triplet_position",
    "training_seed", "validation_seed", "test_seed", "status", "wall_seconds",
    "peak_memory_mb", *FINGERPRINT_FIELDS, "result_path", "manifest_path",
    "manifest_sha256", "failure_stage", "updated_at_utc",
)
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2_1_endpoint_selection.py",
    "src/phase6_m2_1_pilot.py",
    "src/run_phase6_m2_1_pilot.py",
    "src/phase6_m2_1_pilot_status.py",
    PILOT_CONFIG_PATH,
    RUNNER_CONFIG_PATH,
    DESIGN_CONFIG_PATH,
    FORMAL_BASE_CONFIG_PATH,
    "configs/phase6_m2_two_item_confirmation.yaml",
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


@dataclass(frozen=True)
class M21PilotCase:
    case_id: str
    run_kind: str
    triplet_position: int
    training_seed: int
    validation_seed: int
    test_seed: int
    includes_test_probe: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_payload(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def load_pilot_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("unsupported M2.1 pilot protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE or payload.get("output_root") != OUTPUT_ROOT:
        raise ValueError("M2.1 pilot namespace mismatch")
    parent = payload.get("frozen_design") or {}
    if parent != {
        "path": DESIGN_CONFIG_PATH,
        "sha256": "75668fa7a4759d02f4325113aa5abd9ffaa0e1031ea435ef43fc130297700e5c",
        "protocol_id": "phase6_m2_1_endpoint_selection_design_v1_0",
        "pr62_merge_commit": "770c863d69ba37ba858b00931310f94a9fb84e77",
        "pr62_merge_tree": "043de6a433376928e9544c6e2d7784811a37a7d2",
        "audit_path": "docs/handoffs/2026-08-21_phase6_m2_1_endpoint_selection_design_v1_0_audit.json",
        "audit_sha256": "724f6aad499fb4d39a27a17b9b5f300410c809a4c3aa3dc03494468ac2d31a9d",
    }:
        raise ValueError("M2.1 frozen PR #62 design identity changed")
    base = payload.get("scientific_base") or {}
    expected_base = {
        "formal_extension_config": FORMAL_BASE_CONFIG_PATH,
        "formal_extension_config_sha256": "e3eb0ae4c79e9e0859ecc33e4707aecc7ce1a7a1aed3166453f8af2ed2db6792",
        "confirmation_config": "configs/phase6_m2_two_item_confirmation.yaml",
        "confirmation_config_sha256": "d6e28d2171aceacd750a74bcc58a01c3c7383ffdab7ce7fca53e7451fe5f39a5",
        "model": "unchanged_M2_supply_disruption", "tier_id": "M2F2",
        "beta": 1.1, "profile_id": "T03", "training_scenario_count": 100,
        "validation_scenario_count": 2000, "test_scenario_count": 2000,
    }
    if base != expected_base:
        raise ValueError("M2.1 frozen scientific base changed")
    matrix = payload.get("pilot_matrix") or {}
    expected = {
        "training_seeds": [2026090401, 2026090402, 2026090403],
        "validation_seeds": [2026090501, 2026090502, 2026090503],
        "test_seeds": [2026090701, 2026090702, 2026090703],
        "candidate_ids": list(CANDIDATE_IDS),
        "test_strategy_ids": list(TEST_STRATEGIES),
    }
    for field, values in expected.items():
        if matrix.get(field) != values:
            raise ValueError(f"M2.1 pilot matrix changed: {field}")
    if (
        matrix.get("triplet_count") != 3
        or matrix.get("validation_candidate_plan_count") != 9
        or matrix.get("validation_exact_recourse_evaluation_count") != 18000
        or matrix.get("test_probe_plan_count") != 6
        or matrix.get("test_probe_exact_recourse_evaluation_count") != 12000
        or matrix.get("primary_run_count") != 3
        or matrix.get("one_time_test_probe_triplet_position") != 1
    ):
        raise ValueError("M2.1 pilot count identity changed")
    gates = payload.get("identity_gates") or {}
    if (
        gates.get("validation_scenario_generated_once_per_triplet") is not True
        or gates.get("test_scenario_generated_once_for_probe_triplet") is not True
        or tuple(gates.get("required_scenario_identity_fields", ())) != SCENARIO_IDENTITY_FIELDS
        or tuple(gates.get("finalized_plan_identity_fields", ())) != PLAN_IDENTITY_FIELDS
        or gates.get("minimum_endpoint_is_M2_control_artifact") is not True
        or gates.get("selected_minimum_reuses_M2_control_artifact") is not True
        or gates.get("selected_minimum_test_difference_zero_within_frozen_tolerance") is not True
    ):
        raise ValueError("M2.1 pilot identity gate changed")
    if payload.get("execution_boundaries", {}).get("runner_implemented") is not True:
        raise ValueError("M2.1 pilot runner is not implemented")
    if any(payload.get("execution_boundaries", {}).get(field) is not False for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
        "formal_extension_authorized",
    )):
        raise ValueError("M2.1 formal execution must remain unauthorized")
    boundaries = payload.get("execution_boundaries") or {}
    if any(int(boundaries.get(field, -1)) != 0 for field in (
        "scenario_generation_count", "gurobi_call_count", "pilot_run_count",
        "formal_run_count", "algorithm_performance_runs", "M0_E3_runs",
    )):
        raise ValueError("M2.1 runner revision must contain zero scientific execution")
    if payload.get("compute_gate") != {
        "projection_method": "maximum_observed_triplet_wall_seconds_times_ten",
        "projected_formal_wall_hours_maximum": 72.0,
        "all_three_triplets_optimal_required": True,
        "all_validation_and_probe_recourse_optimal_required": True,
        "common_random_numbers_required": True,
        "activation_or_selection_outcome_may_not_change_formal_design": True,
    }:
        raise ValueError("M2.1 pilot compute gate changed")
    return payload


def build_pilot_cases(pilot: Mapping[str, Any], design: Mapping[str, Any]) -> tuple[M21PilotCase, ...]:
    triplets = build_seed_triplets(design, "pilot")
    probe_position = int(pilot["pilot_matrix"]["one_time_test_probe_triplet_position"])
    cases = tuple(M21PilotCase(
        case_id=(
            f"M2_1_triplet{row.position:02d}_train{row.training_seed}_"
            f"validation{row.validation_seed}_test{row.test_seed}"
        ),
        run_kind="pilot_triplet", triplet_position=row.position,
        training_seed=row.training_seed, validation_seed=row.validation_seed,
        test_seed=row.test_seed, includes_test_probe=row.position == probe_position,
    ) for row in triplets)
    if len(cases) != 3 or sum(case.includes_test_probe for case in cases) != 1:
        raise ValueError("M2.1 pilot triplet construction failed")
    return cases


def pilot_fingerprints(root: Path, pilot_path: Path, runner_path: Path) -> dict[str, str]:
    pilot = load_pilot_config(pilot_path)
    design = load_m2_1_config(root / DESIGN_CONFIG_PATH)
    scientific = {
        "pilot": {key: value for key, value in pilot.items() if key not in LIFECYCLE_FIELDS},
        "design": {key: value for key, value in design.items() if key not in LIFECYCLE_FIELDS},
    }
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": _sha256_payload(scientific),
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def _scenario_identity(generated: Any) -> dict[str, str]:
    components = _confirmation_component_hashes(generated)
    return {
        "scenario_set_sha256": str(generated.joint_scenario_set_sha256),
        "scenario_order_sha256": str(components["scenario_order_sha256"]),
        "latent_draw_sha256": str(components["latent_draw_sha256"]),
        "demand_sha256": str(components["demand_sha256"]),
        "emergency_price_sha256": str(components["emergency_price_sha256"]),
        "emergency_supply_sha256": str(components["emergency_supply_sha256"]),
        "fulfillment_sha256": str(components["fulfillment_sha256"]),
    }


def _generate_data(
    *, root: Path, matrix: Mapping[str, Any], matrix_path: Path,
    formal: Mapping[str, Any], seed: int, scenario_count: int, phase: str,
) -> tuple[Any, float]:
    confirmation = _confirmation_config(root)
    frozen_matrix, _, budget, expected_capacity = _validate_formal_baseline_before_generation(
        matrix, formal, confirmation, beta=1.1, scenario_count=scenario_count,
    )
    if phase == "training":
        base = generate_phase6_data(
            frozen_matrix, matrix_path=matrix_path, tier_id="M2F2", seed=seed, budget=budget,
        )
    else:
        base = generate_oos_data(
            frozen_matrix, matrix_path=matrix_path, tier_id="M2F2", test_seed=seed, budget=budget,
        )
    if any(not math.isclose(a, b, abs_tol=1.0e-9) for a, b in zip(
        base.data.storage_capacity, expected_capacity, strict=True,
    )):
        raise ValueError("generated M2.1 storage capacity mismatch")
    latent = reconstruct_frozen_demand_latent(frozen_matrix, base)
    generated = apply_m2c2_supply_disruption(
        base,
        profile=resolve_supply_disruption_profile(_science_config_for_formal(root, formal), "T03"),
        demand_latent=latent,
        item_vulnerability_multiplier={"relief_food_1": 0.8, "relief_food_2": 1.2},
    )
    return generated, budget


def _require_complete_metrics(metrics: Mapping[str, Any], scenario_count: int, stage: str) -> None:
    if (
        metrics.get("plan_oos_status") != "complete_feasible"
        or int(metrics.get("optimal_scenario_count", -1)) != scenario_count
        or int(metrics.get("infeasible_scenario_count", -1)) != 0
        or int(metrics.get("solver_failure_count", -1)) != 0
    ):
        raise DevelopmentStageError(stage, "unexpected_infeasible_recourse", f"{stage} incomplete")
    for field in ("mean_total_cost", "total_cost_cvar95", "service_level"):
        if not math.isfinite(float(metrics.get(field, math.nan))):
            raise ValueError(f"{stage} metric is missing: {field}")


def _evaluate_plan(
    *, generated: Any, plan: Mapping[str, Any], seconds: float,
    wall_seconds: float, stage: str,
) -> dict[str, Any]:
    with m2_model_context():
        evaluation = _evaluate_plan_with_wall_limit(
            generated.data, plan["regular_purchase"], float(plan["reserve_amount"]),
            solver_call_seconds=seconds, plan_wall_seconds=wall_seconds,
        )
    metrics = aggregate_oos_evaluation(
        generated.data, evaluation, reserve=float(plan["reserve_amount"]),
    )
    _require_complete_metrics(metrics, len(generated.data.scenarios), stage)
    return metrics


class _TrainingDeadline:
    """Hard wall-clock budget shared by all training stages in one triplet."""

    def __init__(self, *, wall_seconds: float, solver_call_seconds: float) -> None:
        if not math.isfinite(wall_seconds) or wall_seconds <= 0:
            raise ValueError("training_triplet_wall_seconds must be finite and positive")
        if not math.isfinite(solver_call_seconds) or solver_call_seconds <= 0:
            raise ValueError("solver_call_seconds must be finite and positive")
        self.deadline = perf_counter() + wall_seconds
        self.solver_call_seconds = solver_call_seconds

    def check(self, stage: str) -> None:
        if self.deadline - perf_counter() <= 0:
            raise TimeoutError(f"training_triplet_wall_seconds exceeded before {stage}")

    def solver_seconds(self, stage: str) -> float:
        remaining = self.deadline - perf_counter()
        if remaining <= 0:
            raise TimeoutError(f"training_triplet_wall_seconds exceeded before {stage}")
        return min(self.solver_call_seconds, remaining)


def _evaluate_test_strategies(
    *, generated: Any, strategy_plan: Mapping[str, Mapping[str, Any]],
    seconds: float, wall_seconds: float, progress: Callable[[str, Mapping[str, Any]], None],
    test_identity: Mapping[str, str], selected_id: str,
) -> dict[str, dict[str, Any]]:
    """Evaluate all six logical strategies independently, even for one shared plan."""

    results: dict[str, dict[str, Any]] = {}
    for strategy_id in TEST_STRATEGIES:
        plan = strategy_plan[strategy_id]
        progress(f"test_{strategy_id}", {})
        metrics = _evaluate_plan(
            generated=generated, plan=plan, seconds=seconds,
            wall_seconds=wall_seconds, stage=f"test_{strategy_id}",
        )
        results[strategy_id] = {
            "strategy_id": strategy_id,
            "source_candidate_id": (
                "minimum_endpoint" if strategy_id == "M2_minimum_endpoint"
                else selected_id if strategy_id == "M2_1_validation_selected_endpoint"
                else strategy_id
            ),
            "reserve": float(plan["reserve_amount"]),
            "regular_purchase_sha256": plan["regular_purchase_sha256"],
            "exact_training_objective": plan["exact_training_objective"],
            "metrics": metrics,
            **test_identity,
        }
    return results


def execute_triplet_science(**kwargs: Any) -> dict[str, Any]:
    """Run one indivisible training-validation-test pilot triplet."""

    root: Path = kwargs["project_root"]
    matrix = kwargs["matrix"]
    matrix_path: Path = kwargs["matrix_path"]
    pilot = kwargs["pilot_config"]
    runner = kwargs["runner_config"]
    case: M21PilotCase = kwargs["case"]
    progress = kwargs["progress"]
    formal = yaml.safe_load((root / FORMAL_BASE_CONFIG_PATH).read_text(encoding="utf-8"))
    seconds = float(runner["limits"]["solver_call_seconds"])
    plan_wall = float(runner["limits"]["validation_candidate_wall_seconds"])
    absolute, relative = 1.0e-5, 1.0e-7
    training_deadline = _TrainingDeadline(
        wall_seconds=float(runner["limits"]["training_triplet_wall_seconds"]),
        solver_call_seconds=seconds,
    )

    training_deadline.check("training_scenario_generation")
    progress("training_scenario_generation", {"seed": case.training_seed})
    training, budget = _generate_data(
        root=root, matrix=matrix, matrix_path=matrix_path, formal=formal,
        seed=case.training_seed, scenario_count=100, phase="training",
    )
    training_identity = _scenario_identity(training)
    data = training.data
    training_deadline.check("minimum_feasible_reserve")
    progress("minimum_feasible_reserve", {})
    floor = solve_minimum_feasible_reserve(
        data, solver_threads=1,
        time_limit_seconds=training_deadline.solver_seconds("minimum_feasible_reserve"),
    )
    _require_optimal("minimum_feasible_reserve", floor.status, f"floor failed: {floor.status}")
    progress("complete_extensive_optimum", {})
    optimum = solve_m2_endogenous_extensive(
        data, solver_threads=1,
        time_limit_seconds=training_deadline.solver_seconds("complete_extensive_optimum"),
        consistency_tolerance=absolute,
    )
    _require_optimal(
        "complete_extensive_optimum", _native_failure_status(optimum),
        f"complete optimum failed: {optimum.status}",
    )
    if optimum.objective is None or optimum.master.objective is None:
        raise RuntimeError("complete optimum returned no objective")
    tolerance = objective_tolerance(
        float(optimum.objective), absolute_tolerance=absolute, relative_tolerance=relative,
    )
    common = dict(
        data=data, master_optimum=float(optimum.master.objective),
        exact_optimum=float(optimum.objective), tolerance=tolerance,
        solver_preference=("gurobi",),
        solver_threads=1, feasibility_tolerance=1.0e-7, optimality_tolerance=1.0e-7,
    )
    progress("minimum_tolerance_optimal_reserve", {})
    with m2_model_context():
        minimum = solve_reserve_face_point(
            direction="min",
            time_limit_seconds=training_deadline.solver_seconds(
                "minimum_tolerance_optimal_reserve"
            ),
            **common,
        )
    _require_optimal(
        "minimum_tolerance_optimal_reserve", _native_failure_status(minimum),
        f"minimum endpoint failed: {minimum.status}",
    )
    progress("maximum_tolerance_optimal_reserve", {})
    with m2_model_context():
        maximum_face = solve_reserve_face_point(
            direction="max",
            time_limit_seconds=training_deadline.solver_seconds(
                "maximum_tolerance_optimal_reserve"
            ),
            **common,
        )
    _require_optimal(
        "maximum_tolerance_optimal_reserve", _native_failure_status(maximum_face),
        f"maximum endpoint failed: {maximum_face.status}",
    )
    endpoint_objectives = (float(minimum.exact_objective), float(maximum_face.exact_objective))
    if not all(math.isfinite(value) for value in endpoint_objectives) or any(
        abs(value - float(optimum.objective)) > tolerance + 1.0e-8
        for value in endpoint_objectives
    ):
        raise RuntimeError("M2.1 tolerance-optimal endpoint objective mismatch")
    endpoints = reserve_candidates(minimum.reserve, maximum_face.reserve)
    training_hash = training.joint_scenario_set_sha256
    plans: dict[str, dict[str, Any]] = {
        "minimum_endpoint": _plan_payload(
            strategy_id="minimum_endpoint", reserve=minimum.reserve,
            regular_purchase=minimum.regular_purchase,
            objective=minimum.exact_objective,
            joint_scenario_set_sha256=training_hash,
        )
    }
    candidate_training: dict[str, dict[str, Any]] = {
        "minimum_endpoint": {
            "reserve": float(minimum.reserve),
            "exact_training_objective": float(minimum.exact_objective),
            "regular_purchase_reoptimized": True,
        }
    }
    for candidate_id in ("interval_midpoint", "maximum_endpoint"):
        progress(f"reoptimize_{candidate_id}", {"reserve": endpoints[candidate_id]})
        solution = solve_m2_fixed_reserve(
            data, reserve_ratio=endpoints[candidate_id] / budget,
            solver_threads=1,
            time_limit_seconds=training_deadline.solver_seconds(
                f"reoptimize_{candidate_id}"
            ),
            consistency_tolerance=absolute,
        )
        _require_optimal(
            f"reoptimize_{candidate_id}", _native_failure_status(solution),
            f"{candidate_id} reoptimization failed: {solution.status}",
        )
        if not math.isclose(float(solution.reserve), endpoints[candidate_id], abs_tol=1.0e-8):
            raise RuntimeError(f"{candidate_id} fixed-reserve reoptimization changed reserve")
        if float(solution.objective) > float(optimum.objective) + tolerance + 1.0e-8:
            raise RuntimeError(f"{candidate_id} leaves the tolerance-optimal face")
        plans[candidate_id] = _plan_payload(
            strategy_id=candidate_id, reserve=solution.reserve,
            regular_purchase=solution.master.regular_purchase,
            objective=solution.objective,
            joint_scenario_set_sha256=training_hash,
        )
        candidate_training[candidate_id] = {
            "reserve": float(solution.reserve),
            "exact_training_objective": float(solution.objective),
            "regular_purchase_reoptimized": True,
        }

    fixed_names = {
        0.0: "zero_autonomous_reserve", 0.1: "fixed_autonomous_reserve_0_10",
        0.3: "fixed_autonomous_reserve_0_30", 0.5: "fixed_autonomous_reserve_0_50",
    }
    for rho, strategy in fixed_names.items():
        progress(f"train_{strategy}", {"rho": rho})
        reserve = float(floor.reserve) + rho * (budget - float(floor.reserve))
        solution = solve_m2_fixed_reserve(
            data, reserve_ratio=reserve / budget, solver_threads=1,
            time_limit_seconds=training_deadline.solver_seconds(f"train_{strategy}"),
            consistency_tolerance=absolute,
        )
        _require_optimal(
            f"train_{strategy}", _native_failure_status(solution),
            f"{strategy} failed: {solution.status}",
        )
        if not math.isclose(float(solution.reserve), reserve, abs_tol=1.0e-8):
            raise RuntimeError(f"{strategy} fixed autonomous reserve formula mismatch")
        plans[strategy] = _plan_payload(
            strategy_id=strategy, reserve=solution.reserve,
            regular_purchase=solution.master.regular_purchase,
            objective=solution.objective,
            joint_scenario_set_sha256=training_hash,
        )
    training_deadline.check("validation_scenario_generation")

    progress("validation_scenario_generation", {"seed": case.validation_seed})
    validation, validation_budget = _generate_data(
        root=root, matrix=matrix, matrix_path=matrix_path, formal=formal,
        seed=case.validation_seed, scenario_count=2000, phase="validation",
    )
    if not math.isclose(validation_budget, budget, abs_tol=1.0e-9):
        raise RuntimeError("validation budget differs from training budget")
    validation_identity = _scenario_identity(validation)
    validation_results: dict[str, dict[str, Any]] = {}
    for candidate_id in CANDIDATE_IDS:
        progress(f"validate_{candidate_id}", {})
        metrics = _evaluate_plan(
            generated=validation, plan=plans[candidate_id], seconds=seconds,
            wall_seconds=plan_wall, stage=f"validate_{candidate_id}",
        )
        validation_results[candidate_id] = {
            "candidate_id": candidate_id,
            "reserve": float(plans[candidate_id]["reserve_amount"]),
            "regular_purchase_sha256": plans[candidate_id]["regular_purchase_sha256"],
            "exact_training_objective": plans[candidate_id]["exact_training_objective"],
            "metrics": metrics,
            **validation_identity,
        }
    validate_shared_scenario_identity(
        validation_results, expected_ids=CANDIDATE_IDS, phase="validation",
    )
    selection = select_validation_candidate({
        candidate_id: {
            "total_cost_cvar95": row["metrics"]["total_cost_cvar95"],
            "mean_total_cost": row["metrics"]["mean_total_cost"],
            "reserve": row["reserve"],
        }
        for candidate_id, row in validation_results.items()
    })
    selected_id = selection["selected_candidate_id"]

    test_results: dict[str, dict[str, Any]] = {}
    test_identity: dict[str, str] | None = None
    if case.includes_test_probe:
        progress("test_scenario_generation", {"seed": case.test_seed})
        test, test_budget = _generate_data(
            root=root, matrix=matrix, matrix_path=matrix_path, formal=formal,
            seed=case.test_seed, scenario_count=2000, phase="test",
        )
        if not math.isclose(test_budget, budget, abs_tol=1.0e-9):
            raise RuntimeError("test budget differs from training budget")
        test_identity = _scenario_identity(test)
        strategy_plan = {
            "M2_minimum_endpoint": plans["minimum_endpoint"],
            "M2_1_validation_selected_endpoint": plans[selected_id],
            "zero_autonomous_reserve": plans["zero_autonomous_reserve"],
            "fixed_autonomous_reserve_0_10": plans["fixed_autonomous_reserve_0_10"],
            "fixed_autonomous_reserve_0_30": plans["fixed_autonomous_reserve_0_30"],
            "fixed_autonomous_reserve_0_50": plans["fixed_autonomous_reserve_0_50"],
        }
        test_results = _evaluate_test_strategies(
            generated=test, strategy_plan=strategy_plan, seconds=seconds,
            wall_seconds=float(runner["limits"]["test_plan_wall_seconds"]),
            progress=progress, test_identity=test_identity, selected_id=selected_id,
        )
        validate_shared_scenario_identity(
            test_results, expected_ids=TEST_STRATEGIES, phase="test",
        )
        paired = (
            float(test_results["M2_1_validation_selected_endpoint"]["metrics"]["total_cost_cvar95"])
            - float(test_results["M2_minimum_endpoint"]["metrics"]["total_cost_cvar95"])
        )
        validate_selected_minimum_test_difference(
            selected_candidate_id=selected_id, paired_difference=paired,
            tolerance=absolute + relative * max(
                1.0, abs(float(test_results["M2_minimum_endpoint"]["metrics"]["total_cost_cvar95"])),
            ),
        )

    endpoint_counts = {
        "minimum": _failure_counts(minimum.evaluation),
        "maximum": _failure_counts(maximum_face.evaluation),
    }
    if any(sum(row.values()) for row in endpoint_counts.values()):
        raise RuntimeError("M2.1 endpoint exact recourse evaluation is incomplete")
    science = {
        "tier_id": "M2F2", "beta": 1.1, "profile_id": "T03",
        "training_seed": case.training_seed, "validation_seed": case.validation_seed,
        "test_seed": case.test_seed, "includes_test_probe": case.includes_test_probe,
        "budget": budget, "training_scenario_count": 100,
        "validation_scenario_count": 2000,
        "test_scenario_count": 2000 if case.includes_test_probe else 0,
        "training_scenario_identity": training_identity,
        "R_min_feas": float(floor.reserve), "R_min_opt": float(minimum.reserve),
        "R_max_opt": float(maximum_face.reserve),
        "complete_extensive_objective": float(optimum.objective),
        "objective_tolerance": tolerance, "endpoint_failure_counts": endpoint_counts,
        "candidate_training": candidate_training,
        "validation_results": validation_results,
        "validation_selection": selection,
        "validation_scenario_identity": validation_identity,
        "test_results": test_results,
        "test_scenario_identity": test_identity,
        "minimum_endpoint_control_candidate_id": "minimum_endpoint",
        "minimum_endpoint_generated_once": True,
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
        "_plan_payloads": plans,
    }
    return science


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (output_root / "pilot/runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("M2.1 run path escapes controlled output root")
    return path


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = output_root / "pilot"
    path = base / "pilot_run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("M2.1 pilot run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _controlled_artifact_paths(output_root: Path, row: Mapping[str, str]) -> tuple[Path, Path]:
    run_id = str(row["run_id"]); validate_run_id(run_id)
    directory = (output_root / "pilot/runs" / run_id).resolve()
    result = Path(row["result_path"]).resolve()
    manifest = Path(row["manifest_path"]).resolve()
    if result != directory / "result.json" or manifest != directory / "manifest.json":
        raise ValueError("M2.1 artifact path leaves controlled namespace")
    return result, manifest


def _validate_artifact(output_root: Path, row: Mapping[str, str]) -> dict[str, Any]:
    result_path, manifest_path = _controlled_artifact_paths(output_root, row)
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("M2.1 finalized artifact is missing")
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("M2.1 manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_state") != "finalized" or sha256_file(result_path) != manifest.get("result_sha256"):
        raise ValueError("M2.1 result is not finalized")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if (
        result.get("finalized") is not True
        or result.get("run_id") != row["run_id"]
        or result.get("case_id") != row["case_id"]
        or result.get("status") != row["status"]
    ):
        raise ValueError("M2.1 result identity mismatch")
    case = result.get("case") or {}
    expected = {
        "run_kind": row["run_kind"], "triplet_position": int(row["triplet_position"]),
        "training_seed": int(row["training_seed"]),
        "validation_seed": int(row["validation_seed"]), "test_seed": int(row["test_seed"]),
    }
    if any(case.get(field) != value for field, value in expected.items()):
        raise ValueError("M2.1 result case identity mismatch")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("M2.1 parent identity mismatch")
    expected_fingerprints = {field: row[field] for field in FINGERPRINT_FIELDS}
    if result.get("fingerprints") != expected_fingerprints or manifest.get("fingerprints") != expected_fingerprints:
        raise ValueError("M2.1 artifact fingerprints mismatch")
    wall = float(row["wall_seconds"])
    if not math.isfinite(wall) or not math.isclose(wall, float(result["wall_seconds"]), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("M2.1 wall time mismatch")
    for name, field in (
        ("checkpoint.json", "checkpoint_sha256"),
        ("status_summary.json", "status_summary_sha256"),
        ("heartbeat.json", "heartbeat_sha256"),
    ):
        path = result_path.parent / name
        if not path.is_file() or manifest.get(field) != sha256_file(path):
            raise ValueError(f"M2.1 terminal artifact mismatch: {name}")
    return result


def _validate_plan_artifact(
    *, output_root: Path, run_id: str, identity: Mapping[str, Any],
) -> dict[str, Any]:
    strategy = str(identity["strategy_id"]); validate_run_id(run_id)
    expected = (output_root / "pilot/runs" / run_id / "plans" / f"{strategy}.json").resolve()
    path = Path(identity["path"]).resolve()
    if path != expected or not path.is_file() or sha256_file(path) != identity["finalized_plan_artifact_sha256"]:
        raise ValueError("M2.1 plan artifact path or hash mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("artifact_state") != "finalized"
        or payload.get("source_run_id") != run_id
        or payload.get("strategy_id") != strategy
        or payload.get("regular_purchase_sha256") != identity.get("regular_purchase_sha256")
        or payload.get("training_joint_scenario_set_sha256") != identity.get("training_joint_scenario_set_sha256")
        or not math.isclose(float(payload.get("reserve_amount", math.nan)), float(identity.get("reserve_amount", math.nan)), abs_tol=1e-9)
        or not math.isclose(float(payload.get("exact_training_objective", math.nan)), float(identity.get("exact_training_objective", math.nan)), abs_tol=1e-8)
    ):
        raise ValueError("M2.1 plan identity mismatch")
    return payload


def _derive_triplet(science: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    if (
        science.get("tier_id") != "M2F2" or float(science.get("beta", math.nan)) != 1.1
        or science.get("profile_id") != "T03"
        or int(science.get("training_seed", -1)) != int(case["training_seed"])
        or int(science.get("validation_seed", -1)) != int(case["validation_seed"])
        or int(science.get("test_seed", -1)) != int(case["test_seed"])
        or bool(science.get("includes_test_probe")) != bool(case["includes_test_probe"])
        or int(science.get("training_scenario_count", -1)) != 100
        or int(science.get("validation_scenario_count", -1)) != 2000
        or not math.isclose(float(science.get("budget", math.nan)), 2571.372016574617, abs_tol=1.0e-9)
        or science.get("solver") != "gurobi_direct"
        or science.get("gurobi_optimizer_version") != "13.0.2"
        or science.get("gurobipy_version") != "13.0.2"
        or int(science.get("threads", -1)) != 1
    ):
        raise ValueError("M2.1 triplet scientific identity mismatch")
    training_identity = science.get("training_scenario_identity") or {}
    if tuple(training_identity) != SCENARIO_IDENTITY_FIELDS or any(
        not isinstance(training_identity.get(field), str)
        or len(training_identity[field]) != 64
        or any(char not in "0123456789abcdef" for char in training_identity[field])
        for field in SCENARIO_IDENTITY_FIELDS
    ):
        raise ValueError("M2.1 training scenario identity is incomplete")
    identities = science.get("first_stage_plan_artifacts") or {}
    required_plan_ids = (*CANDIDATE_IDS, "zero_autonomous_reserve", "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30", "fixed_autonomous_reserve_0_50")
    if tuple(identities) != required_plan_ids:
        raise ValueError("M2.1 finalized plan set mismatch")
    if any(
        identity.get("training_joint_scenario_set_sha256")
        != training_identity["scenario_set_sha256"]
        for identity in identities.values()
    ):
        raise ValueError("M2.1 plan training scenario identity mismatch")
    candidate_records = science.get("validation_results") or {}
    validation_identity = validate_shared_scenario_identity(
        candidate_records, expected_ids=CANDIDATE_IDS, phase="validation",
    )
    for candidate_id in CANDIDATE_IDS:
        row = candidate_records[candidate_id]
        plan = identities[candidate_id]
        _require_complete_metrics(row.get("metrics") or {}, 2000, f"validate_{candidate_id}")
        if (
            row.get("regular_purchase_sha256") != plan.get("regular_purchase_sha256")
            or not math.isclose(float(row.get("reserve", math.nan)), float(plan.get("reserve_amount", math.nan)), abs_tol=1e-9)
            or not math.isclose(float(row.get("exact_training_objective", math.nan)), float(plan.get("exact_training_objective", math.nan)), abs_tol=1e-8)
            or row.get("source_plan_identity")
            != {field: plan.get(field) for field in PLAN_IDENTITY_FIELDS}
        ):
            raise ValueError("M2.1 validation result is not bound to its plan")
    expected_selection = select_validation_candidate({
        candidate_id: {
            "total_cost_cvar95": candidate_records[candidate_id]["metrics"]["total_cost_cvar95"],
            "mean_total_cost": candidate_records[candidate_id]["metrics"]["mean_total_cost"],
            "reserve": candidate_records[candidate_id]["reserve"],
        }
        for candidate_id in CANDIDATE_IDS
    })
    if science.get("validation_selection") != expected_selection:
        raise ValueError("M2.1 validation selection was not independently reproduced")
    minimum = identities["minimum_endpoint"]
    saved_control = science.get("minimum_endpoint_M2_control_identity") or {}
    expected_control = {field: minimum.get(field) for field in PLAN_IDENTITY_FIELDS}
    if saved_control != expected_control:
        raise ValueError("minimum endpoint M2 control identity mismatch")
    validate_minimum_endpoint_control_binding(minimum, saved_control)
    test_results = science.get("test_results") or {}
    if case["includes_test_probe"]:
        test_identity = validate_shared_scenario_identity(
            test_results, expected_ids=TEST_STRATEGIES, phase="test",
        )
        selected_id = expected_selection["selected_candidate_id"]
        for strategy in TEST_STRATEGIES:
            _require_complete_metrics(test_results[strategy].get("metrics") or {}, 2000, f"test_{strategy}")
        strategy_sources = {
            "M2_minimum_endpoint": "minimum_endpoint",
            "M2_1_validation_selected_endpoint": expected_selection["selected_candidate_id"],
            "zero_autonomous_reserve": "zero_autonomous_reserve",
            "fixed_autonomous_reserve_0_10": "fixed_autonomous_reserve_0_10",
            "fixed_autonomous_reserve_0_30": "fixed_autonomous_reserve_0_30",
            "fixed_autonomous_reserve_0_50": "fixed_autonomous_reserve_0_50",
        }
        for strategy, source_id in strategy_sources.items():
            row = test_results[strategy]; plan = identities[source_id]
            if (
                row.get("source_candidate_id") != source_id
                or row.get("regular_purchase_sha256") != plan.get("regular_purchase_sha256")
                or not math.isclose(float(row.get("reserve", math.nan)), float(plan.get("reserve_amount", math.nan)), abs_tol=1e-9)
                or not math.isclose(float(row.get("exact_training_objective", math.nan)), float(plan.get("exact_training_objective", math.nan)), abs_tol=1e-8)
                or row.get("source_plan_identity")
                != {field: plan.get(field) for field in PLAN_IDENTITY_FIELDS}
            ):
                raise ValueError("M2.1 test result is not bound to its finalized source plan")
        if selected_id == "minimum_endpoint":
            control = test_results["M2_minimum_endpoint"]
            treatment = test_results["M2_1_validation_selected_endpoint"]
            if any(control.get(field) != treatment.get(field) for field in (
                "reserve", "regular_purchase_sha256", "exact_training_objective",
            )):
                raise ValueError("selected minimum test plan does not reuse M2 control")
            validate_selected_minimum_test_difference(
                selected_candidate_id=selected_id,
                paired_difference=float(treatment["metrics"]["total_cost_cvar95"]) - float(control["metrics"]["total_cost_cvar95"]),
                tolerance=1.0e-5 + 1.0e-7 * max(1.0, abs(float(control["metrics"]["total_cost_cvar95"]))),
            )
    else:
        if test_results or science.get("test_scenario_count") != 0:
            raise ValueError("non-probe triplet contains test evidence")
        test_identity = None
    return {
        "selected_candidate_id": expected_selection["selected_candidate_id"],
        "validation_scenario_identity": validation_identity,
        "test_scenario_identity": test_identity,
        "validation_plan_count": 3,
        "validation_recourse_evaluation_count": 6000,
        "test_plan_count": 6 if case["includes_test_probe"] else 0,
        "test_recourse_evaluation_count": 12000 if case["includes_test_probe"] else 0,
    }


def _finalization_failure_ids(base: Path) -> list[str]:
    runs = base / "runs"
    if not runs.is_dir():
        return []
    return sorted(path.parent.name for path in runs.glob("*/runner_exception.json"))


def update_projection(
    *, output_root: Path, pilot: Mapping[str, Any], design: Mapping[str, Any],
    fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    base = output_root / "pilot"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [
            row for row in _read_registry(base / "pilot_run_registry.csv")
            if all(row.get(field) == value for field, value in fingerprints.items())
        ]
        verified: dict[str, dict[str, Any]] = {}
        invalid: list[str] = []; diagnostics: list[str] = []
        failed: list[str] = []; duplicates: list[str] = []
        for row in rows:
            try:
                result = _validate_artifact(output_root, row)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"]); continue
                if result["case_id"] in verified:
                    duplicates.append(result["case_id"]); continue
                if result["status"] != "optimal":
                    failed.append(result["run_id"]); continue
                for identity in (result["science"].get("first_stage_plan_artifacts") or {}).values():
                    _validate_plan_artifact(output_root=output_root, run_id=result["run_id"], identity=identity)
                verified[result["case_id"]] = result
            except Exception:
                invalid.append(row.get("run_id", ""))
        cases = build_pilot_cases(pilot, design)
        derived: list[dict[str, Any] | None] = []
        for case in cases:
            result = verified.get(case.case_id)
            try:
                derived.append(_derive_triplet(result["science"], result["case"]) if result else None)
            except Exception:
                invalid.append(result.get("run_id", "") if result else "")
                derived.append(None)
        finalization_failures = _finalization_failure_ids(base)
        complete = bool(
            len(verified) == 3 and all(derived) and not invalid and not diagnostics
            and not failed and not duplicates and not finalization_failures
        )
        total_validation_plans = sum(row["validation_plan_count"] for row in derived if row)
        total_validation_evaluations = sum(row["validation_recourse_evaluation_count"] for row in derived if row)
        total_test_plans = sum(row["test_plan_count"] for row in derived if row)
        total_test_evaluations = sum(row["test_recourse_evaluation_count"] for row in derived if row)
        max_wall = max((float(result["wall_seconds"]) for result in verified.values()), default=math.inf)
        projected_hours = 10.0 * max_wall / 3600.0
        gate = pilot["compute_gate"]
        passed = bool(
            complete and total_validation_plans == 9 and total_validation_evaluations == 18000
            and total_test_plans == 6 and total_test_evaluations == 12000
            and projected_hours <= float(gate["projected_formal_wall_hours_maximum"])
        )
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints),
            "required_primary_run_count": 3,
            "verified_primary_run_count": sum(row is not None for row in derived),
            "validation_candidate_plan_count": total_validation_plans,
            "validation_exact_recourse_evaluation_count": total_validation_evaluations,
            "test_probe_plan_count": total_test_plans,
            "test_probe_exact_recourse_evaluation_count": total_test_evaluations,
            "invalid_primary_run_ids": sorted(set(invalid)),
            "diagnostic_run_ids": sorted(diagnostics),
            "failed_primary_run_ids": sorted(failed),
            "duplicate_case_ids": sorted(set(duplicates)),
            "finalization_failure_run_ids": finalization_failures,
            "selected_candidate_ids": [row["selected_candidate_id"] for row in derived if row],
            "projection_method": gate["projection_method"],
            "maximum_triplet_wall_seconds": max_wall,
            "projected_formal_wall_hours": projected_hours,
            "pilot_compute_gate_passed": passed,
            "formal_extension_authorized": False,
            "next_decision": "permit_separate_formal_freeze_PR_only" if passed else "pilot_incomplete_or_compute_gate_failed",
            "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "pilot_projection.json", payload)
        return payload


def validate_preflight(
    *, root: Path, pilot_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    pilot = load_pilot_config(pilot_path)
    design_path = root / DESIGN_CONFIG_PATH
    design = load_m2_1_config(design_path)
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    if pilot.get("status") != READY_STATUS:
        raise RuntimeError("M2.1 pilot protocol is not frozen for execution")
    if not authorize:
        raise PermissionError("--authorize-pilot-execution is required")
    if pilot.get("execution_boundaries", {}).get("pilot_authorized") is not True:
        raise PermissionError("M2.1 pilot protocol authorization is false")
    expected_approval = {
        "approval_id": "phase6_m2_1_endpoint_selection_pilot_execution_v1_0",
        "status": "approved_for_pilot_execution",
        "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": RUNNER_NAMESPACE,
        "explicit_cli_authorization_required": True,
        "pilot_authorized": True,
    }
    if any(approval.get(field) != value for field, value in expected_approval.items()):
        raise PermissionError("M2.1 pilot approval is not active")
    if any(approval.get(field) is not False for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
        "formal_extension_authorized", "accept_M2_authorization",
    )):
        raise RuntimeError("M2.1 approval illegally authorizes a later phase")
    expected_counts = {
        "pilot_primary_runs": 0, "validation_candidate_plans": 0,
        "validation_recourse_evaluations": 0, "test_probe_plans": 0,
        "test_probe_recourse_evaluations": 0, "scenario_generation_count": 0,
        "gurobi_call_count": 0, "formal_runs": 0,
        "algorithm_performance_runs": 0, "M0_E3_runs": 0,
    }
    if approval.get("execution_counts_in_this_revision") != expected_counts:
        raise RuntimeError("M2.1 approval execution-count boundary changed")
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("M2.1 runner identity mismatch")
    required_execution = {
        "strictly_serial": True,
        "empty_output_namespace_required_for_primary_batch": True,
        "explicit_cli_authorization_required": True,
        "immutable_run_ids": True,
        "full_three_triplet_primary_batch_required": True,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
        "failure_stops_batch": True,
        "existing_M2_outputs_are_read_only": True,
        "formal_execution_authorized": False,
    }
    if runner.get("execution") != required_execution or runner.get("limits") != {
        "solver_call_seconds": 120,
        "training_triplet_wall_seconds": 1800,
        "validation_candidate_wall_seconds": 7200,
        "test_plan_wall_seconds": 7200,
        "threads": 1,
    }:
        raise RuntimeError("M2.1 runner safety or limit protocol changed")
    if runner.get("solver") != {
        "interface": "gurobi_direct", "optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "fallback_allowed": False,
    }:
        raise RuntimeError("M2.1 solver identity changed")
    parent = pilot["frozen_design"]
    if sha256_file(design_path) != parent["sha256"]:
        raise RuntimeError("M2.1 frozen design hash mismatch")
    audit_path = root / parent["audit_path"]
    if sha256_file(audit_path) != parent["audit_sha256"]:
        raise RuntimeError("M2.1 PR #62 audit hash mismatch")
    for path_field, hash_field in (
        ("formal_extension_config", "formal_extension_config_sha256"),
        ("confirmation_config", "confirmation_config_sha256"),
    ):
        if sha256_file(root / pilot["scientific_base"][path_field]) != pilot["scientific_base"][hash_field]:
            raise RuntimeError(f"M2.1 scientific base hash mismatch: {path_field}")
    actual = pilot_fingerprints(root, pilot_path, runner_path)
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("M2.1 approved fingerprint mismatch")
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [pilot_path, runner_path, approval_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    runtime = capture_runtime_context(
        solver_preference=("gurobi",), project_root=root, solver_threads=1,
    )
    solver = runtime.get("solver") or {}
    if (
        solver.get("selected") != "gurobi_direct"
        or str(solver.get("version")) != "13.0.2"
        or int(solver.get("threads", -1)) != 1
    ):
        raise RuntimeError("M2.1 runtime is not Gurobi 13.0.2 through gurobi_direct Threads=1")
    return {
        "pilot": pilot, "design": design, "runner": runner,
        "fingerprints": actual, "locked_environment": validate_locked_environment(root),
        "source": source, "preflight_runtime": runtime,
    }


def _write_terminal_diagnostic(
    directory: Path, *, run_id: str, case_id: str, stage: str,
    status: str, error: BaseException,
) -> None:
    payload = {
        "run_id": run_id, "case_id": case_id, "status": status, "stage": stage,
        "message": f"{type(error).__name__}: {error}"[:1000],
        "updated_at_utc": utc_now(),
    }
    for name in ("runner_exception.json", "status_summary.json", "heartbeat.json"):
        try:
            atomic_write_json(directory / name, payload)
        except Exception:
            pass


def _validate_diagnostic_parent(
    output_root: Path, *, case_id: str, parent_run_id: str,
) -> None:
    rows = _read_registry(output_root / "pilot/pilot_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1 or matches[0].get("case_id") != case_id:
        raise ValueError("M2.1 diagnostic parent does not identify the same case")
    if matches[0].get("parent_run_id", "").strip() or matches[0].get("status") not in {
        "stage_failure", "timeout", "interrupted", "runner_exception",
    }:
        raise ValueError("M2.1 diagnostic parent is not a failed primary run")


def run_case(
    *, root: Path, output_root: Path, matrix_path: Path,
    pilot: Mapping[str, Any], design: Mapping[str, Any], runner: Mapping[str, Any],
    fingerprints: Mapping[str, str], locked_environment: Mapping[str, str],
    source: Mapping[str, Any], case: M21PilotCase, run_id: str,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("M2.1 pilot run_id is immutable")
        started = perf_counter(); stages: list[dict[str, Any]] = []
        failure = None; science = None; status = "running"
        sampler = PeakRSSSampler(); sampler.start()
        checkpoint = directory / "checkpoint.json"
        status_path = directory / "status_summary.json"
        heartbeat = directory / "heartbeat.json"

        def progress(stage: str, details: Mapping[str, Any]) -> None:
            stages.append({"stage": stage, **details, "updated_at_utc": utc_now()})
            atomic_write_json(checkpoint, {
                "run_id": run_id, "case": case.as_dict(), "status": "running",
                "completed_stages": stages[:-1], "current_stage": stage,
                "updated_at_utc": utc_now(),
            })
            compact = {
                "run_id": run_id, "case_id": case.case_id, "status": "running",
                "current_stage": stage, "completed_stage_count": max(0, len(stages) - 1),
                "failure": None,
            }
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)

        try:
            matrix = load_phase6_matrix(matrix_path)
            science = (science_executor or execute_triplet_science)(
                project_root=root, matrix=matrix, matrix_path=matrix_path,
                pilot_config=pilot, design_config=design, runner_config=runner,
                case=case, progress=progress,
            )
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": "KeyboardInterrupt", "exception_type": "KeyboardInterrupt"}
        except Exception as exc:
            solver_status = (
                str(exc.solver_status).strip().lower()
                if isinstance(exc, DevelopmentStageError) else ""
            )
            is_solver_timeout = (
                solver_status in {"time_limit", "master_time_limit"}
                or solver_status.endswith("_time_limit")
            )
            status = "timeout" if isinstance(exc, TimeoutError) or is_solver_timeout else "stage_failure"
            failure = {
                "stage": getattr(exc, "stage", stages[-1]["stage"] if stages else "initialization"),
                "status": status, "solver_status": solver_status or None,
                "message": f"{type(exc).__name__}: {exc}"[:1000],
                "exception_type": type(exc).__name__,
            }

        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "plan_artifact_finalization"
            if science is not None and "_plan_payloads" in science:
                payloads = science.pop("_plan_payloads")
                identities = _write_plan_artifacts(
                    directory=directory, run_id=run_id, case_id=case.case_id, payloads=payloads,
                )
                science["first_stage_plan_artifacts"] = identities
                minimum = identities["minimum_endpoint"]
                validate_minimum_endpoint_control_binding(minimum, minimum)
                science["minimum_endpoint_M2_control_identity"] = {
                    field: minimum[field] for field in PLAN_IDENTITY_FIELDS
                }
                for candidate_id, row in science["validation_results"].items():
                    identity = identities[candidate_id]
                    row["source_plan_identity"] = {
                        field: identity[field] for field in PLAN_IDENTITY_FIELDS
                    }
                for strategy_id, row in science["test_results"].items():
                    identity = identities[row["source_candidate_id"]]
                    row["source_plan_identity"] = {
                        field: identity[field] for field in PLAN_IDENTITY_FIELDS
                    }
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(
                solver_preference=("gurobi",), project_root=root, solver_threads=1,
            )
            result = {
                "run_id": run_id, "parent_run_id": parent_run_id,
                "case_id": case.case_id, "case": case.as_dict(), "status": status,
                "finalized": True, "science": science, "stages": stages,
                "failure": failure, "wall_seconds": wall, "peak_memory_mb": peak,
                "fingerprints": dict(fingerprints), "git_sha": source["commit_sha"],
                "git_tree_sha": source["tree_sha"], "finished_at_utc": utc_now(),
            }
            result_path, manifest_path = directory / "result.json", directory / "manifest.json"
            compact = {
                "run_id": run_id, "case_id": case.case_id, "status": status,
                "current_stage": failure.get("stage") if failure else None,
                "completed_stage_count": len(stages), "failure": compact_failure(failure),
                "updated_at_utc": utc_now(),
            }
            finalization_stage = "artifact_finalization"
            atomic_write_json(checkpoint, {"run_id": run_id, "case": case.as_dict(), "status": status, "completed_stages": stages, "failure": compact_failure(failure), "updated_at_utc": utc_now()})
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {
                "artifact_state": "finalized", "run_id": run_id, "case_id": case.case_id,
                "result_sha256": sha256_file(result_path),
                "checkpoint_sha256": sha256_file(checkpoint),
                "status_summary_sha256": sha256_file(status_path),
                "heartbeat_sha256": sha256_file(heartbeat),
                "fingerprints": dict(fingerprints), "source": dict(source),
                "locked_environment": dict(locked_environment), "runtime_context": runtime,
            })
            row = {
                "run_id": run_id, "parent_run_id": parent_run_id or "",
                "case_id": case.case_id, "run_kind": case.run_kind,
                "triplet_position": case.triplet_position,
                "training_seed": case.training_seed, "validation_seed": case.validation_seed,
                "test_seed": case.test_seed, "status": status,
                "wall_seconds": wall, "peak_memory_mb": peak, **dict(fingerprints),
                "result_path": str(result_path.resolve()), "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": sha256_file(manifest_path),
                "failure_stage": failure.get("stage") if failure else "",
                "updated_at_utc": result["finished_at_utc"],
            }
            finalization_stage = "registry_finalization"
            _write_registry(output_root, row)
            finalization_stage = "projection_finalization"
            projection = update_projection(
                output_root=output_root, pilot=pilot, design=design,
                fingerprints=fingerprints,
            )
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="interrupted", error=exc)
            raise
        except Exception as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="runner_exception", error=exc)
            raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "projection": projection}


def run_pilot(
    *, root: Path, pilot_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_preflight(
        root=root, pilot_path=pilot_path, runner_path=runner_path,
        approval_path=approval_path, authorize=authorize,
    )
    cases = build_pilot_cases(preflight["pilot"], preflight["design"])
    all_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary execution must run the complete frozen three-triplet pilot")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("diagnostic execution requires one case_id and parent_run_id")
    requested = set(case_ids or all_ids)
    if requested - all_ids:
        raise ValueError("unknown M2.1 pilot case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OUTPUT_ROOT; results: list[dict[str, Any]] = []
    with exclusive_file_lock(output_root / "pilot/.serial-execution.lock", timeout_seconds=1.0):
        existing = output_root / "pilot"
        if parent_run_id is None and existing.exists() and any(
            path.name != ".serial-execution.lock" for path in existing.iterdir()
        ):
            raise RuntimeError("primary M2.1 pilot requires an empty output namespace")
        if parent_run_id is not None:
            _validate_diagnostic_parent(
                output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id,
            )
        for case in selected:
            result = run_case(
                root=root, output_root=output_root,
                matrix_path=root / "configs/phase6_experiment_matrix.yaml",
                pilot=preflight["pilot"], design=preflight["design"],
                runner=preflight["runner"], fingerprints=preflight["fingerprints"],
                locked_environment=preflight["locked_environment"], source=preflight["source"],
                case=case, run_id=f"{run_id_prefix}_{case.case_id}",
                parent_run_id=parent_run_id, science_executor=science_executor,
            )
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

"""Safe, serial executor for the frozen Phase 6 M2 development matrix."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import threading
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import psutil
import yaml

from .phase6_environment import validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json
from .phase6_locking import exclusive_file_lock
from .phase6_m2 import (
    M2_E3_COMPONENT_FILES,
    M2_EXECUTION_READY_STATUS,
    M2_FAMILY_COMPONENT_FILES,
    M2_OUTPUT_ROOT,
    generate_m2_data,
    load_m2_config,
    m2_model_context,
    m2_fingerprints,
    solve_m2_fixed_reserve,
    solve_m2_endogenous_extensive,
)
from .phase6_m1 import (
    objective_tolerance,
    solve_minimum_feasible_reserve,
    solve_reserve_face_point,
)
from .phase6_protocol import load_phase6_matrix
from .reproducibility import (
    capture_runtime_context,
    sha256_file,
    validate_execution_source,
)


M2_DEVELOPMENT_APPROVAL = "configs/phase6_m2_development_approval.yaml"
REGISTRY_FIELDS = (
    "run_id",
    "parent_run_id",
    "case_id",
    "tier_id",
    "seed",
    "beta",
    "profile_id",
    "status",
    "substantive_activation",
    "wall_seconds",
    "peak_memory_mb",
    "scientific_config_sha256",
    "e3_component_sha256",
    "family_component_sha256",
    "runner_config_sha256",
    "environment_sha256",
    "result_path",
    "manifest_path",
    "manifest_sha256",
    "failure_stage",
    "updated_at_utc",
)
TERMINAL_STATUSES = {
    "optimal",
    "stage_failure",
    "timeout",
    "runner_exception",
    "preflight_failure",
    "interrupted",
}
FAILURE_FIELDS = (
    "stage",
    "status",
    "solver_status",
    "message",
    "exception_type",
)
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
TIMEOUT_STATUSES = {
    "time_limit",
    "master_time_limit",
    "oracle_time_limit",
    "timeout",
}


class DevelopmentStageError(RuntimeError):
    """Preserve a scientific stage's native terminal status."""

    def __init__(self, stage: str, solver_status: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.solver_status = solver_status


class PeakRSSSampler:
    """Lightweight process-RSS sampler used for an actual sampled peak."""

    def __init__(self, interval_seconds: float = 0.1) -> None:
        self.interval_seconds = interval_seconds
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        process = psutil.Process()
        while not self._stop.is_set():
            self.peak_mb = max(
                self.peak_mb,
                process.memory_info().rss / (1024.0 * 1024.0),
            )
            self._stop.wait(self.interval_seconds)

    def start(self) -> None:
        self._sample_once()
        self._thread.start()

    def _sample_once(self) -> None:
        self.peak_mb = max(
            self.peak_mb,
            psutil.Process().memory_info().rss / (1024.0 * 1024.0),
        )

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=max(1.0, self.interval_seconds * 5.0))
        self._sample_once()
        return self.peak_mb


def validate_run_id(run_id: str) -> str:
    """Allow one portable path component and reject traversal spellings."""

    if not isinstance(run_id, str) or not run_id:
        raise ValueError("M2 development run_id must be a nonempty string")
    if not SAFE_RUN_ID.fullmatch(run_id) or ".." in run_id:
        raise ValueError(
            "M2 development run_id may contain only letters, digits, dots, "
            "underscores, and hyphens, without '..'"
        )
    if Path(run_id).is_absolute() or Path(run_id).name != run_id:
        raise ValueError("M2 development run_id must be one safe path component")
    return run_id


def resolve_run_directory(output_root: Path, run_id: str) -> Path:
    validated = validate_run_id(run_id)
    runs_root = (output_root / "development" / "runs").resolve()
    directory = (runs_root / validated).resolve()
    if directory.parent != runs_root:
        raise ValueError("M2 development run path escapes the controlled root")
    return directory


def _is_timeout_status(status: str | None) -> bool:
    normalized = str(status or "").strip().lower()
    return normalized in TIMEOUT_STATUSES or normalized.endswith("_time_limit")


def _require_optimal(stage: str, status: str, message: str) -> None:
    if status != "optimal":
        raise DevelopmentStageError(stage, status, message)


def _native_failure_status(solution: Any) -> str:
    """Expose a nested recourse timeout hidden by an oracle_failure wrapper."""

    status = str(getattr(solution, "status", "unknown"))
    if _is_timeout_status(status):
        return status
    evaluation = getattr(solution, "evaluation", None)
    for result in getattr(evaluation, "scenario_results", {}).values():
        nested = str(getattr(result, "status", "unknown"))
        if _is_timeout_status(nested):
            return nested
    return status


@dataclass(frozen=True)
class DevelopmentCase:
    case_id: str
    tier_id: str
    seed: int
    beta: float
    profile_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def compact_failure(failure: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if failure is None:
        return None
    result = {key: failure.get(key) for key in FAILURE_FIELDS}
    message = str(result.get("message") or "")
    result["message"] = message[:1000]
    return result


def _case_token(value: float) -> str:
    return f"{value:.2f}".replace(".", "p")


def build_development_cases(config: Mapping[str, Any]) -> tuple[DevelopmentCase, ...]:
    raw = config["development_preregistration"]
    cases = tuple(
        DevelopmentCase(
            case_id=(
                f"V1_seed{int(seed)}_beta{_case_token(float(beta))}_"
                f"profile{str(profile_id)}"
            ),
            tier_id="V1",
            seed=int(seed),
            beta=float(beta),
            profile_id=str(profile_id),
        )
        for seed in raw["seeds"]
        for beta in raw["beta"]
        for profile_id in raw["profiles"]
    )
    if len(cases) != 27 or len({case.case_id for case in cases}) != 27:
        raise ValueError("M2 development matrix must contain 27 unique cases")
    return cases


def load_development_approval(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("M2 development approval must be a mapping")
    required = {
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
        "environment_sha256",
    }
    fingerprints = payload.get("approved_fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != required:
        raise ValueError("M2 development approval fingerprints are incomplete")
    expected_metadata = {
        "approval_id": "phase6_m2_development_execution_v1",
        "status": M2_EXECUTION_READY_STATUS,
        "scientific_protocol": "phase6_m2_supply_disruption_v1_0",
        "runner_namespace": "phase6_m2_supply_disruption",
        "matrix_case_count": 27,
        "explicit_cli_authorization_required": True,
        "formal_extension_authorized": False,
        "accept_m0_or_m1_authorization": False,
    }
    mismatches = {
        key: {"expected": value, "actual": payload.get(key)}
        for key, value in expected_metadata.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise ValueError(f"M2 development approval metadata mismatch: {mismatches}")
    return payload


def validate_development_preflight(
    *,
    project_root: Path,
    config_path: Path,
    runner_config_path: Path,
    approval_path: Path,
    authorize_development_execution: bool,
) -> dict[str, Any]:
    """Reject unsafe execution before scenario generation or Gurobi use."""

    config = load_m2_config(config_path)
    if config.get("status") != M2_EXECUTION_READY_STATUS:
        raise RuntimeError("M2 matrix is not frozen for development execution")
    if not authorize_development_execution:
        raise PermissionError(
            "M2 development execution requires --authorize-development-execution"
        )
    runner = yaml.safe_load(runner_config_path.read_text(encoding="utf-8"))
    if runner.get("namespace") != "phase6_m2_supply_disruption":
        raise RuntimeError("M2 runner namespace mismatch")
    if runner.get("output_root") != M2_OUTPUT_ROOT:
        raise RuntimeError("M2 runner output root mismatch")
    execution = runner.get("execution", {})
    if execution.get("development_execution_requires_explicit_authorization") is not True:
        raise RuntimeError("M2 runner does not enforce explicit authorization")
    if execution.get("formal_extension_authorized") is not False:
        raise RuntimeError("M2 formal extension must remain unauthorized")
    for field in (
        "accept_M0_or_M1_authorization",
        "accept_M0_or_M1_registry",
        "accept_M0_or_M1_projection",
    ):
        if execution.get(field) is not False:
            raise RuntimeError(f"M2 runner isolation guard mismatch: {field}")

    approval = load_development_approval(approval_path)
    locked = validate_locked_environment(project_root)
    actual = m2_fingerprints(
        project_root=project_root,
        config_path=config_path,
        runner_config_path=runner_config_path,
    )
    expected = approval["approved_fingerprints"]
    mismatches = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in expected
        if actual.get(key) != expected[key]
    }
    if mismatches:
        raise RuntimeError(f"M2 development fingerprint mismatch: {mismatches}")

    required_paths = {
        *(project_root / path for path in M2_E3_COMPONENT_FILES),
        *(project_root / path for path in M2_FAMILY_COMPONENT_FILES),
        config_path,
        runner_config_path,
        approval_path,
        project_root / "requirements-gurobi-lock.txt",
    }
    source = validate_execution_source(
        project_root,
        required_tracked_paths=sorted(required_paths),
    )
    return {
        "config": config,
        "runner": runner,
        "approval": approval,
        "fingerprints": actual,
        "locked_environment": locked,
        "source": source,
    }


def _decision_sha256(purchase: Mapping[str, Sequence[float]]) -> str:
    payload = json.dumps(
        purchase,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _failure_counts(evaluation: Any) -> dict[str, int]:
    if evaluation is None:
        return {"infeasible": 0, "solver_failure": 0, "missing": 1}
    return {
        "infeasible": len(evaluation.infeasible_scenarios),
        "solver_failure": len(evaluation.failed_scenarios),
        "missing": max(
            0,
            len(evaluation.scenario_results)
            - len(evaluation.exact_scenario_costs),
        ),
    }


def execute_development_case_science(
    *,
    project_root: Path,
    matrix: Mapping[str, Any],
    matrix_path: Path,
    config: Mapping[str, Any],
    case: DevelopmentCase,
    progress: Callable[[str, Mapping[str, Any]], None],
) -> dict[str, Any]:
    """Execute one case serially; callers own finalization and immutability."""

    reference = float(matrix["budget_plan"]["reference_budget_by_tier"]["V1"])
    budget = case.beta * reference
    progress("scenario_generation", {"budget": budget, "reference_budget": reference})
    generated = generate_m2_data(
        matrix,
        matrix_path=matrix_path,
        tier_id="V1",
        seed=case.seed,
        budget=budget,
        m2_config=config,
        profile_id=case.profile_id,
    )
    data = generated.data
    solver_call_seconds = float(generated.tier.solver_call_seconds)
    absolute = float(config["objective_tolerance"]["absolute_tolerance"])
    relative = float(config["objective_tolerance"]["relative_tolerance"])

    progress("minimum_feasible_reserve", {})
    floor = solve_minimum_feasible_reserve(
        data,
        solver_threads=1,
        time_limit_seconds=solver_call_seconds,
    )
    _require_optimal("minimum_feasible_reserve", floor.status,
                     f"minimum feasible reserve failed: {floor.status}")
    progress("complete_extensive_optimum", {})
    optimum = solve_m2_endogenous_extensive(
        data, solver_threads=1, time_limit_seconds=solver_call_seconds,
        consistency_tolerance=absolute,
    )
    _require_optimal(
        "complete_extensive_optimum", _native_failure_status(optimum),
        f"complete extensive optimum failed: {optimum.status}",
    )
    if optimum.objective is None:
        raise RuntimeError("complete extensive optimum returned no objective")
    tolerance = objective_tolerance(
        float(optimum.objective), absolute_tolerance=absolute,
        relative_tolerance=relative,
    )
    common = {
        "data": data, "master_optimum": float(optimum.master.objective),
        "exact_optimum": float(optimum.objective), "tolerance": tolerance,
        "solver_preference": ("gurobi",),
        "time_limit_seconds": solver_call_seconds, "solver_threads": 1,
        "feasibility_tolerance": 1.0e-7, "optimality_tolerance": 1.0e-7,
    }
    progress("minimum_tolerance_optimal_reserve", {})
    with m2_model_context():
        minimum = solve_reserve_face_point(direction="min", **common)
    _require_optimal("minimum_tolerance_optimal_reserve",
                     _native_failure_status(minimum),
                     f"minimum optimal reserve failed: {minimum.status}")
    progress("maximum_tolerance_optimal_reserve", {})
    with m2_model_context():
        maximum = solve_reserve_face_point(direction="max", **common)
    _require_optimal("maximum_tolerance_optimal_reserve",
                     _native_failure_status(maximum),
                     f"maximum optimal reserve failed: {maximum.status}")

    robust_reserve = float(minimum.reserve)
    ratio = robust_reserve / budget if budget > 0.0 else 0.0
    fixed: list[dict[str, Any]] = []
    for rho in (0.0, 0.1, 0.3, 0.5):
        progress(f"fixed_total_reserve_{rho:.1f}", {"rho": rho})
        solution = solve_m2_fixed_reserve(
            data,
            reserve_ratio=rho,
            solver_threads=1,
            time_limit_seconds=solver_call_seconds,
            consistency_tolerance=absolute,
        )
        _require_optimal(
            f"fixed_total_reserve_{rho:.1f}",
            _native_failure_status(solution),
            f"fixed reserve rho={rho} failed: {solution.status}",
        )
        if solution.objective is None:
            raise RuntimeError(f"fixed reserve rho={rho} returned no objective")
        fixed.append(
            {
                "rho": rho,
                "reserve": solution.reserve,
                "reserve_ratio": solution.reserve_ratio,
                "objective": solution.objective,
                "regular_purchase": solution.master.regular_purchase,
                "regular_purchase_sha256": _decision_sha256(
                    solution.master.regular_purchase
                ),
                "regular_purchase_reoptimized": True,
                "status": solution.status,
            }
        )

    endpoint_counts = {
        "minimum": _failure_counts(minimum.evaluation),
        "maximum": _failure_counts(maximum.evaluation),
    }
    if any(sum(values.values()) for values in endpoint_counts.values()):
        raise RuntimeError("reserve-face exact recourse evaluation is incomplete")
    return {
        "tier_id": case.tier_id,
        "seed": case.seed,
        "beta": case.beta,
        "profile_id": case.profile_id,
        "budget": budget,
        "reference_budget": reference,
        "R_star": optimum.reserve,
        "R_star_ratio": optimum.reserve_ratio,
        "R_min_feas": floor.reserve,
        "R_min_feas_ratio": floor.reserve_ratio,
        "R_min_feas_closed_form": floor.closed_form_reserve,
        "R_min_feas_closed_form_difference": floor.closed_form_difference,
        "R_min_opt": minimum.reserve,
        "R_max_opt": maximum.reserve,
        "R_min_robust_opt": robust_reserve,
        "R_min_robust_opt_ratio": ratio,
        "numerical_activation": ratio > 1.0e-4,
        "substantive_activation": ratio >= 0.01,
        "objective_tolerance": tolerance,
        "complete_extensive_objective": optimum.objective,
        "minimum_endpoint_exact_objective": minimum.exact_objective,
        "maximum_endpoint_exact_objective": maximum.exact_objective,
        "minimum_endpoint_status": minimum.status,
        "maximum_endpoint_status": maximum.status,
        "minimum_endpoint_consistency_difference": abs(
            float(minimum.exact_objective) - float(optimum.objective)
        ),
        "maximum_endpoint_consistency_difference": abs(
            float(maximum.exact_objective) - float(optimum.objective)
        ),
        "minimum_endpoint_regular_purchase": minimum.regular_purchase,
        "maximum_endpoint_regular_purchase": maximum.regular_purchase,
        "minimum_endpoint_regular_purchase_sha256": _decision_sha256(
            minimum.regular_purchase
        ),
        "maximum_endpoint_regular_purchase_sha256": _decision_sha256(
            maximum.regular_purchase
        ),
        "fixed_reserve_policies": fixed,
        "fulfillment_statistics": generated.statistics.as_dict(),
        "joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
        "scenario_component_set_sha256": generated.component_set_sha256,
        "scenario_identity_count": len(generated.scenario_identities),
        "c0_alpha_exactly_one": (
            case.profile_id != "C0" or all(
                float(value) == 1.0
                for scenario in data.scenarios
                for item in data.items
                for value in data.regular_fulfillment_rate[scenario][item]
            )
        ),
        "endpoint_failure_counts": endpoint_counts,
        "solver": "gurobi_direct",
        "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2",
        "threads": 1,
    }


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def upsert_development_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = output_root / "development"
    path = base / "development_run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        existing = _read_registry(path)
        if any(item["run_id"] == str(row["run_id"]) for item in existing):
            raise ValueError(f"immutable M2 development run_id exists: {row['run_id']}")
        atomic_write_csv(path, REGISTRY_FIELDS, [*existing, row])


def validate_run_artifacts(row: Mapping[str, str]) -> dict[str, Any]:
    result_path = Path(row["result_path"])
    manifest_path = Path(row["manifest_path"])
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("M2 development result or manifest is missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if row.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("M2 development manifest hash mismatch")
    if manifest.get("result_sha256") != sha256_file(result_path):
        raise ValueError("M2 development result hash mismatch")
    if manifest.get("run_id") != row.get("run_id"):
        raise ValueError("M2 development manifest run identity mismatch")
    if manifest.get("case_id") != row.get("case_id"):
        raise ValueError("M2 development manifest case identity mismatch")
    if result.get("run_id") != row.get("run_id"):
        raise ValueError("M2 development run identity mismatch")
    if result.get("case_id") != row.get("case_id"):
        raise ValueError("M2 development case identity mismatch")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("M2 development parent identity mismatch")
    case = result.get("case") or {}
    if case.get("tier_id") != row.get("tier_id"):
        raise ValueError("M2 development tier identity mismatch")
    if int(case.get("seed")) != int(row.get("seed")):
        raise ValueError("M2 development seed identity mismatch")
    if not math.isclose(float(case.get("beta")), float(row.get("beta")), abs_tol=1e-12):
        raise ValueError("M2 development beta identity mismatch")
    if case.get("profile_id") != row.get("profile_id"):
        raise ValueError("M2 development disruption-profile identity mismatch")
    if result.get("status") != row.get("status"):
        raise ValueError("M2 development status mismatch")
    wall_seconds = float(row.get("wall_seconds"))
    if not math.isfinite(wall_seconds) or not math.isclose(
        wall_seconds,
        float(result.get("wall_seconds")),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise ValueError("M2 development wall time mismatch")
    expected_activation = str(
        bool((result.get("science") or {}).get("substantive_activation"))
    )
    if str(row.get("substantive_activation")) != expected_activation:
        raise ValueError("M2 development activation mismatch")
    directory = result_path.parent
    for name, field in (
        ("checkpoint.json", "checkpoint_sha256"),
        ("status_summary.json", "status_summary_sha256"),
        ("heartbeat.json", "heartbeat_sha256"),
    ):
        path = directory / name
        if not path.is_file() or manifest.get(field) != sha256_file(path):
            raise ValueError(f"M2 development terminal artifact mismatch: {name}")
    for field in (
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
        "environment_sha256",
    ):
        if result["fingerprints"].get(field) != row.get(field):
            raise ValueError(f"M2 development registry fingerprint mismatch: {field}")
        if manifest.get("fingerprints", {}).get(field) != row.get(field):
            raise ValueError(f"M2 development manifest fingerprint mismatch: {field}")
    if manifest.get("source", {}).get("commit_sha") != result.get("git_sha"):
        raise ValueError("M2 development source commit mismatch")
    if manifest.get("source", {}).get("tree_sha") != result.get("git_tree_sha"):
        raise ValueError("M2 development source tree mismatch")
    if result.get("finalized") is not True:
        raise ValueError("M2 development result is not finalized")
    return result


def _recompute_scientific_evidence(
    science: Mapping[str, Any], config: Mapping[str, Any]
) -> dict[str, Any]:
    """Independently derive activation and verify all prerequisite evidence."""

    budget = float(science["budget"])
    if not math.isfinite(budget) or budget <= 0.0:
        raise ValueError("M2 development budget must be finite and positive")
    minimum_feasible = float(science["R_min_feas"])
    minimum_optimal = float(science["R_min_opt"])
    maximum_optimal = float(science["R_max_opt"])
    if not all(math.isfinite(value) for value in (
        minimum_feasible, minimum_optimal, maximum_optimal
    )):
        raise ValueError("M2 reserve interval contains a non-finite value")
    if maximum_optimal + 1.0e-8 < minimum_optimal:
        raise ValueError("M2 reserve interval endpoints are reversed")
    robust_discretionary = max(0.0, minimum_optimal - minimum_feasible)
    ratio = robust_discretionary / budget
    numerical_threshold = float(
        config["reserve_identification"][
            "numerical_activation_ratio_strictly_greater_than"
        ]
    )
    substantive_threshold = float(
        config["reserve_identification"][
            "substantive_activation_ratio_greater_than_or_equal_to"
        ]
    )
    tolerance = float(science["objective_tolerance"])
    optimum = float(science["complete_extensive_objective"])
    stored_endpoint_differences = {
        "minimum": float(science["minimum_endpoint_consistency_difference"]),
        "maximum": float(science["maximum_endpoint_consistency_difference"]),
    }
    endpoint_objectives = {
        "minimum": float(science["minimum_endpoint_exact_objective"]),
        "maximum": float(science["maximum_endpoint_exact_objective"]),
    }
    if not math.isfinite(tolerance) or tolerance < 0.0:
        raise ValueError("M2 objective tolerance is invalid")
    for endpoint, endpoint_objective in endpoint_objectives.items():
        if science.get(f"{endpoint}_endpoint_status") != "optimal":
            raise ValueError(f"M2 {endpoint} endpoint is not optimal")
        difference = abs(endpoint_objective - optimum)
        if not math.isfinite(difference) or difference > tolerance + 1.0e-8:
            raise ValueError(f"M2 {endpoint} endpoint exceeds objective tolerance")
        if not math.isfinite(endpoint_objective):
            raise ValueError(f"M2 {endpoint} endpoint objective is missing")
        if endpoint_objective > optimum + tolerance + 1.0e-8:
            raise ValueError(f"M2 {endpoint} endpoint is not tolerance-optimal")
        if not math.isclose(stored_endpoint_differences[endpoint], difference,
                            rel_tol=1.0e-10, abs_tol=1.0e-10):
            raise ValueError(f"stored M2 {endpoint} endpoint difference is inconsistent")
    endpoint_counts = science.get("endpoint_failure_counts")
    if not isinstance(endpoint_counts, Mapping) or set(endpoint_counts) != {
        "minimum", "maximum"
    }:
        raise ValueError("M2 endpoint exact-recourse counts are incomplete")
    if any(
        int(value) != 0
        for counts in endpoint_counts.values()
        for value in counts.values()
    ):
        raise ValueError("M2 endpoint exact-recourse evaluation is incomplete")

    fixed = science.get("fixed_reserve_policies")
    if not isinstance(fixed, list) or len(fixed) != 4:
        raise ValueError("M2 fixed-reserve evidence must contain four policies")
    expected_rhos = (0.0, 0.1, 0.3, 0.5)
    for policy, rho in zip(fixed, expected_rhos):
        if not math.isclose(float(policy.get("rho")), rho, abs_tol=1.0e-12):
            raise ValueError("M2 fixed-reserve policy order or ratio is invalid")
        if policy.get("status") != "optimal":
            raise ValueError("M2 fixed-reserve policy is not optimal")
        if policy.get("regular_purchase_reoptimized") is not True:
            raise ValueError("M2 fixed-reserve procurement was not re-optimized")
        if not re.fullmatch(r"[0-9a-f]{64}", str(
            policy.get("regular_purchase_sha256", "")
        )):
            raise ValueError("M2 fixed-reserve procurement hash is invalid")
        if not math.isclose(float(policy.get("reserve")), rho * budget,
                            rel_tol=1.0e-9, abs_tol=1.0e-7):
            raise ValueError("M2 fixed-reserve amount does not match rho * budget")
        if not math.isfinite(float(policy.get("objective"))):
            raise ValueError("M2 fixed-reserve objective is missing")

    components = science.get("scenario_component_set_sha256")
    component_fields = {
        "latent_draw_sha256", "demand_sha256", "fulfillment_sha256",
        "emergency_price_sha256", "emergency_supply_sha256",
    }
    if not isinstance(components, Mapping) or set(components) != component_fields:
        raise ValueError("M2 scenario component-set identity is incomplete")
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(value))
           for value in components.values()):
        raise ValueError("M2 scenario component-set hash is invalid")

    numerical = ratio > numerical_threshold
    substantive = ratio >= substantive_threshold
    if not math.isclose(float(science["R_min_robust_opt"]), robust_discretionary,
                        rel_tol=1.0e-10, abs_tol=1.0e-8):
        raise ValueError("stored robust discretionary reserve is inconsistent")
    if not math.isclose(float(science["R_min_robust_opt_ratio"]), ratio,
                        rel_tol=1.0e-10, abs_tol=1.0e-10):
        raise ValueError("stored robust discretionary reserve ratio is inconsistent")
    if science.get("numerical_activation") is not numerical:
        raise ValueError("stored numerical activation is inconsistent")
    if science.get("substantive_activation") is not substantive:
        raise ValueError("stored substantive activation is inconsistent")
    return {
        "R_disc_robust": robust_discretionary,
        "R_disc_robust_ratio": ratio,
        "numerical_activation": numerical,
        "substantive_activation": substantive,
        "endpoint_evidence_complete": True,
        "fixed_policy_evidence_complete": True,
        "scenario_component_set_sha256": dict(components),
    }


def update_development_projection(
    *,
    output_root: Path,
    config: Mapping[str, Any],
    fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Rebuild the activation gate only from finalized, verified M2 artifacts."""

    base = output_root / "development"
    registry_path = base / "development_run_registry.csv"
    projection_path = base / "development_activation_projection.json"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = _read_registry(registry_path)
        current = [
            row
            for row in rows
            if all(row.get(key) == value for key, value in fingerprints.items())
        ]
        invalid_primary: list[str] = []
        invalid_diagnostics: list[str] = []
        verified: dict[str, dict[str, Any]] = {}
        recomputed: dict[str, dict[str, Any]] = {}
        for row in current:
            try:
                result = validate_run_artifacts(row)
                verified[row["run_id"]] = result
                if result.get("status") == "optimal":
                    recomputed[row["run_id"]] = _recompute_scientific_evidence(
                        result.get("science") or {}, config
                    )
            except (OSError, TypeError, ValueError, KeyError, json.JSONDecodeError):
                target = (
                    invalid_diagnostics
                    if row.get("parent_run_id", "").strip()
                    else invalid_primary
                )
                target.append(row["run_id"])
        primaries = [row for row in current if not row.get("parent_run_id", "").strip()]
        diagnostics = [row["run_id"] for row in current if row.get("parent_run_id", "").strip()]
        by_case: dict[str, list[dict[str, str]]] = {}
        for row in primaries:
            by_case.setdefault(row["case_id"], []).append(row)
        duplicates = sorted(case for case, values in by_case.items() if len(values) > 1)
        expected_cases = build_development_cases(config)
        evidence_by_identity: dict[tuple[int, float, str], dict[str, Any]] = {}
        for result in verified.values():
            case = result.get("case") or {}
            identity = (
                int(case.get("seed")), float(case.get("beta")),
                str(case.get("profile_id")),
            )
            if result["run_id"] in recomputed:
                evidence_by_identity[identity] = recomputed[result["run_id"]]

        common_random_number_checks: list[dict[str, Any]] = []
        common_random_numbers_valid = True
        common_fields = (
            "latent_draw_sha256", "demand_sha256",
            "emergency_price_sha256", "emergency_supply_sha256",
        )
        for seed in (2026081201, 2026081202, 2026081203):
            for beta in (0.9, 1.1, 1.3):
                identities = [(seed, beta, profile) for profile in ("C0", "C1", "C2")]
                evidence = [evidence_by_identity.get(identity) for identity in identities]
                field_matches = {
                    field: (
                        all(item is not None for item in evidence)
                        and len({
                            item["scenario_component_set_sha256"][field]
                            for item in evidence if item is not None
                        }) == 1
                    )
                    for field in common_fields
                }
                verified_pairing = all(field_matches.values())
                common_random_numbers_valid &= verified_pairing
                common_random_number_checks.append({
                    "seed": seed,
                    "beta": beta,
                    "profiles": ["C0", "C1", "C2"],
                    "field_matches": field_matches,
                    "verified": verified_pairing,
                    "fulfillment_hashes": {
                        profile: (
                            item["scenario_component_set_sha256"]["fulfillment_sha256"]
                            if item is not None else None
                        )
                        for profile, item in zip(("C0", "C1", "C2"), evidence)
                    },
                })
        combinations: list[dict[str, Any]] = []
        candidate_by_beta_profile: dict[tuple[float, str], dict[str, Any]] = {}
        missing: list[str] = []
        for beta in (0.9, 1.1, 1.3):
            for profile_id in ("C0", "C1", "C2"):
                cases = [
                    case for case in expected_cases
                    if case.beta == beta and case.profile_id == profile_id
                ]
                records = []
                for case in cases:
                    matches = by_case.get(case.case_id, [])
                    if len(matches) != 1:
                        missing.append(case.case_id)
                        continue
                    row = matches[0]
                    result = verified.get(row["run_id"])
                    if result is not None:
                        records.append(result)
                all_optimal = len(records) == 3 and all(
                    result.get("status") == "optimal" for result in records
                )
                evidence = [
                    recomputed.get(result["run_id"])
                    for result in records
                ]
                science_complete = len(evidence) == 3 and all(
                    item is not None for item in evidence
                )
                numerical_count = sum(
                    item["numerical_activation"] is True
                    for item in evidence if item is not None
                )
                substantive_count = sum(
                    item["substantive_activation"] is True
                    for item in evidence if item is not None
                )
                raw_activation_gate = (
                    all_optimal and science_complete and substantive_count >= 2
                )
                item = {
                    "beta": beta,
                    "profile_id": profile_id,
                    "completed_seed_count": len(records),
                    "optimal_seed_count": sum(
                        result.get("status") == "optimal" for result in records
                    ),
                    "scientific_evidence_seed_count": sum(
                        item is not None for item in evidence
                    ),
                    "numerical_activation_seed_count": numerical_count,
                    "substantive_activation_seed_count": substantive_count,
                    "raw_activation_gate_passed": raw_activation_gate,
                    "gate_passed": False,
                    "run_ids": [result["run_id"] for result in records],
                }
                combinations.append(item)
                candidate_by_beta_profile[(beta, profile_id)] = item

        passed: list[dict[str, Any]] = []
        baseline_confounded_betas: list[float] = []
        for beta in (0.9, 1.1, 1.3):
            baseline = candidate_by_beta_profile[(beta, "C0")]
            baseline_optimal = baseline["optimal_seed_count"] == 3
            baseline_activates = baseline["raw_activation_gate_passed"]
            if baseline_activates:
                baseline_confounded_betas.append(beta)
            for profile_id in ("C1", "C2"):
                item = candidate_by_beta_profile[(beta, profile_id)]
                pairing_ok = all(
                    check["verified"]
                    for check in common_random_number_checks
                    if check["beta"] == beta
                )
                item["c0_all_three_seeds_optimal"] = baseline_optimal
                item["c0_substantive_activation_seed_count"] = baseline[
                    "substantive_activation_seed_count"
                ]
                item["common_random_numbers_verified"] = pairing_ok
                item["gate_passed"] = bool(
                    item["raw_activation_gate_passed"]
                    and baseline_optimal
                    and not baseline_activates
                    and pairing_ok
                )
                if item["gate_passed"]:
                    passed.append(item)
            baseline["gate_passed"] = False
            baseline["control_profile_not_eligible"] = True
        verified_primary_ids = {
            row["run_id"]
            for row in primaries
            if row["run_id"] in verified
        }
        all_primary_finalized = (
            len(verified_primary_ids) == 27
            and not missing
            and not duplicates
            and not invalid_primary
            and not diagnostics
            and not invalid_diagnostics
        )
        all_primary_optimal = all_primary_finalized and all(
            result.get("status") == "optimal"
            for run_id, result in verified.items()
            if run_id in verified_primary_ids
        )
        gate_passed = (
            all_primary_optimal
            and common_random_numbers_valid
            and not baseline_confounded_betas
            and bool(passed)
        )
        payload = {
            "status": (
                "passed" if gate_passed else "completed_no_activation"
                if all_primary_optimal else "completed_with_failures"
                if all_primary_finalized else "incomplete"
            ),
            "fingerprints": dict(fingerprints),
            "required_primary_run_count": 27,
            "verified_primary_run_count": len(verified_primary_ids),
            "missing_case_ids": sorted(set(missing)),
            "invalid_primary_run_ids": sorted(invalid_primary),
            "invalid_diagnostic_run_ids": sorted(invalid_diagnostics),
            "duplicate_case_ids": duplicates,
            "diagnostic_run_ids": diagnostics,
            "combinations": combinations,
            "passed_combinations": passed,
            "baseline_activation_confounded_betas": baseline_confounded_betas,
            "common_random_number_checks": common_random_number_checks,
            "common_random_numbers_verified": common_random_numbers_valid,
            "development_activation_gate_passed": gate_passed,
            "formal_extension_authorized": False,
            "stop_reason": (
                "baseline_activation_confounds_disruption_attribution"
                if all_primary_optimal and baseline_confounded_betas
                else "common_random_number_evidence_failed"
                if all_primary_optimal and not common_random_numbers_valid
                else
                "no_preregistered_combination_passed"
                if all_primary_optimal and not passed
                else "development_primary_failure"
                if all_primary_finalized and not all_primary_optimal
                else None
            ),
            "selection_metrics_excluded": [
                "cost",
                "service_level",
                "P95",
                "CVaR",
                "manual_trend",
            ],
            "updated_at_utc": utc_now(),
        }
        atomic_write_json(projection_path, payload)
        return payload


def run_development_case(
    *,
    project_root: Path,
    output_root: Path,
    matrix_path: Path,
    config: Mapping[str, Any],
    fingerprints: Mapping[str, str],
    locked_environment: Mapping[str, str],
    source: Mapping[str, Any],
    case: DevelopmentCase,
    run_id: str,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_development_case_science,
) -> dict[str, Any]:
    validate_run_id(run_id)
    if parent_run_id is not None:
        validate_run_id(parent_run_id)
    base = output_root / "development"
    directory = resolve_run_directory(output_root, run_id)
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError(f"M2 development run_id is immutable: {run_id}")
        started = perf_counter()
        stages: list[dict[str, Any]] = []
        sampler = PeakRSSSampler()
        sampler_started = False
        peak_memory_mb = 0.0
        failure = None
        checkpoint = directory / "checkpoint.json"
        status_path = directory / "status_summary.json"
        heartbeat = directory / "heartbeat.json"

        def save(status: str, current_stage: str | None = None) -> None:
            full = {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "case": case.as_dict(),
                "status": status,
                "current_stage": current_stage,
                "completed_stages": stages,
                "failure": failure,
                "updated_at_utc": utc_now(),
            }
            atomic_write_json(checkpoint, full)
            compact = {
                "run_id": run_id,
                "case_id": case.case_id,
                "status": status,
                "current_stage": current_stage,
                "completed_stage_count": len(stages),
                "failure": compact_failure(failure),
                "updated_at_utc": full["updated_at_utc"],
            }
            atomic_write_json(status_path, compact)
            atomic_write_json(heartbeat, compact)

        active_stage_index: int | None = None
        stage_started = 0.0

        def progress(stage: str, details: Mapping[str, Any]) -> None:
            nonlocal active_stage_index, stage_started
            now = perf_counter()
            if active_stage_index is not None:
                stages[active_stage_index]["status"] = "completed"
                stages[active_stage_index]["runtime_seconds"] = now - stage_started
            stage_started = now
            stages.append({"stage": stage, "status": "running", **details})
            active_stage_index = len(stages) - 1
            save("running", stage)

        science = None
        status = "running"
        runtime_context: dict[str, Any] | None = None
        interrupted: KeyboardInterrupt | None = None
        try:
            sampler.start()
            sampler_started = True
            save("running", "initialization")
            progress("matrix_load", {"matrix_path": str(matrix_path)})
            matrix = load_phase6_matrix(matrix_path)
            progress("science_execution", {})
            science = science_executor(
                project_root=project_root,
                matrix=matrix,
                matrix_path=matrix_path,
                config=config,
                case=case,
                progress=progress,
            )
            if active_stage_index is not None:
                stages[active_stage_index]["status"] = "completed"
                stages[active_stage_index]["runtime_seconds"] = (
                    perf_counter() - stage_started
                )
            status = "optimal"
        except KeyboardInterrupt as exc:
            interrupted = exc
            status = "interrupted"
            failure = {
                "stage": stages[-1]["stage"] if stages else "initialization",
                "status": status,
                "message": "KeyboardInterrupt",
                "exception_type": "KeyboardInterrupt",
            }
        except DevelopmentStageError as exc:
            status = "timeout" if _is_timeout_status(exc.solver_status) else "stage_failure"
            failure = {
                "stage": exc.stage,
                "status": status,
                "solver_status": exc.solver_status,
                "message": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
            }
        except Exception as exc:
            current_stage = stages[-1]["stage"] if stages else "initialization"
            status = (
                "timeout"
                if isinstance(exc, TimeoutError)
                else "runner_exception"
                if current_stage in {"initialization", "matrix_load"}
                else "stage_failure"
            )
            failure = {
                "stage": current_stage,
                "status": status,
                "message": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
            }
        finally:
            if sampler_started:
                peak_memory_mb = sampler.stop()

        try:
            runtime_context = capture_runtime_context(
                solver_preference=("gurobi",),
                project_root=project_root,
                solver_threads=1,
            )
        except Exception as exc:
            runtime_context = {
                "status": "capture_failed",
                "exception_type": type(exc).__name__,
                "message": str(exc)[:1000],
            }
            if interrupted is None:
                status = "runner_exception"
                failure = {
                    "stage": "runtime_context",
                    "status": status,
                    "message": f"{type(exc).__name__}: {exc}",
                    "exception_type": type(exc).__name__,
                }
                science = None
        wall_seconds = perf_counter() - started
        failure_text = str((failure or {}).get("message", "")).lower()
        infeasible_failure = failure is not None and "infeasible" in failure_text
        solver_stage_failure = failure is not None and any(
            token in str(failure.get("stage", ""))
            for token in (
                "minimum_feasible_reserve",
                "complete_extensive_optimum",
                "optimal_reserve",
                "fixed_total_reserve",
            )
        )
        result = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "case_id": case.case_id,
            "case": case.as_dict(),
            "status": status,
            "finalized": True,
            "science": science,
            "stages": stages,
            "failure": failure,
            "failure_counts": {
                "infeasible_recourse": int(infeasible_failure),
                "solver_failure": int(
                    solver_stage_failure
                    and not infeasible_failure
                    and status != "timeout"
                ),
                "runner_failure": int(
                    failure is not None
                    and not solver_stage_failure
                    and status != "timeout"
                ),
                "timeout": int(status == "timeout"),
                "missing": int(science is None),
            },
            "wall_seconds": wall_seconds,
            "peak_memory_mb": peak_memory_mb,
            "memory_metric": "sampled_process_peak_rss_mb",
            "fingerprints": dict(fingerprints),
            "git_sha": source["commit_sha"],
            "git_tree_sha": source["tree_sha"],
            "finished_at_utc": utc_now(),
        }
        result_path = directory / "result.json"
        manifest_path = directory / "manifest.json"
        def write_terminal_artifacts() -> None:
            terminal_stage = (failure or {}).get("stage") if status != "optimal" else None
            save(status, terminal_stage)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {
                "artifact_state": "finalized",
                "run_id": run_id,
                "case_id": case.case_id,
                "result_path": str(result_path.resolve()),
                "result_sha256": sha256_file(result_path),
                "checkpoint_sha256": sha256_file(checkpoint),
                "status_summary_sha256": sha256_file(status_path),
                "heartbeat_sha256": sha256_file(heartbeat),
                "fingerprints": dict(fingerprints),
                "source": dict(source),
                "locked_environment": dict(locked_environment),
                "runtime_context": runtime_context,
            })

        try:
            write_terminal_artifacts()
        except Exception as exc:
            status = "runner_exception"
            failure = {
                "stage": "artifact_finalization",
                "status": status,
                "message": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
            }
            science = None
            result.update({
                "status": status,
                "science": None,
                "failure": failure,
                "failure_counts": {
                    "infeasible_recourse": 0,
                    "solver_failure": 0,
                    "runner_failure": 1,
                    "timeout": 0,
                    "missing": 1,
                },
                "finished_at_utc": utc_now(),
            })
            # Best-effort immutable terminal evidence. If storage itself is
            # unavailable, the original exception remains visible to the CLI.
            try:
                write_terminal_artifacts()
            except Exception:
                raise exc
        row = {
            "run_id": run_id,
            "parent_run_id": parent_run_id or "",
            "case_id": case.case_id,
            "tier_id": case.tier_id,
            "seed": case.seed,
            "beta": case.beta,
            "profile_id": case.profile_id,
            "status": status,
            "substantive_activation": (
                science.get("substantive_activation") if science else False
            ),
            "wall_seconds": wall_seconds,
            "peak_memory_mb": peak_memory_mb,
            **dict(fingerprints),
            "result_path": str(result_path.resolve()),
            "manifest_path": str(manifest_path.resolve()),
            "manifest_sha256": sha256_file(manifest_path),
            "failure_stage": failure.get("stage") if failure else "",
            "updated_at_utc": result["finished_at_utc"],
        }
        try:
            upsert_development_registry(output_root, row)
        except Exception as exc:
            status = "runner_exception"
            failure = {
                "stage": "registry_finalization",
                "status": status,
                "message": f"{type(exc).__name__}: {exc}",
                "exception_type": type(exc).__name__,
            }
            science = None
            result.update({
                "status": status,
                "science": None,
                "failure": failure,
                "failure_counts": {
                    "infeasible_recourse": 0,
                    "solver_failure": 0,
                    "runner_failure": 1,
                    "timeout": 0,
                    "missing": 1,
                },
                "finished_at_utc": utc_now(),
            })
            write_terminal_artifacts()
            row.update({
                "status": status,
                "substantive_activation": False,
                "manifest_sha256": sha256_file(manifest_path),
                "failure_stage": "registry_finalization",
                "updated_at_utc": result["finished_at_utc"],
            })
            atomic_write_json(
                directory / "registry_failure.json",
                compact_failure(failure),
            )
            if not any(
                item.get("run_id") == run_id
                for item in _read_registry(base / "development_run_registry.csv")
            ):
                upsert_development_registry(output_root, row)
        try:
            projection = update_development_projection(
                output_root=output_root,
                config=config,
                fingerprints=fingerprints,
            )
        except Exception as exc:
            # The finalized run remains immutable and registered. Record the
            # aggregation failure separately without corrupting its hashes.
            atomic_write_json(
                directory / "projection_failure.json",
                compact_failure({
                    "stage": "projection_finalization",
                    "status": "runner_exception",
                    "message": f"{type(exc).__name__}: {exc}",
                    "exception_type": type(exc).__name__,
                }),
            )
            raise
        if interrupted is not None:
            raise interrupted
        return {**result, "projection": projection}


def run_development_matrix(
    *,
    project_root: Path,
    config_path: Path,
    runner_config_path: Path,
    approval_path: Path,
    authorize_development_execution: bool,
    run_id_prefix: str,
    case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_development_case_science,
) -> list[dict[str, Any]]:
    """Execute selected frozen cases strictly serially under one global lock."""

    validate_run_id(run_id_prefix)
    if parent_run_id is not None:
        validate_run_id(parent_run_id)
    preflight = validate_development_preflight(
        project_root=project_root,
        config_path=config_path,
        runner_config_path=runner_config_path,
        approval_path=approval_path,
        authorize_development_execution=authorize_development_execution,
    )
    config = preflight["config"]
    all_cases = build_development_cases(config)
    requested = set(case_ids or [case.case_id for case in all_cases])
    unknown = requested - {case.case_id for case in all_cases}
    if unknown:
        raise ValueError(f"unknown M2 development cases: {sorted(unknown)}")
    selected = [case for case in all_cases if case.case_id in requested]
    output_root = project_root / M2_OUTPUT_ROOT
    matrix_path = project_root / config["base_model"]["matrix_path"]
    results = []
    with exclusive_file_lock(
        output_root / "development" / ".serial-execution.lock",
        timeout_seconds=1.0,
    ):
        if case_ids is None and parent_run_id is None:
            existing = output_root / "development"
            if existing.exists() and any(
                path.name != ".serial-execution.lock"
                for path in existing.iterdir()
            ):
                raise RuntimeError(
                    "M2 primary development matrix requires an empty controlled "
                    "development output root"
                )
        for case in selected:
            run_id = f"{run_id_prefix}_{case.case_id}"
            result = run_development_case(
                project_root=project_root,
                output_root=output_root,
                matrix_path=matrix_path,
                config=config,
                fingerprints=preflight["fingerprints"],
                locked_environment=preflight["locked_environment"],
                source=preflight["source"],
                case=case,
                run_id=run_id,
                parent_run_id=parent_run_id,
                science_executor=science_executor,
            )
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

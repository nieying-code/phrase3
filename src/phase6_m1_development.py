"""Safe, serial executor for the frozen Phase 6 M1 development matrix."""

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

import psutil
import yaml

from .phase6_environment import validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json
from .phase6_locking import exclusive_file_lock
from .phase6_m1 import (
    M1_E3_COMPONENT_FILES,
    M1_EXECUTION_READY_STATUS,
    M1_FAMILY_COMPONENT_FILES,
    M1_OUTPUT_ROOT,
    generate_m1_data,
    load_m1_config,
    m1_fingerprints,
    objective_tolerance,
    solve_fixed_autonomous_reserve,
    solve_m1_endogenous_extensive,
    solve_minimum_feasible_reserve,
    solve_reserve_face_point,
)
from .phase6_protocol import load_phase6_matrix
from .reproducibility import (
    capture_runtime_context,
    sha256_file,
    validate_execution_source,
)


M1_DEVELOPMENT_APPROVAL = "configs/phase6_m1_development_approval.yaml"
REGISTRY_FIELDS = (
    "run_id",
    "parent_run_id",
    "case_id",
    "tier_id",
    "seed",
    "beta",
    "kappa",
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
}
FAILURE_FIELDS = ("stage", "status", "message", "exception_type")


@dataclass(frozen=True)
class DevelopmentCase:
    case_id: str
    tier_id: str
    seed: int
    beta: float
    kappa: float | None

    @property
    def cap_config(self) -> dict[str, Any]:
        return {
            "enabled": self.kappa is not None,
            "kappa": self.kappa,
        }

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


def _case_token(value: float | None) -> str:
    if value is None:
        return "unbounded"
    return f"{value:.2f}".replace(".", "p")


def build_development_cases(config: Mapping[str, Any]) -> tuple[DevelopmentCase, ...]:
    raw = config["development_preregistration"]
    cases = tuple(
        DevelopmentCase(
            case_id=(
                f"V1_seed{int(seed)}_beta{_case_token(float(beta))}_"
                f"kappa{_case_token(None if kappa is None else float(kappa))}"
            ),
            tier_id="V1",
            seed=int(seed),
            beta=float(beta),
            kappa=None if kappa is None else float(kappa),
        )
        for seed in raw["seeds"]
        for beta in raw["beta"]
        for kappa in raw["kappa"]
    )
    if len(cases) != 63 or len({case.case_id for case in cases}) != 63:
        raise ValueError("M1 development matrix must contain 63 unique cases")
    return cases


def load_development_approval(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("M1 development approval must be a mapping")
    required = {
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
        "environment_sha256",
    }
    fingerprints = payload.get("approved_fingerprints")
    if not isinstance(fingerprints, dict) or set(fingerprints) != required:
        raise ValueError("M1 development approval fingerprints are incomplete")
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

    config = load_m1_config(config_path)
    if config.get("status") != M1_EXECUTION_READY_STATUS:
        raise RuntimeError("M1 matrix is not frozen for development execution")
    if not authorize_development_execution:
        raise PermissionError(
            "M1 development execution requires --authorize-development-execution"
        )
    runner = yaml.safe_load(runner_config_path.read_text(encoding="utf-8"))
    execution = runner.get("execution", {})
    if execution.get("development_execution_requires_explicit_authorization") is not True:
        raise RuntimeError("M1 runner does not enforce explicit authorization")
    if execution.get("formal_extension_authorized") is not False:
        raise RuntimeError("M1 formal extension must remain unauthorized")

    locked = validate_locked_environment(project_root)
    actual = m1_fingerprints(
        project_root=project_root,
        config_path=config_path,
        runner_config_path=runner_config_path,
    )
    approval = load_development_approval(approval_path)
    expected = approval["approved_fingerprints"]
    mismatches = {
        key: {"expected": expected[key], "actual": actual[key]}
        for key in expected
        if actual.get(key) != expected[key]
    }
    if mismatches:
        raise RuntimeError(f"M1 development fingerprint mismatch: {mismatches}")

    required_paths = {
        *(project_root / path for path in M1_E3_COMPONENT_FILES),
        *(project_root / path for path in M1_FAMILY_COMPONENT_FILES),
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
    generated = generate_m1_data(
        matrix,
        matrix_path=matrix_path,
        tier_id="V1",
        seed=case.seed,
        budget=budget,
        cap_config=case.cap_config,
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
    if floor.status != "optimal" or floor.reserve is None:
        raise RuntimeError(f"minimum feasible reserve failed: {floor.status}")
    if (
        floor.closed_form_difference is None
        or float(floor.closed_form_difference) > absolute
    ):
        raise RuntimeError("minimum feasible reserve closed-form check failed")

    progress("complete_extensive_optimum", {})
    optimum = solve_m1_endogenous_extensive(
        data,
        solver_threads=1,
        consistency_tolerance=float(config["objective_tolerance"]["absolute_tolerance"]),
    )
    if optimum.status != "optimal" or optimum.objective is None:
        raise RuntimeError(f"complete extensive optimum failed: {optimum.status}")
    tolerance = objective_tolerance(
        float(optimum.objective),
        absolute_tolerance=absolute,
        relative_tolerance=relative,
    )
    common = {
        "data": data,
        "master_optimum": float(optimum.master.objective),
        "exact_optimum": float(optimum.objective),
        "tolerance": tolerance,
        "solver_preference": ("gurobi",),
        "time_limit_seconds": solver_call_seconds,
        "solver_threads": 1,
        "feasibility_tolerance": 1.0e-7,
        "optimality_tolerance": 1.0e-7,
    }
    progress("minimum_tolerance_optimal_reserve", {})
    minimum = solve_reserve_face_point(direction="min", **common)
    if minimum.status != "optimal" or minimum.reserve is None:
        raise RuntimeError(f"minimum optimal reserve failed: {minimum.status}")
    progress("maximum_tolerance_optimal_reserve", {})
    maximum = solve_reserve_face_point(direction="max", **common)
    if maximum.status != "optimal" or maximum.reserve is None:
        raise RuntimeError(f"maximum optimal reserve failed: {maximum.status}")

    discretionary = max(0.0, float(minimum.reserve) - float(floor.reserve))
    ratio = discretionary / budget if budget > 0.0 else 0.0
    fixed: list[dict[str, Any]] = []
    for rho in (0.0, 0.1, 0.3, 0.5):
        progress(f"fixed_autonomous_reserve_{rho:.1f}", {"rho": rho})
        solution = solve_fixed_autonomous_reserve(
            data,
            rho=rho,
            minimum_feasible_reserve=float(floor.reserve),
            solver_threads=1,
            time_limit_seconds=solver_call_seconds,
            consistency_tolerance=absolute,
        )
        if solution.status != "optimal" or solution.objective is None:
            raise RuntimeError(f"fixed reserve rho={rho} failed: {solution.status}")
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
        "kappa": case.kappa,
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
        "R_disc_robust": discretionary,
        "R_disc_robust_ratio": ratio,
        "numerical_activation": ratio > 1.0e-4,
        "substantive_activation": ratio >= 0.01,
        "objective_tolerance": tolerance,
        "complete_extensive_objective": optimum.objective,
        "minimum_endpoint_exact_objective": minimum.exact_objective,
        "maximum_endpoint_exact_objective": maximum.exact_objective,
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
        "fixed_autonomous_reserve_policies": fixed,
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
            raise ValueError(f"immutable M1 development run_id exists: {row['run_id']}")
        atomic_write_csv(path, REGISTRY_FIELDS, [*existing, row])


def validate_run_artifacts(row: Mapping[str, str]) -> dict[str, Any]:
    result_path = Path(row["result_path"])
    manifest_path = Path(row["manifest_path"])
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("M1 development result or manifest is missing")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if row.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("M1 development manifest hash mismatch")
    if manifest.get("result_sha256") != sha256_file(result_path):
        raise ValueError("M1 development result hash mismatch")
    if manifest.get("run_id") != row.get("run_id"):
        raise ValueError("M1 development manifest run identity mismatch")
    if manifest.get("case_id") != row.get("case_id"):
        raise ValueError("M1 development manifest case identity mismatch")
    if result.get("run_id") != row.get("run_id"):
        raise ValueError("M1 development run identity mismatch")
    if result.get("case_id") != row.get("case_id"):
        raise ValueError("M1 development case identity mismatch")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("M1 development parent identity mismatch")
    case = result.get("case") or {}
    if case.get("tier_id") != row.get("tier_id"):
        raise ValueError("M1 development tier identity mismatch")
    if int(case.get("seed")) != int(row.get("seed")):
        raise ValueError("M1 development seed identity mismatch")
    if not math.isclose(float(case.get("beta")), float(row.get("beta")), abs_tol=1e-12):
        raise ValueError("M1 development beta identity mismatch")
    result_kappa = "unbounded" if case.get("kappa") is None else float(case["kappa"])
    row_kappa = row.get("kappa")
    if result_kappa == "unbounded":
        kappa_matches = row_kappa == "unbounded"
    else:
        try:
            kappa_matches = math.isclose(
                float(result_kappa), float(row_kappa), abs_tol=1e-12
            )
        except (TypeError, ValueError):
            kappa_matches = False
    if not kappa_matches:
        raise ValueError("M1 development kappa identity mismatch")
    if result.get("status") != row.get("status"):
        raise ValueError("M1 development status mismatch")
    wall_seconds = float(row.get("wall_seconds"))
    if not math.isfinite(wall_seconds) or not math.isclose(
        wall_seconds,
        float(result.get("wall_seconds")),
        rel_tol=1e-12,
        abs_tol=1e-9,
    ):
        raise ValueError("M1 development wall time mismatch")
    expected_activation = str(
        bool((result.get("science") or {}).get("substantive_activation"))
    )
    if str(row.get("substantive_activation")) != expected_activation:
        raise ValueError("M1 development activation mismatch")
    directory = result_path.parent
    for name, field in (
        ("checkpoint.json", "checkpoint_sha256"),
        ("status_summary.json", "status_summary_sha256"),
        ("heartbeat.json", "heartbeat_sha256"),
    ):
        path = directory / name
        if not path.is_file() or manifest.get(field) != sha256_file(path):
            raise ValueError(f"M1 development terminal artifact mismatch: {name}")
    for field in (
        "scientific_config_sha256",
        "e3_component_sha256",
        "family_component_sha256",
        "runner_config_sha256",
        "environment_sha256",
    ):
        if result["fingerprints"].get(field) != row.get(field):
            raise ValueError(f"M1 development registry fingerprint mismatch: {field}")
        if manifest.get("fingerprints", {}).get(field) != row.get(field):
            raise ValueError(f"M1 development manifest fingerprint mismatch: {field}")
    if manifest.get("source", {}).get("commit_sha") != result.get("git_sha"):
        raise ValueError("M1 development source commit mismatch")
    if manifest.get("source", {}).get("tree_sha") != result.get("git_tree_sha"):
        raise ValueError("M1 development source tree mismatch")
    if result.get("finalized") is not True:
        raise ValueError("M1 development result is not finalized")
    return result


def update_development_projection(
    *,
    output_root: Path,
    config: Mapping[str, Any],
    fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Rebuild the activation gate only from finalized, verified M1 artifacts."""

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
        for row in current:
            try:
                verified[row["run_id"]] = validate_run_artifacts(row)
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
        combinations: list[dict[str, Any]] = []
        passed: list[dict[str, Any]] = []
        missing: list[str] = []
        for beta in (0.9, 1.1, 1.3):
            for kappa in (None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8):
                cases = [
                    case for case in expected_cases
                    if case.beta == beta and case.kappa == kappa
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
                substantive_count = sum(
                    (result.get("science") or {}).get("substantive_activation") is True
                    for result in records
                )
                gate = all_optimal and substantive_count >= 2
                item = {
                    "beta": beta,
                    "kappa": kappa,
                    "completed_seed_count": len(records),
                    "optimal_seed_count": sum(
                        result.get("status") == "optimal" for result in records
                    ),
                    "substantive_activation_seed_count": substantive_count,
                    "gate_passed": gate,
                    "run_ids": [result["run_id"] for result in records],
                }
                combinations.append(item)
                if gate:
                    passed.append(item)
        verified_primary_ids = {
            row["run_id"]
            for row in primaries
            if row["run_id"] in verified
        }
        all_primary_finalized = (
            len(verified_primary_ids) == 63
            and not missing
            and not duplicates
            and not invalid_primary
        )
        all_primary_optimal = all_primary_finalized and all(
            result.get("status") == "optimal"
            for run_id, result in verified.items()
            if run_id in verified_primary_ids
        )
        gate_passed = all_primary_optimal and bool(passed)
        payload = {
            "status": (
                "passed" if gate_passed else "completed_no_activation"
                if all_primary_optimal else "completed_with_failures"
                if all_primary_finalized else "incomplete"
            ),
            "fingerprints": dict(fingerprints),
            "required_primary_run_count": 63,
            "verified_primary_run_count": len(verified_primary_ids),
            "missing_case_ids": sorted(set(missing)),
            "invalid_primary_run_ids": sorted(invalid_primary),
            "invalid_diagnostic_run_ids": sorted(invalid_diagnostics),
            "duplicate_case_ids": duplicates,
            "diagnostic_run_ids": diagnostics,
            "combinations": combinations,
            "passed_combinations": passed,
            "development_activation_gate_passed": gate_passed,
            "formal_extension_authorized": False,
            "stop_reason": (
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
    base = output_root / "development"
    directory = base / "runs" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError(f"M1 development run_id is immutable: {run_id}")
        started = perf_counter()
        stages: list[dict[str, Any]] = []
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
            nonlocal active_stage_index, stage_started, peak_memory_mb
            now = perf_counter()
            if active_stage_index is not None:
                stages[active_stage_index]["status"] = "completed"
                stages[active_stage_index]["runtime_seconds"] = now - stage_started
            stage_started = now
            peak_memory_mb = max(
                peak_memory_mb,
                psutil.Process().memory_info().rss / (1024.0 * 1024.0),
            )
            stages.append({"stage": stage, "status": "running", **details})
            active_stage_index = len(stages) - 1
            save("running", stage)

        save("running", "initialization")
        matrix = load_phase6_matrix(matrix_path)
        try:
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
        except Exception as exc:
            status = "timeout" if isinstance(exc, TimeoutError) else "stage_failure"
            failure = {
                "stage": stages[-1]["stage"] if stages else "initialization",
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
                "fixed_autonomous_reserve",
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
            "fingerprints": dict(fingerprints),
            "git_sha": source["commit_sha"],
            "git_tree_sha": source["tree_sha"],
            "finished_at_utc": utc_now(),
        }
        # Finalize compact progress before hashing terminal artifacts.
        save(status, None)
        result_path = directory / "result.json"
        atomic_write_json(result_path, result)
        manifest_path = directory / "manifest.json"
        atomic_write_json(
            manifest_path,
            {
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
                "runtime_context": capture_runtime_context(
                    solver_preference=("gurobi",),
                    project_root=project_root,
                    solver_threads=1,
                ),
            },
        )
        row = {
            "run_id": run_id,
            "parent_run_id": parent_run_id or "",
            "case_id": case.case_id,
            "tier_id": case.tier_id,
            "seed": case.seed,
            "beta": case.beta,
            "kappa": "unbounded" if case.kappa is None else case.kappa,
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
        upsert_development_registry(output_root, row)
        projection = update_development_projection(
            output_root=output_root,
            config=config,
            fingerprints=fingerprints,
        )
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
        raise ValueError(f"unknown M1 development cases: {sorted(unknown)}")
    selected = [case for case in all_cases if case.case_id in requested]
    output_root = project_root / M1_OUTPUT_ROOT
    matrix_path = project_root / config["base_model"]["matrix_path"]
    results = []
    with exclusive_file_lock(
        output_root / "development" / ".serial-execution.lock",
        timeout_seconds=1.0,
    ):
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

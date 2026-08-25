"""Safe orchestration for the frozen M2 algorithm-performance experiment."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
from statistics import median
import subprocess
import sys
from time import perf_counter, sleep
from typing import Any, Callable, Mapping, Sequence

import psutil
import yaml

from .model_common import validate_gurobi_runtime
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_json, read_lf_bytes
from .phase6_locking import exclusive_file_lock
from .reproducibility import sha256_file, validate_execution_source
from .phase6_m2 import M2_E3_COMPONENT_FILES, M2_FAMILY_COMPONENT_FILES
from .phase6_m2_formal_extension import _confirmation_config, _validate_formal_baseline_before_generation
from .phase6_protocol import load_phase6_matrix
from .phase6_runner import _build_transferred_state


NAMESPACE = "phase6_m2_algorithm_performance_v1_0"
DESIGN_STATUS = "frozen_for_runner_implementation"
APPROVAL_PENDING_STATUS = "runner_frozen_pilot_pending_authorization"
APPROVAL_READY_STATUS = "frozen_for_pilot_execution"
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9._-]+")
LIFECYCLE_FIELDS = {"status", "version", "designed_on", "execution_boundaries"}
ORCHESTRATOR_FILES = (
    "src/phase6_m2_algorithm_performance.py",
    "src/phase6_m2_algorithm_performance_worker.py",
    "src/run_phase6_m2_algorithm_performance.py",
    "src/phase6_m2_algorithm_performance_status.py",
    "configs/phase6_m2_algorithm_performance_design_v1_0.yaml",
    "configs/phase6_m2_algorithm_performance_runner_v1_0.yaml",
)
E3_FILES = tuple(dict.fromkeys((*M2_E3_COMPONENT_FILES, *ORCHESTRATOR_FILES)))
FAMILY_FILES = tuple(dict.fromkeys((*M2_FAMILY_COMPONENT_FILES, *ORCHESTRATOR_FILES)))


@dataclass(frozen=True)
class PerformanceCase:
    case_id: str
    seed: int
    profile_id: str


WorkerExecutor = Callable[[dict[str, Any], float, Path], dict[str, Any]]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return payload


def _canonical_sha(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _component_sha(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def algorithm_performance_fingerprints(
    root: Path, design_path: Path, runner_path: Path,
) -> dict[str, str]:
    design = _load_yaml(design_path)
    scientific = {key: value for key, value in design.items() if key not in LIFECYCLE_FIELDS}
    return {
        "scientific_config_sha256": _canonical_sha(scientific),
        "e3_component_sha256": _component_sha(root, E3_FILES),
        "family_component_sha256": _component_sha(root, FAMILY_FILES),
        "runner_config_sha256": sha256_file(runner_path),
        "environment_sha256": environment_sha256(validate_locked_environment(root)),
        "algorithm_performance_orchestrator_sha256": _component_sha(root, ORCHESTRATOR_FILES),
    }


def build_pilot_cases(design: Mapping[str, Any]) -> tuple[PerformanceCase, ...]:
    seeds = tuple(int(value) for value in design["seed_protocol"]["pilot_seeds"])
    profiles = tuple(design["profiles"])
    cases = tuple(
        PerformanceCase(
            case_id=f"M2AP2_pilot_seed{seed}_profile{profile}",
            seed=seed, profile_id=str(profile),
        )
        for seed in seeds for profile in profiles
    )
    if seeds != (2026091001, 2026091002, 2026091003) or profiles != ("C0", "T03"):
        raise ValueError("pilot seed/profile matrix differs from the reviewed design")
    if len(cases) != 6:
        raise ValueError("M2 algorithm pilot must contain six primary sequences")
    return cases


def validate_static_freeze(root: Path, runner_path: Path, approval_path: Path) -> dict[str, Any]:
    runner = _load_yaml(runner_path)
    approval = _load_yaml(approval_path)
    design_path = root / str(runner["design_config"])
    design = _load_yaml(design_path)
    if runner.get("namespace") != NAMESPACE or approval.get("runner_namespace") != NAMESPACE:
        raise RuntimeError("M2 algorithm-performance namespace mismatch")
    if design.get("status") != DESIGN_STATUS:
        raise RuntimeError("M2 algorithm-performance design is not frozen for runner implementation")
    if design.get("execution_boundaries", {}).get("formal_authorized") is not False:
        raise RuntimeError("formal algorithm performance must remain unauthorized")
    if tuple(float(v) for v in design["budget_sequence"]["betas"]) != (1.1, 1.3):
        raise RuntimeError("budget sequence changed")
    if tuple(float(v) for v in design["budget_sequence"]["budgets"]) != (
        2571.372016574617, 3038.894201406366,
    ):
        raise RuntimeError("budget values changed")
    if design["pilot_protocol"]["planned_algorithm_solve_count"] != 36:
        raise RuntimeError("pilot workload is not 36 solves")
    if design["formal_matrix"]["planned_algorithm_execution_count"] != 240:
        raise RuntimeError("formal workload is not 240 executions")
    expected_solver = {
        "preference": ["gurobi"], "interface": "gurobi_direct",
        "optimizer_version": "13.0.2", "gurobipy_version": "13.0.2",
        "threads": 1, "feasibility_tolerance": 1.0e-7,
        "optimality_tolerance": 1.0e-7, "call_time_limit_seconds": 120,
    }
    if runner.get("solver") != expected_solver:
        raise RuntimeError("solver configuration changed")
    if runner.get("limits") != {"worker_wall_seconds": 180, "threads": 1}:
        raise RuntimeError("runner limits changed")
    if runner["execution"].get("formal_authorized") is not False:
        raise RuntimeError("runner may not authorize formal execution")
    return {
        "runner": runner, "approval": approval, "design": design,
        "design_path": design_path, "cases": build_pilot_cases(design),
    }


def validate_preflight(
    root: Path, runner_path: Path, approval_path: Path, *, require_authorization: bool,
) -> dict[str, Any]:
    context = validate_static_freeze(root, runner_path, approval_path)
    runner, approval = context["runner"], context["approval"]
    if require_authorization:
        if approval.get("status") != APPROVAL_READY_STATUS or approval.get("pilot_authorized") is not True:
            raise RuntimeError("M2 algorithm-performance pilot is not authorized")
    else:
        if approval.get("status") not in {APPROVAL_PENDING_STATUS, APPROVAL_READY_STATUS}:
            raise RuntimeError("unexpected pilot approval lifecycle status")
    false_scope = (
        "formal_authorized", "M0_E3_additional_runs_authorized",
        "M2_mechanism_additional_runs_authorized", "M2_OOS_additional_runs_authorized",
        "M2_1_additional_runs_authorized",
    )
    if any(approval.get(field) is not False for field in false_scope):
        raise RuntimeError("pilot approval exceeds the reviewed scope")
    matrix_path = root / str(runner["base_matrix"])
    matrix = load_phase6_matrix(matrix_path)
    confirmation = _confirmation_config(root)
    formal_like = {
        "scientific_model": context["design"]["scientific_model"],
        "profiles": context["design"]["profiles"],
        "mechanism_experiment": {
            "primary_track": {"beta": 1.1, "budget": 2571.372016574617},
            "secondary_track": {"beta": 1.3, "budget": 3038.894201406366},
        },
    }
    # Both budgets and all six capacities are recomputed before the first RNG call.
    for beta in (1.1, 1.3):
        _validate_formal_baseline_before_generation(
            matrix, formal_like, confirmation, beta=beta, scenario_count=50,
        )
    required = (
        matrix_path, context["design_path"], runner_path, approval_path,
        *(root / relative for relative in E3_FILES),
    )
    validate_execution_source(root, required_tracked_paths=required)
    actual = algorithm_performance_fingerprints(root, context["design_path"], runner_path)
    approved = approval.get("approved_fingerprints", {})
    if require_authorization and approved != actual:
        raise RuntimeError("approved M2 algorithm-performance fingerprints do not match")
    artifact_paths = {
        "runner_config": runner_path,
        "orchestrator_module": root / "src/phase6_m2_algorithm_performance.py",
        "worker_module": root / "src/phase6_m2_algorithm_performance_worker.py",
        "cli": root / "src/run_phase6_m2_algorithm_performance.py",
        "status_module": root / "src/phase6_m2_algorithm_performance_status.py",
    }
    if require_authorization:
        for name, path in artifact_paths.items():
            if approval.get("artifact_sha256", {}).get(name) != sha256_file(path):
                raise RuntimeError(f"approved artifact differs: {name}")
        validate_gurobi_runtime()
    context.update(matrix=matrix, fingerprints=actual, matrix_path=matrix_path)
    return context


def _worker_executor(request: dict[str, Any], timeout_seconds: float, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    suffix = f"b{request['budget_index']}_{request['algorithm']}_r{request['repetition']:02d}"
    request_path = directory / f"{suffix}_request.json"
    result_path = directory / f"{suffix}_result.json"
    atomic_write_json(request_path, request)
    env = os.environ.copy()
    env.update({name: "1" for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")})
    command = [sys.executable, "-m", "src.phase6_m2_algorithm_performance_worker", "--request", str(request_path), "--result", str(result_path)]
    started = perf_counter()
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    monitored = psutil.Process(process.pid)
    peak = 0
    timed_out = False
    while process.poll() is None:
        if perf_counter() - started > timeout_seconds:
            timed_out = True
            try:
                children = monitored.children(recursive=True)
                for child in reversed(children): child.kill()
                monitored.kill(); psutil.wait_procs([*children, monitored], timeout=5)
            except (psutil.Error, OSError):
                process.kill()
            break
        try:
            peak = max(peak, sum(p.memory_info().rss for p in (monitored, *monitored.children(recursive=True)) if p.is_running()))
        except (psutil.Error, OSError):
            pass
        sleep(0.05)
    stdout, stderr = process.communicate()
    elapsed = perf_counter() - started
    if timed_out:
        payload = {"status": "timeout", "solver_status": "external_wall_timeout", "failure": {"stage": "worker_watchdog", "message": f"worker exceeded {timeout_seconds}s"}}
    elif result_path.is_file():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        payload = {"status": "worker_process_error", "solver_status": None, "failure": {"stage": "worker_process", "message": "worker returned no result"}}
    payload.update(subprocess_wall_seconds=elapsed, sampled_peak_RSS_MiB=peak / (1024.0 ** 2), return_code=process.returncode, stdout=stdout, stderr=stderr)
    atomic_write_json(result_path, payload)
    return payload


def _objective_tolerance(values: Sequence[float], ccg: Mapping[str, Any]) -> float:
    return float(ccg["absolute_tolerance"]) + float(ccg["relative_tolerance"]) * max(1.0, *(abs(v) for v in values))


def _manifest(result_path: Path, result: Mapping[str, Any], fingerprints: Mapping[str, str]) -> dict[str, Any]:
    return {
        "artifact_state": "finalized", "run_id": result["run_id"],
        "status": result["status"], "result_sha256": sha256_file(result_path),
        "fingerprints": dict(fingerprints), "finalized_at_utc": utc_now(),
    }


def run_sequence(
    *, root: Path, runner: Mapping[str, Any], design: Mapping[str, Any],
    fingerprints: Mapping[str, str], case: PerformanceCase, run_id: str,
    execution_root: Path, worker_executor: WorkerExecutor = _worker_executor,
) -> dict[str, Any]:
    if SAFE_RUN_ID.fullmatch(run_id) is None or ".." in run_id:
        raise ValueError("unsafe run_id")
    run_dir = (execution_root / "runs" / run_id).resolve()
    if execution_root.resolve() not in run_dir.parents:
        raise ValueError("run path escapes controlled output root")
    if run_dir.exists():
        raise FileExistsError("run_id is immutable and already exists")
    run_dir.mkdir(parents=True)
    result_path, manifest_path = run_dir / "result.json", run_dir / "manifest.json"
    status_path = run_dir / "status_summary.json"
    started = utc_now()
    comparisons: list[dict[str, Any]] = []
    previous_state: dict[str, Any] | None = None
    try:
        for budget_index, (beta, budget) in enumerate(zip(design["budget_sequence"]["betas"], design["budget_sequence"]["budgets"], strict=True)):
            order = ("extensive", "cold", "warm") if budget_index == 0 else ("extensive", "warm", "cold")
            rows: dict[str, dict[str, Any]] = {}
            for algorithm in order:
                request = {
                    "project_root": str(root), "matrix_path": str(root / runner["base_matrix"]),
                    "design_path": str(root / runner["design_config"]),
                    "algorithm": algorithm, "budget_index": budget_index,
                    "beta": float(beta), "budget": float(budget), "seed": case.seed,
                    "profile_id": case.profile_id, "scenario_count": 50, "repetition": 1,
                    "previous_state": previous_state if algorithm == "warm" else None,
                    "solver": runner["solver"], "ccg": runner["ccg"],
                }
                row = worker_executor(request, float(runner["limits"]["worker_wall_seconds"]), run_dir / "workers")
                rows[algorithm] = row
                if row.get("status") != "optimal":
                    native = str(row.get("solver_status") or row.get("status"))
                    terminal = "timeout" if native in {"time_limit", "master_time_limit", "external_wall_timeout"} or row.get("status") == "timeout" else "stage_failure"
                    raise RuntimeError(json.dumps({"terminal": terminal, "algorithm": algorithm, "native_status": native, "failure": row.get("failure")}, ensure_ascii=False))
                if algorithm == "warm":
                    previous_state = _build_transferred_state(
                        row, previous_state, budget=float(budget),
                        tolerance=float(runner["ccg"]["active_scenario_tolerance"]),
                    )
            objectives = [float(rows[name]["objective"]) for name in ("extensive", "cold", "warm")]
            tolerance = _objective_tolerance(objectives, runner["ccg"])
            maximum_difference = max(objectives) - min(objectives)
            if maximum_difference > tolerance:
                raise RuntimeError("objective_consistency_failure")
            identity = {rows[name]["joint_scenario_set_sha256"] for name in rows}
            if len(identity) != 1:
                raise RuntimeError("algorithm joint scenario identity mismatch")
            comparisons.append({
                "budget_index": budget_index, "beta": float(beta), "budget": float(budget),
                "execution_order": list(order), "status": "optimal", "methods": rows,
                "objective_tolerance": tolerance,
                "maximum_objective_difference": maximum_difference,
                "transferred_state": previous_state,
            })
            atomic_write_json(status_path, {"status": "running", "run_id": run_id, "completed_budget_count": len(comparisons), "updated_at_utc": utc_now()})
        result = {
            "artifact_state": "finalized", "status": "optimal",
            "run_id": run_id, "parent_run_id": None, "case_id": case.case_id,
            "tier_id": "M2AP2", "execution_mode": "pilot", "seed": case.seed,
            "profile_id": case.profile_id, "planned_algorithm_solve_count": 6,
            "completed_algorithm_solve_count": 6, "comparisons": comparisons,
            "fingerprints": dict(fingerprints), "started_at_utc": started,
            "completed_at_utc": utc_now(),
        }
        atomic_write_json(result_path, result)
        manifest = _manifest(result_path, result, fingerprints)
        atomic_write_json(manifest_path, manifest)
        atomic_write_json(status_path, {"status": "optimal", "run_id": run_id, "completed_budget_count": 2, "completed_algorithm_solve_count": 6, "updated_at_utc": utc_now()})
        return result
    except BaseException as exc:
        message = str(exc)
        terminal = "interrupted" if isinstance(exc, KeyboardInterrupt) else ("timeout" if '"terminal": "timeout"' in message else "runner_exception")
        failure = {"artifact_state": "finalized", "status": terminal, "run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "comparisons": comparisons, "exception_type": type(exc).__name__, "message": message[:4096], "fingerprints": dict(fingerprints), "completed_at_utc": utc_now()}
        atomic_write_json(result_path, failure)
        atomic_write_json(manifest_path, _manifest(result_path, failure, fingerprints))
        atomic_write_json(status_path, {"status": terminal, "run_id": run_id, "message": message[:4096], "updated_at_utc": utc_now()})
        raise


def _registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file(): return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("runs", []))


def update_projection(execution_root: Path, cases: Sequence[PerformanceCase], fingerprints: Mapping[str, str]) -> dict[str, Any]:
    registry_path = execution_root / "run_registry.json"
    rows = _registry(registry_path)
    expected = {case.case_id: case for case in cases}
    primary = {case_id: [row for row in rows if row.get("case_id") == case_id and not row.get("parent_run_id")] for case_id in expected}
    missing = [key for key, values in primary.items() if not values]
    duplicates = [key for key, values in primary.items() if len(values) > 1]
    failed, invalid, results = [], [], []
    for case_id, values in primary.items():
        if len(values) != 1: continue
        row = values[0]
        if row.get("status") != "optimal": failed.append(row.get("run_id")); continue
        try:
            result_path = (execution_root / "runs" / row["run_id"] / "result.json").resolve()
            manifest_path = result_path.with_name("manifest.json")
            if execution_root.resolve() not in result_path.parents:
                raise ValueError("artifact path escapes output root")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            if result.get("fingerprints") != dict(fingerprints) or result.get("case_id") != case_id:
                raise ValueError("result identity or fingerprints mismatch")
            if manifest.get("result_sha256") != sha256_file(result_path):
                raise ValueError("result hash mismatch")
            if len(result.get("comparisons", [])) != 2 or result.get("completed_algorithm_solve_count") != 6:
                raise ValueError("pilot solve count mismatch")
            results.append(result)
        except Exception as exc:
            invalid.append({"case_id": case_id, "message": f"{type(exc).__name__}: {exc}"})
    crn_mismatches: list[dict[str, Any]] = []
    for seed in sorted({case.seed for case in cases}):
        paired = [result for result in results if int(result["seed"]) == seed]
        if len(paired) != 2: continue
        for budget_index in (0, 1):
            components = [row["comparisons"][budget_index]["methods"]["cold"]["component_set_sha256"] for row in paired]
            for field in ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256", "scenario_order_sha256"):
                if len({value[field] for value in components}) != 1:
                    crn_mismatches.append({"seed": seed, "budget_index": budget_index, "field": field})
    diagnostics = [row["run_id"] for row in rows if row.get("parent_run_id")]
    gate = not (missing or duplicates or failed or invalid or diagnostics or crn_mismatches) and len(results) == 6
    payload = {
        "status": "passed" if gate else "incomplete",
        "required_primary_sequence_count": 6, "completed_primary_sequence_count": len(results),
        "required_budget_pair_count": 12, "completed_budget_pair_count": sum(len(row["comparisons"]) for row in results),
        "required_algorithm_solve_count": 36, "completed_algorithm_solve_count": sum(row["completed_algorithm_solve_count"] for row in results),
        "missing_case_ids": missing, "duplicate_case_ids": duplicates,
        "failed_primary_run_ids": failed, "invalid_primary_runs": invalid,
        "diagnostic_run_ids": diagnostics, "common_random_number_mismatches": crn_mismatches,
        "fingerprints": dict(fingerprints), "pilot_compute_gate_passed": gate,
        "formal_authorized": False, "updated_at_utc": utc_now(),
    }
    atomic_write_json(execution_root / "pilot_projection.json", payload)
    atomic_write_json(execution_root / "status_summary.json", payload)
    return payload


def run_pilot_batch(
    *, root: Path, runner_path: Path, approval_path: Path, authorize: bool,
    run_id_prefix: str, worker_executor: WorkerExecutor = _worker_executor,
) -> dict[str, Any]:
    if not authorize:
        raise RuntimeError("explicit --authorize-m2-algorithm-performance-pilot is required")
    if SAFE_RUN_ID.fullmatch(run_id_prefix or "") is None or ".." in run_id_prefix:
        raise ValueError("unsafe run_id_prefix")
    context = validate_preflight(root, runner_path, approval_path, require_authorization=True)
    output_root = (root / context["runner"]["output_root"]).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError("M2 algorithm-performance output root must be empty")
    execution_root = output_root / context["runner"]["pilot_subdirectory"]
    execution_root.mkdir(parents=True)
    registry_path = execution_root / "run_registry.json"
    with exclusive_file_lock(output_root / ".batch.lock", timeout_seconds=0.0):
        for case in context["cases"]:
            run_id = f"{run_id_prefix}_{case.case_id}"
            try:
                result = run_sequence(root=root, runner=context["runner"], design=context["design"], fingerprints=context["fingerprints"], case=case, run_id=run_id, execution_root=execution_root, worker_executor=worker_executor)
                rows = _registry(registry_path)
                rows.append({"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "status": result["status"]})
                atomic_write_json(registry_path, {"namespace": NAMESPACE, "runs": rows})
                projection = update_projection(execution_root, context["cases"], context["fingerprints"])
                if result["status"] != "optimal": return projection
            except BaseException:
                rows = _registry(registry_path)
                status = json.loads((execution_root / "runs" / run_id / "status_summary.json").read_text(encoding="utf-8"))["status"]
                rows.append({"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "status": status})
                atomic_write_json(registry_path, {"namespace": NAMESPACE, "runs": rows})
                update_projection(execution_root, context["cases"], context["fingerprints"])
                raise
        return update_projection(execution_root, context["cases"], context["fingerprints"])


def read_status(path: Path, *, maximum_bytes: int = 16384) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_started", "path": str(path)}
    if path.stat().st_size > maximum_bytes:
        raise ValueError("status file exceeds bounded status-tool limit")
    return json.loads(path.read_text(encoding="utf-8"))

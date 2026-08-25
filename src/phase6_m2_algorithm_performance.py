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


NAMESPACE = "phase6_m2_algorithm_performance_v1_1"
DESIGN_STATUS = "frozen_for_runner_implementation"
APPROVAL_PENDING_STATUS = "runner_frozen_pilot_pending_authorization"
APPROVAL_READY_STATUS = "frozen_for_pilot_execution"
SAFE_RUN_ID = re.compile(r"[A-Za-z0-9._-]+")
M2_OBJECTIVE_ABSOLUTE_TOLERANCE = 1.0e-5
M2_OBJECTIVE_RELATIVE_TOLERANCE = 1.0e-7
LIFECYCLE_FIELDS = {"status", "version", "designed_on", "execution_boundaries"}
ORCHESTRATOR_FILES = (
    "src/phase6_m2_algorithm_performance.py",
    "src/phase6_m2_algorithm_performance_worker.py",
    "src/run_phase6_m2_algorithm_performance.py",
    "src/phase6_m2_algorithm_performance_status.py",
    "configs/phase6_m2_algorithm_performance_design_v1_0.yaml",
    "configs/phase6_m2_algorithm_performance_runner_v1_1.yaml",
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


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=root, text=True).strip()


def _validate_synchronized_main(
    root: Path, *, reviewed_runner_merge_commit: str,
) -> dict[str, str]:
    if re.fullmatch(r"[0-9a-f]{40}", reviewed_runner_merge_commit or "") is None:
        raise RuntimeError("approved reviewed runner commit is missing or invalid")
    branch = _git(root, "branch", "--show-current")
    if branch != "main":
        raise RuntimeError("M2 algorithm-performance execution requires main")
    remote = _git(root, "config", "--get", "branch.main.remote")
    merge = _git(root, "config", "--get", "branch.main.merge")
    if remote != "origin" or merge != "refs/heads/main":
        raise RuntimeError("local main must track origin/main")
    head = _git(root, "rev-parse", "HEAD")
    remote_main = _git(root, "rev-parse", "refs/remotes/origin/main")
    if head != remote_main:
        raise RuntimeError("main must be synchronized with the fetched origin/main")
    try:
        _git(root, "merge-base", "--is-ancestor", reviewed_runner_merge_commit, head)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("reviewed runner commit is not an ancestor of execution HEAD") from exc
    tree = _git(root, "rev-parse", "HEAD^{tree}")
    return {
        "branch": branch, "upstream_remote": remote,
        "upstream_merge": merge, "head": head,
        "remote_main": remote_main, "tree": tree,
        "reviewed_runner_merge_commit": reviewed_runner_merge_commit,
    }


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
    if runner.get("objective_consistency") != {
        "source": "frozen_M2_scientific_objective_consistency_tolerance",
        "absolute_tolerance": 1.0e-5,
        "relative_tolerance": 1.0e-7,
    }:
        raise RuntimeError("frozen M2 objective-consistency tolerance changed")
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
    synchronized_main = None
    if require_authorization:
        synchronized_main = _validate_synchronized_main(
            root,
            reviewed_runner_merge_commit=str(
                approval.get("reviewed_runner_merge_commit") or ""
            ),
        )
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
    context.update(
        matrix=matrix, fingerprints=actual, matrix_path=matrix_path,
        synchronized_main=synchronized_main,
    )
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


def _objective_tolerance(values: Sequence[float], consistency: Mapping[str, Any]) -> float:
    numeric = tuple(float(value) for value in values)
    absolute = float(consistency["absolute_tolerance"])
    relative = float(consistency["relative_tolerance"])
    if not numeric or not all(math.isfinite(value) for value in numeric):
        raise ValueError("objective values must be finite")
    if not all(math.isfinite(value) and value >= 0.0 for value in (absolute, relative)):
        raise ValueError("objective-consistency tolerances must be finite and nonnegative")
    return absolute + relative * max(1.0, *(abs(value) for value in numeric))


def _validate_worker_evidence(row: Mapping[str, Any], *, expected_scenarios: int) -> None:
    objective = float(row["objective"])
    wall = float(row["subprocess_wall_seconds"])
    memory = float(row["sampled_peak_RSS_MiB"])
    if not math.isfinite(objective):
        raise ValueError("worker objective is not finite")
    if not math.isfinite(wall) or wall <= 0.0:
        raise ValueError("worker wall time must be finite and positive")
    if not math.isfinite(memory) or memory < 0.0:
        raise ValueError("worker peak RSS must be finite and nonnegative")
    if int(row.get("scenario_count", -1)) != expected_scenarios:
        raise ValueError("worker scenario count differs from frozen pilot")
    if row["algorithm"] in {"cold", "warm"}:
        exact = row.get("ccg_result", {}).get("exact_scenario_costs", {})
        if len(exact) != expected_scenarios:
            raise ValueError("C&CG exact oracle does not cover all pilot scenarios")
        if not all(math.isfinite(float(value)) for value in exact.values()):
            raise ValueError("C&CG exact oracle contains non-finite costs")
        if _canonical_sha(list(exact)) != row["component_set_sha256"]["scenario_order_sha256"]:
            raise ValueError("C&CG exact oracle scenario identities differ from scenario order")


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
    execution_identity: Mapping[str, str] | None = None,
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
    execution_identity = dict(execution_identity or {
        "branch": "test", "upstream_remote": "test", "upstream_merge": "test",
        "head": "0" * 40, "remote_main": "0" * 40, "tree": "0" * 40,
        "reviewed_runner_merge_commit": "0" * 40,
    })
    comparisons: list[dict[str, Any]] = []
    previous_state: dict[str, Any] | None = None
    prior_components: dict[str, str] | None = None
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
                    "objective_consistency": runner["objective_consistency"],
                }
                row = worker_executor(request, float(runner["limits"]["worker_wall_seconds"]), run_dir / "workers")
                rows[algorithm] = row
                if row.get("status") != "optimal":
                    native = str(row.get("solver_status") or row.get("status"))
                    terminal = "timeout" if native in {"time_limit", "master_time_limit", "external_wall_timeout"} or row.get("status") == "timeout" else "stage_failure"
                    raise RuntimeError(json.dumps({"terminal": terminal, "algorithm": algorithm, "native_status": native, "failure": row.get("failure")}, ensure_ascii=False))
                _validate_worker_evidence(row, expected_scenarios=50)
                if algorithm == "warm":
                    previous_state = _build_transferred_state(
                        row, previous_state, budget=float(budget),
                        tolerance=float(runner["ccg"]["active_scenario_tolerance"]),
                    )
            objectives = [float(rows[name]["objective"]) for name in ("extensive", "cold", "warm")]
            tolerance = _objective_tolerance(objectives, runner["objective_consistency"])
            maximum_difference = max(objectives) - min(objectives)
            if not math.isfinite(maximum_difference) or maximum_difference < 0.0 or maximum_difference > tolerance:
                raise RuntimeError("objective_consistency_failure")
            identity = {rows[name]["joint_scenario_set_sha256"] for name in rows}
            if len(identity) != 1:
                raise RuntimeError("algorithm joint scenario identity mismatch")
            component_identities = [rows[name]["component_set_sha256"] for name in rows]
            if any(value != component_identities[0] for value in component_identities[1:]):
                raise RuntimeError("algorithm component scenario identity mismatch")
            if prior_components is not None and component_identities[0] != prior_components:
                raise RuntimeError("budget regeneration changed scenario components")
            transfer_input = None if budget_index == 0 else comparisons[0]["transferred_state"]
            warm = rows["warm"]
            expected_source_sha = None if transfer_input is None else _canonical_sha(transfer_input)
            if warm.get("transfer_source_state_sha256") != expected_source_sha:
                raise RuntimeError("warm transfer source identity mismatch")
            if budget_index == 1 and not math.isclose(
                float(warm.get("transfer_source_budget", math.nan)),
                float(design["budget_sequence"]["budgets"][0]),
                rel_tol=0.0, abs_tol=1.0e-9,
            ):
                raise RuntimeError("warm transfer source budget mismatch")
            prior_components = dict(component_identities[0])
            comparisons.append({
                "budget_index": budget_index, "beta": float(beta), "budget": float(budget),
                "execution_order": list(order), "status": "optimal", "methods": rows,
                "objective_tolerance": tolerance,
                "maximum_objective_difference": maximum_difference,
                "transfer_input_state": transfer_input,
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
            "execution_identity": execution_identity,
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
        failure = {"artifact_state": "finalized", "status": terminal, "run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "comparisons": comparisons, "exception_type": type(exc).__name__, "message": message[:4096], "fingerprints": dict(fingerprints), "execution_identity": execution_identity, "completed_at_utc": utc_now()}
        atomic_write_json(result_path, failure)
        atomic_write_json(manifest_path, _manifest(result_path, failure, fingerprints))
        atomic_write_json(status_path, {"status": terminal, "run_id": run_id, "message": message[:4096], "updated_at_utc": utc_now()})
        raise


def _registry(path: Path) -> list[dict[str, Any]]:
    if not path.is_file(): return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload.get("runs", []))


def _validate_pilot_result(
    result: Mapping[str, Any], case: PerformanceCase,
    fingerprints: Mapping[str, str], expected_execution_identity: Mapping[str, str] | None,
) -> dict[str, Any]:
    if result.get("fingerprints") != dict(fingerprints):
        raise ValueError("result fingerprints mismatch")
    if expected_execution_identity is not None and result.get("execution_identity") != dict(expected_execution_identity):
        raise ValueError("result execution Git identity mismatch")
    if (
        result.get("case_id") != case.case_id
        or int(result.get("seed", -1)) != case.seed
        or result.get("profile_id") != case.profile_id
        or result.get("tier_id") != "M2AP2"
        or result.get("execution_mode") != "pilot"
    ):
        raise ValueError("result case identity mismatch")
    comparisons = result.get("comparisons", [])
    if len(comparisons) != 2:
        raise ValueError("pilot result must contain two budget comparisons")
    solve_count = 0
    all_walls: list[float] = []
    ccg_walls: list[float] = []
    all_memory: list[float] = []
    prior_components: dict[str, str] | None = None
    prior_state: dict[str, Any] | None = None
    for budget_index, comparison in enumerate(comparisons):
        expected_order = (
            ["extensive", "cold", "warm"]
            if budget_index == 0 else ["extensive", "warm", "cold"]
        )
        if (
            comparison.get("budget_index") != budget_index
            or not math.isclose(float(comparison.get("beta", math.nan)), (1.1, 1.3)[budget_index], abs_tol=1.0e-12)
            or not math.isclose(float(comparison.get("budget", math.nan)), (2571.372016574617, 3038.894201406366)[budget_index], abs_tol=1.0e-9)
            or comparison.get("execution_order") != expected_order
            or comparison.get("status") != "optimal"
        ):
            raise ValueError("budget comparison identity or order mismatch")
        methods = comparison.get("methods", {})
        if set(methods) != {"extensive", "cold", "warm"}:
            raise ValueError("budget comparison must contain exactly three methods")
        objectives: list[float] = []
        component_rows: list[dict[str, str]] = []
        joint: set[str] = set()
        for method in ("extensive", "cold", "warm"):
            row = methods[method]
            if row.get("status") != "optimal" or row.get("algorithm") != method:
                raise ValueError("method identity or status mismatch")
            _validate_worker_evidence(row, expected_scenarios=50)
            objective = float(row["objective"])
            objectives.append(objective)
            all_walls.append(float(row["subprocess_wall_seconds"]))
            all_memory.append(float(row["sampled_peak_RSS_MiB"]))
            if method in {"cold", "warm"}:
                ccg_walls.append(float(row["subprocess_wall_seconds"]))
            joint.add(str(row["joint_scenario_set_sha256"]))
            components = row.get("component_set_sha256", {})
            required_components = {
                "latent_draw_sha256", "demand_sha256", "fulfillment_sha256",
                "emergency_price_sha256", "emergency_supply_sha256",
                "scenario_order_sha256",
            }
            if set(components) != required_components or any(
                SAFE_RUN_ID.fullmatch(str(value)) is None or len(str(value)) != 64
                for value in components.values()
            ):
                raise ValueError("method component identities are incomplete")
            component_rows.append(dict(components))
            solve_count += 1
        if len(joint) != 1 or any(row != component_rows[0] for row in component_rows[1:]):
            raise ValueError("methods do not use an identical joint scenario set")
        if prior_components is not None and component_rows[0] != prior_components:
            raise ValueError("same sequence regenerated different scenarios across budgets")
        tolerance = _objective_tolerance(
            objectives,
            {
                "absolute_tolerance": M2_OBJECTIVE_ABSOLUTE_TOLERANCE,
                "relative_tolerance": M2_OBJECTIVE_RELATIVE_TOLERANCE,
            },
        )
        difference = max(objectives) - min(objectives)
        recorded_tolerance = float(comparison.get("objective_tolerance", math.nan))
        recorded_difference = float(comparison.get("maximum_objective_difference", math.nan))
        if not all(math.isfinite(value) and value >= 0.0 for value in (difference, recorded_difference, recorded_tolerance)):
            raise ValueError("objective consistency evidence must be finite and nonnegative")
        if not math.isclose(recorded_tolerance, tolerance, rel_tol=0.0, abs_tol=1.0e-12):
            raise ValueError("recorded objective tolerance is not the frozen M2 tolerance")
        if not math.isclose(recorded_difference, difference, rel_tol=0.0, abs_tol=1.0e-12) or difference > tolerance:
            raise ValueError("three-method objective consistency gate failed")
        warm = methods["warm"]
        expected_source_sha = None if prior_state is None else _canonical_sha(prior_state)
        if warm.get("transfer_source_state_sha256") != expected_source_sha:
            raise ValueError("warm result is not bound to the prior budget state")
        transfer_count = int(warm.get("transferred_exact_scenario_count", -1))
        transfer_names = list(warm.get("transferred_exact_scenarios", []))
        reuse_rate = float(warm.get("transferred_scenario_reuse_rate", math.nan))
        if transfer_count != len(transfer_names) or transfer_count < 0:
            raise ValueError("transferred scenario count mismatch")
        if not math.isfinite(reuse_rate) or not 0.0 <= reuse_rate <= 1.0:
            raise ValueError("transferred scenario reuse rate is invalid")
        if budget_index == 0:
            if warm.get("transfer_source_budget") is not None or transfer_count != 0:
                raise ValueError("first budget may not claim cross-budget transfer")
        else:
            if not math.isclose(float(warm.get("transfer_source_budget", math.nan)), 2571.372016574617, abs_tol=1.0e-9):
                raise ValueError("second-budget warm result has the wrong source budget")
            if comparison.get("transfer_input_state") != prior_state:
                raise ValueError("comparison transfer input is not the prior warm state")
            initial_pool = list(warm.get("initial_scenarios", []))
            reusable = set(prior_state["active_scenarios"]) | set(
                prior_state["historical_adversarial_scenarios"]
            )
            expected_transfer = [name for name in initial_pool if name in reusable]
            if transfer_names != expected_transfer or not expected_transfer:
                raise ValueError("second-budget transferred scenarios are empty or differ from prior state")
            expected_rate = len(expected_transfer) / len(initial_pool)
            if not math.isclose(reuse_rate, expected_rate, rel_tol=0.0, abs_tol=1.0e-12):
                raise ValueError("transferred scenario reuse rate was not independently reproduced")
            exact_costs = warm["ccg_result"]["exact_scenario_costs"]
            worst_cost = max(float(value) for value in exact_costs.values())
            active = {
                name for name, value in exact_costs.items()
                if worst_cost - float(value) <= 1.0e-6
            }
            worst = warm["ccg_result"].get("worst_scenario")
            expected_active_or_worst = [
                name for name in expected_transfer if name in active or name == worst
            ]
            if (
                warm.get("transferred_scenarios_becoming_active_or_worst")
                != expected_active_or_worst
                or int(warm.get("transferred_scenarios_becoming_active_or_worst_count", -1))
                != len(expected_active_or_worst)
            ):
                raise ValueError("transferred active/worst evidence mismatch")
        prior_state = comparison.get("transferred_state")
        if not isinstance(prior_state, dict):
            raise ValueError("warm solve did not finalize a transferable state")
        prior_components = component_rows[0]
    if solve_count != 6 or int(result.get("completed_algorithm_solve_count", -1)) != 6:
        raise ValueError("pilot sequence does not contain six solves")
    return {
        "solve_count": solve_count,
        "budget_pair_count": 2,
        "all_worker_seconds": all_walls,
        "ccg_worker_seconds": ccg_walls,
        "peak_memory_MiB": max(all_memory),
        "component_set_by_budget": [
            comparisons[index]["methods"]["cold"]["component_set_sha256"]
            for index in (0, 1)
        ],
        "cross_budget_transfer": {
            "source_budget": float(comparisons[1]["methods"]["warm"]["transfer_source_budget"]),
            "transferred_exact_scenarios": list(
                comparisons[1]["methods"]["warm"]["transferred_exact_scenarios"]
            ),
            "transferred_exact_scenario_count": int(
                comparisons[1]["methods"]["warm"]["transferred_exact_scenario_count"]
            ),
            "transferred_scenario_reuse_rate": float(
                comparisons[1]["methods"]["warm"]["transferred_scenario_reuse_rate"]
            ),
            "transferred_scenarios_becoming_active_or_worst": list(
                comparisons[1]["methods"]["warm"][
                    "transferred_scenarios_becoming_active_or_worst"
                ]
            ),
            "transferred_scenarios_becoming_active_or_worst_count": int(
                comparisons[1]["methods"]["warm"][
                    "transferred_scenarios_becoming_active_or_worst_count"
                ]
            ),
        },
    }


def update_projection(
    execution_root: Path, cases: Sequence[PerformanceCase],
    fingerprints: Mapping[str, str],
    execution_identity: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    registry_path = execution_root / "run_registry.json"
    rows = _registry(registry_path)
    expected = {case.case_id: case for case in cases}
    primary = {case_id: [row for row in rows if row.get("case_id") == case_id and not row.get("parent_run_id")] for case_id in expected}
    missing = [key for key, values in primary.items() if not values]
    duplicates = [key for key, values in primary.items() if len(values) > 1]
    failed, invalid, results, derived_rows = [], [], [], []
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
            if manifest.get("result_sha256") != sha256_file(result_path):
                raise ValueError("result hash mismatch")
            derived = _validate_pilot_result(
                result, expected[case_id], fingerprints, execution_identity,
            )
            results.append(result)
            derived_rows.append({"result": result, "derived": derived})
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
            if len({value["fulfillment_sha256"] for value in components}) != 2:
                crn_mismatches.append({"seed": seed, "budget_index": budget_index, "field": "fulfillment_profile_separation"})
    diagnostics = [row["run_id"] for row in rows if row.get("parent_run_id")]
    completed_pairs = sum(row["derived"]["budget_pair_count"] for row in derived_rows)
    completed_solves = sum(row["derived"]["solve_count"] for row in derived_rows)
    ccg_seconds = [value for row in derived_rows for value in row["derived"]["ccg_worker_seconds"]]
    maximum_peak_memory = max((row["derived"]["peak_memory_MiB"] for row in derived_rows), default=0.0)
    conservative_seconds = max(ccg_seconds, default=0.0)
    projected_hours = 240.0 * conservative_seconds / 3600.0
    transfer_evidence = [
        {
            "run_id": row["result"]["run_id"],
            "case_id": row["result"]["case_id"],
            "seed": row["result"]["seed"],
            "profile_id": row["result"]["profile_id"],
            **row["derived"]["cross_budget_transfer"],
        }
        for row in derived_rows
    ]
    projection_complete = (
        len(ccg_seconds) == 24
        and math.isfinite(conservative_seconds) and conservative_seconds > 0.0
        and math.isfinite(projected_hours) and projected_hours > 0.0
        and math.isfinite(maximum_peak_memory) and maximum_peak_memory >= 0.0
    )
    gate = (
        not (missing or duplicates or failed or invalid or diagnostics or crn_mismatches)
        and len(results) == 6 and completed_pairs == 12 and completed_solves == 36
        and projection_complete
    )
    payload = {
        "status": "passed" if gate else "incomplete",
        "required_primary_sequence_count": 6, "completed_primary_sequence_count": len(results),
        "required_budget_pair_count": 12, "completed_budget_pair_count": completed_pairs,
        "required_algorithm_solve_count": 36, "completed_algorithm_solve_count": completed_solves,
        "missing_case_ids": missing, "duplicate_case_ids": duplicates,
        "failed_primary_run_ids": failed, "invalid_primary_runs": invalid,
        "diagnostic_run_ids": diagnostics, "common_random_number_mismatches": crn_mismatches,
        "cross_budget_transfer_evidence": transfer_evidence,
        "total_transferred_exact_scenario_count": sum(
            row["transferred_exact_scenario_count"] for row in transfer_evidence
        ),
        "total_transferred_scenarios_becoming_active_or_worst_count": sum(
            row["transferred_scenarios_becoming_active_or_worst_count"]
            for row in transfer_evidence
        ),
        "formal_compute_projection": {
            "status": "projected" if projection_complete else "unavailable",
            "method": "240_times_maximum_pilot_CCG_worker_seconds",
            "planned_formal_algorithm_execution_count": 240,
            "conservative_seconds_per_execution": conservative_seconds,
            "projected_wall_hours": projected_hours,
            "maximum_sampled_peak_RSS_MiB": maximum_peak_memory,
        },
        "fingerprints": dict(fingerprints), "pilot_compute_gate_passed": gate,
        "execution_identity": (
            None if execution_identity is None else dict(execution_identity)
        ),
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
                result = run_sequence(root=root, runner=context["runner"], design=context["design"], fingerprints=context["fingerprints"], case=case, run_id=run_id, execution_root=execution_root, worker_executor=worker_executor, execution_identity=context["synchronized_main"])
                rows = _registry(registry_path)
                rows.append({"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "status": result["status"]})
                atomic_write_json(registry_path, {"namespace": NAMESPACE, "runs": rows})
                projection = update_projection(execution_root, context["cases"], context["fingerprints"], context["synchronized_main"])
                if result["status"] != "optimal": return projection
            except BaseException:
                rows = _registry(registry_path)
                status = json.loads((execution_root / "runs" / run_id / "status_summary.json").read_text(encoding="utf-8"))["status"]
                rows.append({"run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "status": status})
                atomic_write_json(registry_path, {"namespace": NAMESPACE, "runs": rows})
                update_projection(execution_root, context["cases"], context["fingerprints"], context["synchronized_main"])
                raise
        return update_projection(execution_root, context["cases"], context["fingerprints"], context["synchronized_main"])


def read_status(path: Path, *, maximum_bytes: int = 16384) -> dict[str, Any]:
    if not path.is_file():
        return {"status": "not_started", "path": str(path)}
    if path.stat().st_size > maximum_bytes:
        raise ValueError("status file exceeds bounded status-tool limit")
    return json.loads(path.read_text(encoding="utf-8"))

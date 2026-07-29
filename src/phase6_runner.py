"""Checkpointed Phase 6 cold/warm experiment runner."""

from __future__ import annotations

from collections.abc import Callable
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter, sleep
from typing import Any

import psutil
import yaml

from .model_common import validate_gurobi_runtime
from .phase6_protocol import (
    Phase6ProtocolError,
    budget_values_for_tier,
    generate_phase6_data,
    load_phase6_matrix,
    resolve_tier,
    validate_execution_seed,
)
from .phase6_locking import exclusive_file_lock
from .reproducibility import capture_runtime_context, sha256_file
from .scenario_generator import write_scenarios_csv
from .phase6_reporting import (
    append_failure_registry,
    update_algorithm_performance,
    update_pilot_projection,
    validate_formal_projection,
)


REGISTRY_FIELDS = (
    "run_id",
    "parent_run_id",
    "status",
    "execution_mode",
    "tier_id",
    "seed",
    "matrix_id",
    "matrix_sha256",
    "scientific_config_sha256",
    "runner_config_sha256",
    "e3_component_sha256",
    "planned_budget_count",
    "completed_budget_count",
    "started_at_utc",
    "updated_at_utc",
    "failure_stage",
    "failure_message",
    "result_path",
    "checkpoint_path",
)

BUDGET_FIELDS = (
    "budget_index",
    "budget",
    "budget_factor",
    "execution_order",
    "status",
    "cold_status",
    "warm_status",
    "failure_stage",
    "failure_message",
    "objective_difference",
    "cold_objective",
    "warm_objective",
    "cold_iterations",
    "warm_iterations",
    "cold_median_seconds",
    "warm_median_seconds",
    "cold_peak_memory_mb",
    "warm_peak_memory_mb",
    "cold_repetitions",
    "warm_repetitions",
    "active_scenario_count",
    "historical_adversarial_count",
)

ITERATION_FIELDS = (
    "budget_index",
    "budget",
    "algorithm",
    "repetition",
    "iteration",
    "scenario_count",
    "added_scenario",
    "added_type",
    "LB",
    "candidate_UB",
    "global_UB",
    "gap",
    "regular_cost",
    "R",
    "R/B",
    "master_time",
    "oracle_time",
    "infeasible_scenario_count",
    "worst_recourse_cost",
    "worst_scenario",
)


WorkerExecutor = Callable[[dict[str, Any], float, Path], dict[str, Any]]

PHASE6_E3_COMPONENT_FILES = (
    "src/phase6_protocol.py",
    "src/model_data.py",
    "src/scenario_generator.py",
    "src/model_common.py",
    "src/inventory_model.py",
    "src/recourse_model.py",
    "src/evaluation.py",
    "src/extensive_model.py",
    "src/ccg.py",
    "src/spw_ccg.py",
    "src/phase6_worker.py",
    "src/phase6_runner.py",
)

PHASE6_E3_DEPENDENCY_NAMES = (
    "filelock",
    "gurobipy",
    "numpy",
    "psutil",
    "pyomo",
    "pyyaml",
)
PHASE6_E3_REQUIREMENTS_FILE = "requirements-gurobi-lock.txt"

SCIENTIFIC_CONFIG_EXCLUDED_ROOT_FIELDS = (
    "status",
    "initial_draft_on",
    "revised_on",
)

RUN_LOCK_TIMEOUT_SECONDS = 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _upsert_registry(path: Path, row: dict[str, Any]) -> None:
    lock_path = path.parent / ".aggregate.lock"
    with exclusive_file_lock(lock_path):
        existing: list[dict[str, Any]] = []
        if path.exists():
            with path.open(
                "r",
                encoding="utf-8-sig",
                newline="",
            ) as handle:
                existing = [
                    {
                        name: row.get(name)
                        for name in REGISTRY_FIELDS
                    }
                    for row in csv.DictReader(handle)
                ]
        replaced = False
        for index, current in enumerate(existing):
            if current["run_id"] == str(row["run_id"]):
                existing[index] = {
                    name: row.get(name) for name in REGISTRY_FIELDS
                }
                replaced = True
                break
        if not replaced:
            existing.append(
                {name: row.get(name) for name in REGISTRY_FIELDS}
            )
        _atomic_write_csv(path, REGISTRY_FIELDS, existing)


def _scientific_config_sha256(matrix: dict[str, Any]) -> str:
    """Hash scientific matrix content while excluding lifecycle metadata."""

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


def _e3_component_code_sha256(project_root: Path) -> str:
    """Hash only code and dependencies that can change E3 scientific runs."""

    paths = [project_root / relative for relative in PHASE6_E3_COMPONENT_FILES]
    digest = hashlib.sha256()
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"E3 component file is missing: {path}")
        relative = path.relative_to(project_root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    requirements_path = project_root / PHASE6_E3_REQUIREMENTS_FILE
    if not requirements_path.is_file():
        raise FileNotFoundError(
            f"E3 dependency lock is missing: {requirements_path}"
        )
    requirement_lines = requirements_path.read_text(
        encoding="utf-8"
    ).splitlines()
    e3_requirements = sorted(
        line.strip()
        for line in requirement_lines
        if line.strip()
        and not line.lstrip().startswith("#")
        and line.split(";", maxsplit=1)[0]
        .strip()
        .lower()
        .startswith(PHASE6_E3_DEPENDENCY_NAMES)
    )
    digest.update(PHASE6_E3_REQUIREMENTS_FILE.encode("utf-8"))
    digest.update(b"\0")
    digest.update("\n".join(e3_requirements).encode("utf-8"))
    digest.update(b"\0")
    return digest.hexdigest()


def load_phase6_runner_config(path: str | Path) -> dict[str, Any]:
    """Load runner settings and reject ambiguous solver configuration."""

    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("phase 6 runner config root must be a mapping")
    solver = config["solver"]
    preference = tuple(
        str(value).strip().lower() for value in solver["preference"]
    )
    if preference != ("gurobi",):
        raise ValueError(
            "Phase 6 is Gurobi-only; solver preference must be [gurobi]"
        )
    if int(solver["threads"]) != 1:
        raise ValueError("Phase 6 primary runs require exactly one solver thread")
    for name in ("feasibility_tolerance", "optimality_tolerance"):
        if float(solver[name]) <= 0.0:
            raise ValueError(f"{name} must be positive")
    runner = config["runner"]
    if float(runner["active_scenario_tolerance"]) < 0.0:
        raise ValueError("active_scenario_tolerance must be nonnegative")
    return config


def _default_worker_executor(
    request: dict[str, Any],
    timeout_seconds: float,
    work_directory: Path,
) -> dict[str, Any]:
    """Run one worker in a monitored subprocess with a hard wall timeout."""

    work_directory.mkdir(parents=True, exist_ok=True)
    suffix = (
        f"a{request['attempt']:02d}_b{request['budget_index']:02d}_"
        f"{request['algorithm']}"
        f"_r{request['repetition']:02d}"
    )
    request_path = work_directory / f"{suffix}_request.json"
    result_path = work_directory / f"{suffix}_result.json"
    progress_path = work_directory / f"{suffix}_progress.json"
    request = {**request, "progress_path": str(progress_path)}
    _atomic_write_json(request_path, request)
    if result_path.exists():
        result_path.unlink()
    if progress_path.exists():
        progress_path.unlink()

    environment = os.environ.copy()
    environment.update(
        {
            "OMP_NUM_THREADS": "1",
            "OPENBLAS_NUM_THREADS": "1",
            "MKL_NUM_THREADS": "1",
            "NUMEXPR_NUM_THREADS": "1",
        }
    )
    command = [
        sys.executable,
        "-m",
        "src.phase6_worker",
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    started = perf_counter()
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    monitored = psutil.Process(process.pid)
    peak_bytes = 0
    timed_out = False
    while process.poll() is None:
        elapsed = perf_counter() - started
        if elapsed > timeout_seconds:
            timed_out = True
            try:
                descendants = monitored.children(recursive=True)
                for child in reversed(descendants):
                    child.kill()
                monitored.kill()
                psutil.wait_procs(
                    [*descendants, monitored],
                    timeout=5.0,
                )
            except (psutil.Error, OSError):
                process.kill()
            break
        try:
            processes = [monitored, *monitored.children(recursive=True)]
            peak_bytes = max(
                peak_bytes,
                sum(
                    child.memory_info().rss
                    for child in processes
                    if child.is_running()
                ),
            )
        except (psutil.Error, OSError):
            pass
        sleep(0.05)
    stdout, stderr = process.communicate()
    elapsed = perf_counter() - started
    if timed_out:
        partial_progress = None
        if progress_path.exists():
            try:
                partial_progress = json.loads(
                    progress_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                partial_progress = {
                    "status": "unreadable_progress_file",
                    "path": str(progress_path),
                }
        payload = {
            "status": "budget_wall_timeout",
            "algorithm": request["algorithm"],
            "tier_id": request["tier_id"],
            "seed": request["seed"],
            "budget": request["budget"],
            "ccg_result": None,
            "partial_progress": partial_progress,
            "progress_path": str(progress_path),
            "failure": {
                "stage": "external_budget_watchdog",
                "exception_type": "TimeoutExpired",
                "message": (
                    f"worker exceeded wall limit {timeout_seconds:.6f}s"
                ),
            },
            "subprocess_wall_seconds": elapsed,
            "peak_memory_mb": peak_bytes / (1024.0**2),
            "return_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }
        _atomic_write_json(result_path, payload)
        return payload
    if result_path.exists():
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    else:
        payload = {
            "status": "worker_process_error",
            "algorithm": request["algorithm"],
            "tier_id": request["tier_id"],
            "seed": request["seed"],
            "budget": request["budget"],
            "ccg_result": None,
            "failure": {
                "stage": "worker_process",
                "exception_type": "MissingResultFile",
                "message": "worker exited without a result file",
            },
        }
    payload.update(
        {
            "subprocess_wall_seconds": elapsed,
            "peak_memory_mb": peak_bytes / (1024.0**2),
            "return_code": process.returncode,
            "stdout": stdout,
            "stderr": stderr,
            "progress_path": str(progress_path),
        }
    )
    return payload


def _ordered_union(
    scenario_order: list[str],
    *groups: list[str],
) -> list[str]:
    requested = {value for group in groups for value in group}
    unknown = requested - set(scenario_order)
    if unknown:
        raise ValueError(f"unknown scenario in state transfer: {sorted(unknown)}")
    return [scenario for scenario in scenario_order if scenario in requested]


def _build_transferred_state(
    warm: dict[str, Any],
    previous_state: dict[str, Any] | None,
    *,
    budget: float,
    tolerance: float,
) -> dict[str, Any]:
    ccg = warm["ccg_result"]
    costs = {str(k): float(v) for k, v in ccg["exact_scenario_costs"].items()}
    if not costs:
        raise ValueError("warm result has no exact scenario costs")
    scenario_order = list(costs)
    worst = max(costs.values())
    active = [
        scenario
        for scenario in scenario_order
        if worst - costs[scenario] <= tolerance
    ]
    added = [
        str(row["added_scenario"])
        for row in ccg["iteration_log"]
        if row.get("added_scenario") is not None
        and row.get("added_type") in {"infeasible", "worst_cost"}
    ]
    if ccg.get("worst_scenario") is not None:
        added.append(str(ccg["worst_scenario"]))
    previous_history = (
        []
        if previous_state is None
        else [
            str(value)
            for value in previous_state[
                "historical_adversarial_scenarios"
            ]
        ]
    )
    history = _ordered_union(scenario_order, previous_history, added)
    return {
        "budget": float(budget),
        "final_scenario_set": [
            str(value) for value in ccg["final_scenario_set"]
        ],
        "active_scenarios": active,
        "historical_adversarial_scenarios": history,
    }


def _median_repetition(repetitions: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = sorted(
        repetitions,
        key=lambda row: float(row["subprocess_wall_seconds"]),
    )
    return ordered[(len(ordered) - 1) // 2]


def _validate_repetitions(
    repetitions: list[dict[str, Any]],
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> tuple[bool, str | None]:
    if any(row["status"] != "optimal" for row in repetitions):
        failed = next(row for row in repetitions if row["status"] != "optimal")
        return False, f"nonoptimal repetition: {failed['status']}"
    objectives = [
        float(row["ccg_result"]["objective"]) for row in repetitions
    ]
    spread = max(objectives) - min(objectives)
    limit = absolute_tolerance + relative_tolerance * max(
        1.0,
        *(abs(value) for value in objectives),
    )
    if spread > limit:
        return False, (
            f"technical repetitions differ by {spread}, tolerance {limit}"
        )
    return True, None


def _checkpoint_fingerprint(
    *,
    matrix_path: Path,
    runner_config_path: Path,
    matrix: dict[str, Any],
    tier_id: str,
    seed: int,
    execution_mode: str,
    budgets: tuple[float, ...],
    e3_component_sha256: str,
    parent_run_id: str | None,
) -> dict[str, Any]:
    return {
        "matrix_id": matrix["matrix_id"],
        "matrix_sha256": sha256_file(matrix_path),
        "scientific_config_sha256": _scientific_config_sha256(matrix),
        "runner_config_sha256": sha256_file(runner_config_path),
        "e3_component_sha256": e3_component_sha256,
        "tier_id": tier_id,
        "seed": int(seed),
        "execution_mode": execution_mode,
        "parent_run_id": parent_run_id,
        "budgets": list(budgets),
    }


def _completed_budget_count(comparisons: list[dict[str, Any]]) -> int:
    return sum(row.get("status") == "optimal" for row in comparisons)


def _not_run_mode(status: str) -> dict[str, Any]:
    return {
        "status": status,
        "repetitions": [],
        "representative": None,
        "unexecuted_status": status,
    }


def _terminal_budget_records(
    *,
    completed: list[dict[str, Any]],
    budgets: tuple[float, ...],
    failure: dict[str, Any],
    current_modes: dict[str, dict[str, Any]],
    current_execution_order: tuple[str, str],
    planned_repetitions: int,
    alternate_execution_order: bool,
) -> list[dict[str, Any]]:
    """Add the failed pair and every planned-but-unrun later budget."""

    failure_index = int(failure["budget_index"])
    records = list(completed)
    failed_algorithm = failure.get("algorithm")
    for algorithm in ("cold", "warm"):
        if algorithm in current_modes:
            payload = current_modes[algorithm]
            payload.setdefault(
                "status",
                (
                    "optimal"
                    if payload.get("representative") is not None
                    else str(failure["status"])
                ),
            )
            payload.setdefault(
                "unexecuted_status",
                (
                    "not_run_after_algorithm_failure"
                    if algorithm == failed_algorithm
                    else None
                ),
            )
        elif algorithm == failed_algorithm:
            repetitions = list(failure.get("partial_repetitions", ()))
            current_modes[algorithm] = {
                "status": str(failure["status"]),
                "repetitions": repetitions,
                "representative": None,
                "unexecuted_status": "not_run_after_algorithm_failure",
            }
        else:
            current_modes[algorithm] = _not_run_mode(
                "not_run_after_pair_failure"
            )
    records.append(
        {
            "status": str(failure["status"]),
            "budget_index": failure_index,
            "budget": float(budgets[failure_index]),
            "execution_order": list(current_execution_order),
            "planned_repetitions": planned_repetitions,
            "objective_difference": None,
            "consistency_tolerance": None,
            "cold": current_modes["cold"],
            "warm": current_modes["warm"],
            "transferred_state": None,
            "failure_stage": failure["stage"],
            "failure_message": failure["message"],
        }
    )
    for budget_index in range(failure_index + 1, len(budgets)):
        execution_order = (
            ("cold", "warm")
            if (
                not alternate_execution_order
                or budget_index % 2 == 0
            )
            else ("warm", "cold")
        )
        records.append(
            {
                "status": "not_run_after_pair_sequence_failure",
                "budget_index": budget_index,
                "budget": float(budgets[budget_index]),
                "execution_order": list(execution_order),
                "planned_repetitions": planned_repetitions,
                "objective_difference": None,
                "consistency_tolerance": None,
                "cold": _not_run_mode(
                    "not_run_after_pair_sequence_failure"
                ),
                "warm": _not_run_mode(
                    "not_run_after_pair_sequence_failure"
                ),
                "transferred_state": None,
                "failure_stage": "pair_sequence",
                "failure_message": (
                    "not run because an earlier budget pair failed"
                ),
            }
        )
    return records


def _budget_rows(comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in comparisons:
        cold = row["cold"].get("representative")
        warm = row["warm"].get("representative")
        state = row["transferred_state"]
        cold_ccg = None if cold is None else cold.get("ccg_result")
        warm_ccg = None if warm is None else warm.get("ccg_result")
        rows.append(
            {
                "budget_index": row["budget_index"],
                "budget": row["budget"],
                "budget_factor": (
                    cold.get("budget_factor") if cold is not None else None
                ),
                "execution_order": "->".join(row["execution_order"]),
                "status": row["status"],
                "cold_status": row["cold"].get("status"),
                "warm_status": row["warm"].get("status"),
                "failure_stage": row.get("failure_stage"),
                "failure_message": row.get("failure_message"),
                "objective_difference": row["objective_difference"],
                "cold_objective": (
                    cold_ccg.get("objective")
                    if cold_ccg is not None
                    else None
                ),
                "warm_objective": (
                    warm_ccg.get("objective")
                    if warm_ccg is not None
                    else None
                ),
                "cold_iterations": (
                    cold_ccg.get("iterations")
                    if cold_ccg is not None
                    else None
                ),
                "warm_iterations": (
                    warm_ccg.get("iterations")
                    if warm_ccg is not None
                    else None
                ),
                "cold_median_seconds": (
                    cold.get("subprocess_wall_seconds")
                    if cold is not None
                    else None
                ),
                "warm_median_seconds": (
                    warm.get("subprocess_wall_seconds")
                    if warm is not None
                    else None
                ),
                "cold_peak_memory_mb": max(
                    (
                        value.get("peak_memory_mb", 0.0)
                        for value in row["cold"]["repetitions"]
                    ),
                    default=None,
                ),
                "warm_peak_memory_mb": max(
                    (
                        value.get("peak_memory_mb", 0.0)
                        for value in row["warm"]["repetitions"]
                    ),
                    default=None,
                ),
                "cold_repetitions": len(row["cold"]["repetitions"]),
                "warm_repetitions": len(row["warm"]["repetitions"]),
                "active_scenario_count": (
                    len(state["active_scenarios"])
                    if state is not None
                    else None
                ),
                "historical_adversarial_count": (
                    len(state["historical_adversarial_scenarios"])
                    if state is not None
                    else None
                ),
            }
        )
    return rows


def _iteration_rows(
    comparisons: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for comparison in comparisons:
        for algorithm in ("cold", "warm"):
            for repetition_index, repetition in enumerate(
                comparison[algorithm]["repetitions"],
                start=1,
            ):
                ccg = repetition.get("ccg_result")
                if ccg is None:
                    continue
                for iteration in ccg["iteration_log"]:
                    rows.append(
                        {
                            "budget_index": comparison["budget_index"],
                            "budget": comparison["budget"],
                            "algorithm": algorithm,
                            "repetition": repetition_index,
                            **iteration,
                        }
                    )
    return rows


def run_phase6_sequence(
    *,
    matrix_path: Path,
    runner_config_path: Path,
    output_root: Path,
    tier_id: str,
    seed: int,
    execution_mode: str,
    run_id: str,
    resume: bool = False,
    parent_run_id: str | None = None,
    worker_executor: WorkerExecutor | None = None,
) -> dict[str, Any]:
    """Run one sequence while holding a full-lifecycle per-run lock."""

    resolved_output = output_root.resolve()
    run_directory = (
        resolved_output / "experiments" / "phase6" / "runs" / run_id
    )
    with exclusive_file_lock(
        run_directory / ".run.lock",
        timeout_seconds=RUN_LOCK_TIMEOUT_SECONDS,
    ):
        return _run_phase6_sequence_locked(
            matrix_path=matrix_path,
            runner_config_path=runner_config_path,
            output_root=resolved_output,
            tier_id=tier_id,
            seed=seed,
            execution_mode=execution_mode,
            run_id=run_id,
            resume=resume,
            parent_run_id=parent_run_id,
            worker_executor=worker_executor,
        )


def _run_phase6_sequence_locked(
    *,
    matrix_path: Path,
    runner_config_path: Path,
    output_root: Path,
    tier_id: str,
    seed: int,
    execution_mode: str,
    run_id: str,
    resume: bool = False,
    parent_run_id: str | None = None,
    worker_executor: WorkerExecutor | None = None,
) -> dict[str, Any]:
    """Run or resume a locked tier-seed sequence with atomic checkpoints."""

    matrix_path = matrix_path.resolve()
    runner_config_path = runner_config_path.resolve()
    output_root = output_root.resolve()
    matrix = load_phase6_matrix(matrix_path)
    config = load_phase6_runner_config(runner_config_path)
    validate_gurobi_runtime()
    tier = resolve_tier(matrix, tier_id)
    validate_execution_seed(
        matrix,
        tier_id=tier_id,
        seed=seed,
        execution_mode=execution_mode,
    )
    budgets = budget_values_for_tier(
        matrix,
        tier_id,
        matrix_path=matrix_path,
    )
    code_sha256 = _e3_component_code_sha256(matrix_path.parent.parent)
    fingerprint = _checkpoint_fingerprint(
        matrix_path=matrix_path,
        runner_config_path=runner_config_path,
        matrix=matrix,
        tier_id=tier_id,
        seed=seed,
        execution_mode=execution_mode,
        budgets=budgets,
        e3_component_sha256=code_sha256,
        parent_run_id=parent_run_id,
    )

    if execution_mode == "formal":
        validate_formal_projection(
            projection_path=(
                output_root
                / "experiments"
                / "phase6"
                / "pilot_throughput_projection.json"
            ),
            matrix_id=str(matrix["matrix_id"]),
            scientific_config_sha256=str(
                fingerprint["scientific_config_sha256"]
            ),
            runner_config_sha256=str(
                fingerprint["runner_config_sha256"]
            ),
            e3_component_sha256=str(
                fingerprint["e3_component_sha256"]
            ),
        )

    run_directory = output_root / "experiments" / "phase6" / "runs" / run_id
    worker_directory = run_directory / "workers"
    checkpoint_path = run_directory / "checkpoint.json"
    result_path = run_directory / "result.json"
    registry_path = output_root / "experiments" / "phase6" / "run_registry.csv"
    comparisons: list[dict[str, Any]] = []
    previous_state: dict[str, Any] | None = None
    sequence_elapsed = {
        "cold": [0.0 for _ in range(tier.timing_repetitions)],
        "warm": [0.0 for _ in range(tier.timing_repetitions)],
    }
    started_at = _utc_now()
    attempt = 1
    if parent_run_id == run_id:
        raise Phase6ProtocolError("diagnostic retry must use a new run_id")
    if parent_run_id is not None:
        parent_result_path = (
            output_root
            / "experiments"
            / "phase6"
            / "runs"
            / parent_run_id
            / "result.json"
        )
        if not parent_result_path.exists():
            raise Phase6ProtocolError(
                f"parent run result does not exist: {parent_run_id}"
            )
        parent_result = json.loads(
            parent_result_path.read_text(encoding="utf-8")
        )
        if parent_result.get("status") == "optimal":
            raise Phase6ProtocolError(
                "diagnostic retry parent must be a failed terminal run"
            )
    if checkpoint_path.exists():
        if not resume:
            raise FileExistsError(
                f"checkpoint already exists for {run_id}; use resume=True"
            )
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("status") not in {"running", "interrupted"}:
            raise Phase6ProtocolError(
                "resume is allowed only for running or interrupted "
                f"checkpoints; found {checkpoint.get('status')!r}"
            )
        if checkpoint["fingerprint"] != fingerprint:
            raise Phase6ProtocolError(
                "checkpoint fingerprint does not match the requested run"
            )
        comparisons = list(checkpoint["comparisons"])
        previous_state = checkpoint["previous_state"]
        sequence_elapsed = checkpoint["sequence_elapsed_seconds"]
        started_at = str(checkpoint["started_at_utc"])
        attempt = int(checkpoint.get("attempt", 1)) + 1

    generated = generate_phase6_data(
        matrix,
        matrix_path=matrix_path,
        tier_id=tier_id,
        seed=seed,
        budget=budgets[0],
    )
    scenarios_path = run_directory / "training_scenarios.csv"
    if not scenarios_path.exists():
        write_scenarios_csv(generated.data, scenarios_path)
    resolved_run_path = run_directory / "resolved_run.json"
    resolved_run = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "fingerprint": fingerprint,
        "tier": tier.__dict__,
        "budgets": list(budgets),
        "solver": config["solver"],
        "algorithm_comparison": matrix["algorithm_comparison"],
        "timeout_protocol": matrix["timeout_protocol"],
        "started_at_utc": started_at,
    }
    _atomic_write_json(resolved_run_path, resolved_run)

    executor = worker_executor or _default_worker_executor
    algorithm = matrix["algorithm_comparison"]
    exactness = matrix["exactness_gates"]["cold_vs_warm"]
    absolute_tolerance = float(exactness["objective_absolute_tolerance"])
    relative_tolerance = float(exactness["objective_relative_tolerance"])
    active_tolerance = float(config["runner"]["active_scenario_tolerance"])
    failure: dict[str, Any] | None = None
    completed_count = _completed_budget_count(comparisons)
    if comparisons:
        expected_prefix = list(budgets[:completed_count])
        actual_prefix = [float(row["budget"]) for row in comparisons]
        if actual_prefix != expected_prefix:
            raise Phase6ProtocolError(
                "checkpoint comparisons are not the expected budget prefix"
            )

    def save_checkpoint(status: str) -> None:
        _atomic_write_json(
            checkpoint_path,
            {
                "status": status,
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "fingerprint": fingerprint,
                "started_at_utc": started_at,
                "updated_at_utc": _utc_now(),
                "attempt": attempt,
                "comparisons": comparisons,
                "previous_state": previous_state,
                "sequence_elapsed_seconds": sequence_elapsed,
                "failure": failure,
            },
        )

    save_checkpoint("running")
    _upsert_registry(
        registry_path,
        {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "status": "running",
            "execution_mode": execution_mode,
            "tier_id": tier_id,
            "seed": seed,
            "matrix_id": matrix["matrix_id"],
            "matrix_sha256": fingerprint["matrix_sha256"],
            "scientific_config_sha256": fingerprint[
                "scientific_config_sha256"
            ],
            "runner_config_sha256": fingerprint["runner_config_sha256"],
            "e3_component_sha256": fingerprint["e3_component_sha256"],
            "planned_budget_count": len(budgets),
            "completed_budget_count": completed_count,
            "started_at_utc": started_at,
            "updated_at_utc": _utc_now(),
            "failure_stage": None,
            "failure_message": None,
            "result_path": str(result_path),
            "checkpoint_path": str(checkpoint_path),
        },
    )

    failed_mode_payloads: dict[str, dict[str, Any]] = {}
    failed_execution_order = ("cold", "warm")
    for budget_index in range(completed_count, len(budgets)):
        budget = budgets[budget_index]
        execution_order = (
            ("cold", "warm")
            if (
                not bool(algorithm["alternate_execution_order"])
                or budget_index % 2 == 0
            )
            else ("warm", "cold")
        )
        mode_payloads: dict[str, dict[str, Any]] = {}
        for mode in execution_order:
            repetitions: list[dict[str, Any]] = []
            for repetition in range(tier.timing_repetitions):
                sequence_remaining = (
                    tier.budget_sequence_wall_seconds
                    - float(sequence_elapsed[mode][repetition])
                )
                effective_wall = min(
                    tier.ccg_budget_wall_seconds,
                    sequence_remaining,
                )
                if effective_wall <= 0.0:
                    payload = {
                        "status": "sequence_wall_timeout",
                        "algorithm": mode,
                        "tier_id": tier_id,
                        "seed": seed,
                        "budget": budget,
                        "ccg_result": None,
                        "subprocess_wall_seconds": 0.0,
                        "peak_memory_mb": 0.0,
                        "failure": {
                            "stage": "external_sequence_watchdog",
                            "exception_type": "TimeoutExpired",
                            "message": (
                                f"{mode} repetition {repetition + 1} exhausted "
                                "its budget-sequence wall allowance"
                            ),
                        },
                    }
                else:
                    request = {
                        "matrix_path": str(matrix_path),
                        "attempt": attempt,
                        "tier_id": tier_id,
                        "seed": int(seed),
                        "budget": float(budget),
                        "budget_index": budget_index,
                        "algorithm": mode,
                        "repetition": repetition + 1,
                        "previous_state": previous_state,
                        "solver": {
                            **config["solver"],
                            "call_time_limit_seconds": (
                                tier.solver_call_seconds
                            ),
                        },
                        "ccg": {
                            "absolute_tolerance": float(
                                config["ccg"]["absolute_tolerance"]
                            ),
                            "relative_tolerance": float(
                                config["ccg"]["relative_tolerance"]
                            ),
                            "max_iterations": int(
                                algorithm["max_iterations"]
                            ),
                        },
                    }
                    payload = executor(
                        request,
                        effective_wall,
                        worker_directory,
                    )
                sequence_elapsed[mode][repetition] += float(
                    payload.get("subprocess_wall_seconds", 0.0)
                )
                repetitions.append(payload)
                if payload["status"] != "optimal":
                    break

            valid, repetition_error = _validate_repetitions(
                repetitions,
                absolute_tolerance=absolute_tolerance,
                relative_tolerance=relative_tolerance,
            )
            if valid:
                mode_payloads[mode] = {
                    "status": "optimal",
                    "repetitions": repetitions,
                    "representative": _median_repetition(repetitions),
                    "unexecuted_status": None,
                }
            else:
                nonoptimal = next(
                    (
                        row
                        for row in repetitions
                        if row["status"] != "optimal"
                    ),
                    None,
                )
                failure = {
                    "status": (
                        str(nonoptimal["status"])
                        if nonoptimal is not None
                        else "technical_repetition_inconsistent"
                    ),
                    "stage": mode,
                    "budget_index": budget_index,
                    "budget": budget,
                    "algorithm": mode,
                    "message": repetition_error,
                    "partial_repetitions": repetitions,
                }
                mode_payloads[mode] = {
                    "status": str(failure["status"]),
                    "repetitions": repetitions,
                    "representative": None,
                    "unexecuted_status": (
                        "not_run_after_algorithm_failure"
                    ),
                }
                failed_mode_payloads = mode_payloads
                failed_execution_order = execution_order
                break
        if failure is not None:
            save_checkpoint("failed")
            break

        cold = mode_payloads["cold"]["representative"]
        warm = mode_payloads["warm"]["representative"]
        cold_objective = float(cold["ccg_result"]["objective"])
        warm_objective = float(warm["ccg_result"]["objective"])
        difference = abs(cold_objective - warm_objective)
        consistency_limit = absolute_tolerance + relative_tolerance * max(
            1.0,
            abs(cold_objective),
            abs(warm_objective),
        )
        if difference > consistency_limit:
            failure = {
                "status": "inconsistent_cold_warm_objectives",
                "stage": "comparison",
                "budget_index": budget_index,
                "budget": budget,
                "algorithm": None,
                "message": (
                    f"objective difference {difference} exceeds "
                    f"tolerance {consistency_limit}"
                ),
                "partial_repetitions": mode_payloads,
            }
            failed_mode_payloads = mode_payloads
            failed_execution_order = execution_order
            save_checkpoint("failed")
            break
        try:
            transferred_state = _build_transferred_state(
                warm,
                previous_state,
                budget=budget,
                tolerance=active_tolerance,
            )
        except Exception as exc:
            failure = {
                "status": "state_transfer_exception",
                "stage": "state_transfer",
                "budget_index": budget_index,
                "budget": budget,
                "algorithm": None,
                "message": f"{type(exc).__name__}: {exc}",
                "partial_repetitions": mode_payloads,
            }
            failed_mode_payloads = mode_payloads
            failed_execution_order = execution_order
            save_checkpoint("failed")
            break
        comparison = {
            "status": "optimal",
            "budget_index": budget_index,
            "budget": budget,
            "execution_order": list(execution_order),
            "planned_repetitions": tier.timing_repetitions,
            "objective_difference": difference,
            "consistency_tolerance": consistency_limit,
            "cold": mode_payloads["cold"],
            "warm": mode_payloads["warm"],
            "transferred_state": transferred_state,
            "failure_stage": None,
            "failure_message": None,
        }
        comparisons.append(comparison)
        previous_state = transferred_state
        save_checkpoint("running")
        _upsert_registry(
            registry_path,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "status": "running",
                "execution_mode": execution_mode,
                "tier_id": tier_id,
                "seed": seed,
                "matrix_id": matrix["matrix_id"],
                "matrix_sha256": fingerprint["matrix_sha256"],
                "scientific_config_sha256": fingerprint[
                    "scientific_config_sha256"
                ],
                "runner_config_sha256": fingerprint["runner_config_sha256"],
                "e3_component_sha256": fingerprint[
                    "e3_component_sha256"
                ],
                "planned_budget_count": len(budgets),
                "completed_budget_count": _completed_budget_count(
                    comparisons
                ),
                "started_at_utc": started_at,
                "updated_at_utc": _utc_now(),
                "failure_stage": None,
                "failure_message": None,
                "result_path": str(result_path),
                "checkpoint_path": str(checkpoint_path),
            },
        )

    if failure is not None:
        comparisons = _terminal_budget_records(
            completed=comparisons,
            budgets=budgets,
            failure=failure,
            current_modes=failed_mode_payloads,
            current_execution_order=failed_execution_order,
            planned_repetitions=tier.timing_repetitions,
            alternate_execution_order=bool(
                algorithm["alternate_execution_order"]
            ),
        )
    status = "optimal" if failure is None else str(failure["status"])
    finished_at = _utc_now()
    result = {
        "run_id": run_id,
        "parent_run_id": parent_run_id,
        "status": status,
        "execution_mode": execution_mode,
        "tier_id": tier_id,
        "seed": seed,
        "matrix_id": matrix["matrix_id"],
        "budgets": list(budgets),
        "completed_budget_count": _completed_budget_count(comparisons),
        "planned_budget_count": len(budgets),
        "started_at_utc": started_at,
        "finished_at_utc": finished_at,
        "sequence_elapsed_seconds": sequence_elapsed,
        "comparisons": comparisons,
        "failure": failure,
    }
    _atomic_write_json(result_path, result)
    _atomic_write_csv(
        run_directory / "budget_comparison.csv",
        BUDGET_FIELDS,
        _budget_rows(comparisons),
    )
    _atomic_write_csv(
        run_directory / "ccg_iterations.csv",
        ITERATION_FIELDS,
        _iteration_rows(comparisons),
    )
    runtime_context = capture_runtime_context(
        solver_preference=tuple(config["solver"]["preference"]),
        project_root=matrix_path.parent.parent,
        solver_threads=int(config["solver"]["threads"]),
    )
    _atomic_write_json(
        run_directory / "manifest.json",
        {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "matrix_path": str(matrix_path),
            "matrix_sha256": fingerprint["matrix_sha256"],
            "scientific_config_sha256": fingerprint[
                "scientific_config_sha256"
            ],
            "runner_config_path": str(runner_config_path),
            "runner_config_sha256": fingerprint["runner_config_sha256"],
            "e3_component_sha256": fingerprint["e3_component_sha256"],
            "resolved_run_path": str(resolved_run_path),
            "resolved_run_sha256": sha256_file(resolved_run_path),
            "training_scenarios_path": str(scenarios_path),
            "training_scenarios_sha256": sha256_file(scenarios_path),
            **runtime_context,
        },
    )
    save_checkpoint(status)
    _upsert_registry(
        registry_path,
        {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "status": status,
            "execution_mode": execution_mode,
            "tier_id": tier_id,
            "seed": seed,
            "matrix_id": matrix["matrix_id"],
            "matrix_sha256": fingerprint["matrix_sha256"],
            "scientific_config_sha256": fingerprint[
                "scientific_config_sha256"
            ],
            "runner_config_sha256": fingerprint["runner_config_sha256"],
            "e3_component_sha256": fingerprint["e3_component_sha256"],
            "planned_budget_count": len(budgets),
            "completed_budget_count": _completed_budget_count(comparisons),
            "started_at_utc": started_at,
            "updated_at_utc": finished_at,
            "failure_stage": (
                failure["stage"] if failure is not None else None
            ),
            "failure_message": (
                failure["message"] if failure is not None else None
            ),
            "result_path": str(result_path),
            "checkpoint_path": str(checkpoint_path),
        },
    )
    performance_path = update_algorithm_performance(output_root, result)
    projection = update_pilot_projection(
        output_root=output_root,
        matrix=matrix,
        runner_config=config,
        matrix_sha256=str(fingerprint["matrix_sha256"]),
        scientific_config_sha256=str(
            fingerprint["scientific_config_sha256"]
        ),
        runner_config_sha256=str(fingerprint["runner_config_sha256"]),
        e3_component_sha256=str(fingerprint["e3_component_sha256"]),
    )
    result["reporting"] = {
        "algorithm_performance_path": str(performance_path),
        "pilot_projection_path": str(
            output_root
            / "experiments"
            / "phase6"
            / "pilot_throughput_projection.json"
        ),
        "pilot_projection_status": projection["status"],
        "formal_execution_authorized": projection[
            "formal_execution_authorized"
        ],
    }
    _atomic_write_json(result_path, result)
    if failure is not None:
        failure_path = output_root / "experiments" / "phase6" / "failure_registry.csv"
        append_failure_registry(
            failure_path,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "tier_id": tier_id,
                "seed": seed,
                "budget_index": failure.get("budget_index"),
                "budget": failure.get("budget"),
                "stage": failure["stage"],
                "status": failure["status"],
                "message": failure["message"],
                "recorded_at_utc": finished_at,
            },
        )
    return result

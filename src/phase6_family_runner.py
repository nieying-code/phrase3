"""Checkpointed runner for Phase 6 E1/E2/E4/E5 experiment families."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter, sleep
from typing import Any, Callable, Mapping

import psutil
import yaml

from .model_common import validate_gurobi_runtime
from .phase6_environment import (
    environment_sha256,
    validate_locked_environment,
)
from .phase6_families import (
    FAMILY_COMPONENT_FILES,
    FAMILIES,
    POLICY_RATIOS,
    _atomic_write_json,
    compact_failure,
    enumerate_family_plans,
    family_code_sha256,
    load_verified_plan_result,
    sensitivity_configurations,
    scientific_config_sha256,
    update_family_projection,
    upsert_family_registry,
    validate_family_run_artifacts,
)
from .phase6_locking import exclusive_file_lock
from .phase6_protocol import (
    Phase6ProtocolError,
    budget_values_for_tier,
    load_phase6_matrix,
    validate_execution_seed,
    validate_matrix_execution_status,
)
from .phase6_io import sha256_lf_text_file
from .reproducibility import (
    capture_runtime_context,
    sha256_file,
    validate_execution_source,
)


FamilyWorker = Callable[
    [dict[str, Any], float, Path],
    dict[str, Any],
]
RUN_LOCK_TIMEOUT_SECONDS = 0.0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_family_runner_config(path: str | Path) -> dict[str, Any]:
    """Load the independent family runner and reject solver ambiguity."""

    with Path(path).open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict):
        raise ValueError("family runner config root must be a mapping")
    preference = tuple(
        str(value).strip().lower()
        for value in config["solver"]["preference"]
    )
    if preference != ("gurobi",):
        raise ValueError("Phase 6 family runs require exactly [gurobi]")
    if int(config["solver"]["threads"]) != 1:
        raise ValueError("Phase 6 family runs require Threads=1")
    protocol = config["family_pilot_protocol"]
    if protocol["protocol_id"] != "phase6_family_pilot_v1_0":
        raise ValueError("unsupported Phase 6 family pilot protocol")
    if tuple(protocol["execution_order"]) != FAMILIES:
        raise ValueError("family pilot execution order must be E1,E2,E4,E5")
    for family in FAMILIES:
        if float(config["runner"]["plan_wall_seconds"][family]) <= 0.0:
            raise ValueError(f"{family} plan wall limit must be positive")
    return config


def family_runner_config_sha256(path: Path) -> str:
    return sha256_lf_text_file(path)


def _budget_for_factor(
    matrix: Mapping[str, Any],
    *,
    matrix_path: Path,
    tier_id: str,
    factor: float,
) -> tuple[int, float]:
    factors = tuple(
        float(value) for value in matrix["budget_plan"]["formal_factors"]
    )
    matches = [
        index for index, value in enumerate(factors)
        if abs(value - float(factor)) <= 1.0e-12
    ]
    if len(matches) != 1:
        raise ValueError(f"budget factor {factor} is not uniquely frozen")
    budgets = budget_values_for_tier(
        matrix,
        tier_id,
        matrix_path=matrix_path,
    )
    index = matches[0]
    return index, float(budgets[index])


def resolve_family_pilot_plans(
    matrix: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    matrix_path: Path,
    family: str,
    seed: int,
) -> tuple[dict[str, Any], ...]:
    """Resolve deterministic pilot work for one family and pilot seed."""

    normalized = family.upper()
    if normalized not in FAMILIES:
        raise ValueError(f"unsupported family: {family}")
    specification = config["family_pilot_protocol"][normalized]
    tier_id = str(specification["tier"])
    validate_execution_seed(
        matrix,
        tier_id=tier_id,
        seed=int(seed),
        execution_mode="pilot",
    )
    budget_index, budget = _budget_for_factor(
        matrix,
        matrix_path=matrix_path,
        tier_id=tier_id,
        factor=float(specification["budget_factor"]),
    )
    base = {
        "family": normalized,
        "tier_id": tier_id,
        "training_seed": int(seed),
        "budget_index": budget_index,
        "budget_factor": float(specification["budget_factor"]),
        "budget": budget,
    }
    if normalized == "E1":
        return (
            {
                **base,
                "plan_id": f"E1P_{tier_id}_{seed}_b{budget_index:02d}",
            },
        )
    if normalized == "E2":
        return tuple(
            {
                **base,
                "plan_id": (
                    f"E2P_{tier_id}_{seed}_b{budget_index:02d}_{policy}"
                ),
                "policy": str(policy),
            }
            for policy in specification["policies"]
        )
    if normalized == "E4":
        return tuple(
            {
                **base,
                "plan_id": (
                    f"E4P_{tier_id}_{seed}_b{budget_index:02d}_{policy}"
                ),
                "test_seed": int(seed)
                + int(specification["independent_test_seed_offset"]),
                "policy": str(policy),
                "source_e2_plan_id": (
                    f"E2P_{tier_id}_{seed}_b{budget_index:02d}_{policy}"
                ),
            }
            for policy in specification["policies"]
        )
    configurations = {
        row["configuration_id"]: row
        for row in sensitivity_configurations(matrix)
    }
    return tuple(
        {
            **base,
            **configurations[str(configuration_id)],
            "plan_id": f"E5P_{tier_id}_{seed}_{configuration_id}",
        }
        for configuration_id in specification["configurations"]
    )


def _find_e2_source_plan(
    *,
    output_root: Path,
    source_plan_id: str,
    scientific_hash: str,
    family_config_hash: str,
    family_code_hash: str,
    environment_hash: str,
) -> tuple[Path, str]:
    registry_path = (
        output_root
        / "experiments"
        / "phase6"
        / "family_run_registry.csv"
    )
    if not registry_path.exists():
        raise FileNotFoundError("E4 requires a completed E2 family pilot")
    with registry_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    matching = [
        row for row in rows
        if (
            row.get("family") == "E2"
            and row.get("status") == "optimal"
            and row.get("scientific_config_sha256") == scientific_hash
            and row.get("family_config_sha256") == family_config_hash
            and row.get("family_code_sha256") == family_code_hash
            and row.get("environment_sha256") == environment_hash
            and not row.get("parent_run_id", "").strip()
        )
    ]
    candidates: list[tuple[Path, str]] = []
    for row in matching:
        try:
            payload, _ = validate_family_run_artifacts(row)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        for record in payload.get("plans", ()):
            if (
                record.get("plan_id") == source_plan_id
                and record.get("status") == "optimal"
                and record.get("result_path")
            ):
                try:
                    load_verified_plan_result(record)
                except (
                    OSError,
                    ValueError,
                    KeyError,
                    json.JSONDecodeError,
                ):
                    continue
                candidates.append(
                    (
                        Path(record["result_path"]),
                        str(record["result_sha256"]),
                    )
                )
    unique = sorted(set(candidates))
    if len(unique) != 1:
        raise ValueError(
            f"E4 source plan {source_plan_id!r} resolved to "
            f"{len(unique)} artifacts"
        )
    return unique[0]


def _validate_family_pilot_order(
    *,
    output_root: Path,
    config: Mapping[str, Any],
    family: str,
    seed: int,
    scientific_hash: str,
    family_config_hash: str,
    family_code_hash: str,
    environment_hash: str,
) -> None:
    """Require earlier pilot families for the same seed and fingerprints."""

    order = tuple(config["family_pilot_protocol"]["execution_order"])
    required = order[: order.index(family)]
    if not required:
        return
    registry_path = (
        output_root
        / "experiments"
        / "phase6"
        / "family_run_registry.csv"
    )
    if not registry_path.exists():
        raise ValueError(
            f"{family} pilot requires completed predecessors {required}"
        )
    with registry_path.open(
        "r", encoding="utf-8-sig", newline=""
    ) as handle:
        rows = list(csv.DictReader(handle))
    completed: set[str] = set()
    for row in rows:
        if not (
            row.get("family") in required
            and row.get("execution_mode") == "pilot"
            and int(row.get("seed") or -1) == int(seed)
            and row.get("status") == "optimal"
            and int(row.get("completed_work_units") or -1)
            == int(row.get("planned_work_units") or -2)
            and row.get("scientific_config_sha256") == scientific_hash
            and row.get("family_config_sha256") == family_config_hash
            and row.get("family_code_sha256") == family_code_hash
            and row.get("environment_sha256") == environment_hash
            and not row.get("parent_run_id", "").strip()
        ):
            continue
        try:
            validate_family_run_artifacts(row)
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            continue
        completed.add(str(row["family"]))
    missing = [name for name in required if name not in completed]
    if missing:
        raise ValueError(
            f"{family} pilot requires prior optimal families {missing} "
            f"for seed {seed}"
        )


def _default_family_worker(
    request: dict[str, Any],
    timeout_seconds: float,
    work_directory: Path,
) -> dict[str, Any]:
    """Execute one family plan in a monitored subprocess."""

    work_directory.mkdir(parents=True, exist_ok=True)
    plan_id = str(request["plan"]["plan_id"])
    request_path = work_directory / f"{plan_id}_request.json"
    result_path = work_directory / f"{plan_id}_result.json"
    progress_path = work_directory / f"{plan_id}_progress.json"
    request = {**request, "progress_path": str(progress_path)}
    _atomic_write_json(request_path, request)
    if result_path.exists():
        result_path.unlink()
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
        "src.phase6_family_worker",
        "--request",
        str(request_path),
        "--result",
        str(result_path),
    ]
    process = subprocess.Popen(
        command,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
    )
    monitored = psutil.Process(process.pid)
    started = perf_counter()
    peak_bytes = 0
    timed_out = False
    while process.poll() is None:
        if perf_counter() - started > timeout_seconds:
            timed_out = True
            try:
                descendants = monitored.children(recursive=True)
                for child in reversed(descendants):
                    child.kill()
                monitored.kill()
                psutil.wait_procs([*descendants, monitored], timeout=5.0)
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
        if (
            progress_path.exists()
            and progress_path.stat().st_size <= 2 * 1024 * 1024
        ):
            try:
                partial_progress = json.loads(
                    progress_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                partial_progress = None
        payload = {
            "plan_id": plan_id,
            "status": "plan_wall_timeout",
            "wall_seconds": elapsed,
            "peak_memory_mb": peak_bytes / (1024.0**2),
            "failure": {
                "stage": "external_plan_watchdog",
                "message": (
                    f"plan exceeded family wall limit {timeout_seconds:.6f}s"
                ),
            },
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-4000:],
            "partial_progress": partial_progress,
        }
        _atomic_write_json(result_path, payload)
        return {**payload, "result_path": str(result_path)}
    if not result_path.exists():
        payload = {
            "plan_id": plan_id,
            "status": "worker_result_missing",
            "wall_seconds": elapsed,
            "peak_memory_mb": peak_bytes / (1024.0**2),
            "failure": {
                "stage": "worker_result_load",
                "message": f"worker exited {process.returncode} without result",
            },
            "stdout_tail": stdout[-2000:],
            "stderr_tail": stderr[-4000:],
        }
        _atomic_write_json(result_path, payload)
        return {**payload, "result_path": str(result_path)}
    try:
        payload = json.loads(result_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        payload = {
            "plan_id": plan_id,
            "status": "worker_result_unreadable",
            "failure": {
                "stage": "worker_result_load",
                "message": f"{type(exc).__name__}: {exc}",
            },
        }
    payload.update(
        {
            "wall_seconds": elapsed,
            "peak_memory_mb": peak_bytes / (1024.0**2),
            "return_code": process.returncode,
            "result_path": str(result_path),
        }
    )
    _atomic_write_json(result_path, payload)
    return payload


def _validate_e2_dominance(
    plans: list[dict[str, Any]],
    matrix: Mapping[str, Any],
) -> None:
    by_policy = {
        row["policy"]: row
        for row in plans
        if row.get("status") == "optimal"
    }
    if set(by_policy) != set(matrix["model_comparison"]["policies"]):
        raise ValueError("E2 run does not contain all six optimal policies")
    endogenous_evaluation = by_policy["endogenous_reserve"].get(
        "exact_training_evaluation"
    ) or {}
    if (
        endogenous_evaluation.get("status") != "optimal"
        or by_policy["endogenous_reserve"].get("robust_objective") is None
    ):
        raise ValueError(
            "endogenous reserve policy lacks an optimal exact evaluation"
        )
    endogenous = float(by_policy["endogenous_reserve"]["robust_objective"])
    fixed_objectives = []
    for policy in POLICY_RATIOS:
        evaluation = by_policy[policy].get("exact_training_evaluation") or {}
        objective = by_policy[policy].get("robust_objective")
        if evaluation.get("status") != "optimal" or objective is None:
            raise ValueError(
                f"fixed reserve policy {policy} lacks an optimal exact "
                "evaluation"
            )
        fixed_objectives.append(float(objective))
    fixed = min(fixed_objectives)
    gate = matrix["model_comparison"]["endogenous_dominance_check"]
    limit = float(gate["tolerance_absolute"]) + float(
        gate["tolerance_relative"]
    ) * max(1.0, abs(fixed))
    if endogenous > fixed + limit:
        raise ValueError(
            f"endogenous objective {endogenous} exceeds fixed best {fixed}"
        )


def validate_family_formal_projection(
    projection_path: Path,
    *,
    matrix: Mapping[str, Any],
    scientific_hash: str,
    family_config_hash: str,
    family_code_hash: str,
    environment_hash: str,
) -> dict[str, Any]:
    """Block family formal runs before any scenario generation."""

    if matrix.get("status") != "frozen_for_formal_execution":
        raise Phase6ProtocolError("family formal execution matrix is not frozen")
    if not projection_path.exists():
        raise ValueError("family formal execution requires a projection")
    payload = json.loads(projection_path.read_text(encoding="utf-8"))
    expected = {
        "scientific_config_sha256": scientific_hash,
        "family_config_sha256": family_config_hash,
        "family_code_sha256": family_code_hash,
        "family_environment_sha256": environment_hash,
    }
    mismatches = {
        key: {"expected": value, "actual": payload.get(key)}
        for key, value in expected.items()
        if payload.get(key) != value
    }
    if mismatches:
        raise ValueError(f"family projection fingerprint mismatch: {mismatches}")
    if (
        payload.get("status") != "passed"
        or payload.get("compute_gate_passed") is not True
        or payload.get("formal_execution_authorized") is not True
    ):
        raise ValueError("family formal projection has not passed")
    return payload


def run_family_sequence(
    *,
    matrix_path: Path,
    family_config_path: Path,
    output_root: Path,
    family: str,
    seed: int,
    execution_mode: str,
    run_id: str,
    tier_id: str | None = None,
    parent_run_id: str | None = None,
    worker: FamilyWorker | None = None,
) -> dict[str, Any]:
    """Run one immutable family sequence and retain all plan statuses."""

    normalized = family.upper()
    if normalized not in FAMILIES:
        raise ValueError(f"unsupported family: {family}")
    project_root = matrix_path.resolve().parent.parent
    if execution_mode in ("pilot", "formal"):
        validate_execution_source(
            project_root,
            required_tracked_paths=(
                matrix_path,
                family_config_path.resolve(),
                project_root / "requirements-gurobi-lock.txt",
                *(project_root / path for path in FAMILY_COMPONENT_FILES),
            ),
        )
    matrix = load_phase6_matrix(matrix_path)
    config = load_family_runner_config(family_config_path)
    validate_gurobi_runtime()
    locked = validate_locked_environment(project_root)
    science_hash = scientific_config_sha256(matrix)
    config_hash = family_runner_config_sha256(family_config_path)
    code_hash = family_code_sha256(project_root)
    environment_hash = environment_sha256(locked)
    if execution_mode == "pilot":
        validate_matrix_execution_status(
            matrix,
            execution_mode="pilot",
        )
        _validate_family_pilot_order(
            output_root=output_root,
            config=config,
            family=normalized,
            seed=int(seed),
            scientific_hash=science_hash,
            family_config_hash=config_hash,
            family_code_hash=code_hash,
            environment_hash=environment_hash,
        )
        plans = list(
            resolve_family_pilot_plans(
                matrix,
                config,
                matrix_path=matrix_path,
                family=normalized,
                seed=seed,
            )
        )
    elif execution_mode == "development":
        development = int(matrix["seed_plan"]["development_seed"])
        if int(seed) != development:
            raise Phase6ProtocolError("development family seed is invalid")
        pilot_matrix = dict(matrix)
        pilot_matrix["seed_plan"] = {
            **matrix["seed_plan"],
            "pilot_training_seeds": [development],
        }
        plans = list(
            resolve_family_pilot_plans(
                pilot_matrix,
                config,
                matrix_path=matrix_path,
                family=normalized,
                seed=development,
            )
        )
    elif execution_mode == "formal":
        validate_family_formal_projection(
            output_root
            / "experiments"
            / "phase6"
            / "pilot_throughput_projection.json",
            matrix=matrix,
            scientific_hash=science_hash,
            family_config_hash=config_hash,
            family_code_hash=code_hash,
            environment_hash=environment_hash,
        )
        all_plans = enumerate_family_plans(
            matrix,
            normalized,
            matrix_path=matrix_path,
        )
        if normalized == "E1":
            if tier_id is None:
                raise ValueError("formal E1 requires an explicit tier_id")
            selected_tier = str(tier_id)
        else:
            allowed_tiers = {
                str(plan["tier_id"]) for plan in all_plans
            }
            if tier_id is not None and str(tier_id) not in allowed_tiers:
                raise ValueError(
                    f"{normalized} does not contain tier {tier_id!r}"
                )
            if len(allowed_tiers) != 1:
                raise ValueError(
                    f"{normalized} formal tier is not uniquely defined"
                )
            selected_tier = next(iter(allowed_tiers))
        validate_execution_seed(
            matrix,
            tier_id=selected_tier,
            seed=int(seed),
            execution_mode="formal",
        )
        plans = [
            plan
            for plan in all_plans
            if (
                str(plan["tier_id"]) == selected_tier
                and int(plan["training_seed"]) == int(seed)
            )
        ]
        if not plans:
            raise ValueError(
                f"no formal {normalized} plans resolved for "
                f"{selected_tier} seed {seed}"
            )
    else:
        raise ValueError("execution_mode must be development, pilot, or formal")

    base = output_root / "experiments" / "phase6"
    run_directory = base / "family_runs" / run_id
    result_path = run_directory / "result.json"
    checkpoint_path = run_directory / "checkpoint.json"
    status_path = run_directory / "status_summary.json"
    lock_path = run_directory / ".run.lock"
    run_directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(
        lock_path,
        timeout_seconds=RUN_LOCK_TIMEOUT_SECONDS,
    ):
        existing_artifacts = [
            path
            for path in run_directory.iterdir()
            if path.name != ".run.lock"
        ]
        if existing_artifacts:
            raise ValueError(
                f"family run_id already started and is immutable: {run_id}"
            )
        started_at = _utc_now()
        started = perf_counter()
        records: list[dict[str, Any]] = []
        failure: dict[str, Any] | None = None
        executor = worker or _default_family_worker

        def save(status: str) -> None:
            payload = {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "family": normalized,
                "execution_mode": execution_mode,
                "status": status,
                "planned_work_units": len(plans),
                "completed_work_units": sum(
                    row.get("status") == "optimal" for row in records
                ),
                "plans": records,
                "failure": failure,
                "updated_at_utc": _utc_now(),
            }
            _atomic_write_json(checkpoint_path, payload)
            _atomic_write_json(
                status_path,
                {
                    "run_id": payload["run_id"],
                    "family": payload["family"],
                    "execution_mode": payload["execution_mode"],
                    "status": payload["status"],
                    "planned_work_units": payload["planned_work_units"],
                    "completed_work_units": payload[
                        "completed_work_units"
                    ],
                    "failure": compact_failure(payload["failure"]),
                    "updated_at_utc": payload["updated_at_utc"],
                },
            )

        save("running")
        for index, plan in enumerate(plans):
            request = {
                "matrix_path": str(matrix_path.resolve()),
                "output_root": str(output_root.resolve()),
                "family_config_path": str(family_config_path.resolve()),
                "plan": plan,
                "solver": config["solver"],
                "ccg": config["ccg"],
            }
            if normalized == "E4":
                source_path, source_hash = _find_e2_source_plan(
                    output_root=output_root,
                    source_plan_id=str(plan["source_e2_plan_id"]),
                    scientific_hash=science_hash,
                    family_config_hash=config_hash,
                    family_code_hash=code_hash,
                    environment_hash=environment_hash,
                )
                request["source_plan_path"] = str(source_path)
                request["source_plan_sha256"] = source_hash
            payload = executor(
                request,
                float(
                    config["runner"]["plan_wall_seconds"][normalized]
                ),
                run_directory / "workers",
            )
            plan_result_path = payload.get("result_path")
            plan_result_hash = None
            if plan_result_path:
                try:
                    plan_result_hash = sha256_file(
                        Path(str(plan_result_path))
                    )
                except (OSError, ValueError) as exc:
                    payload = {
                        **payload,
                        "status": "worker_artifact_invalid",
                        "failure": {
                            "stage": "worker_artifact_validation",
                            "message": f"{type(exc).__name__}: {exc}",
                        },
                    }
            elif payload.get("status") == "optimal":
                payload = {
                    **payload,
                    "status": "worker_artifact_invalid",
                    "failure": {
                        "stage": "worker_artifact_validation",
                        "message": "worker result path is missing",
                    },
                }
            record = {
                "plan_index": index,
                "plan_id": plan["plan_id"],
                "policy": plan.get("policy"),
                "configuration_id": plan.get("configuration_id"),
                "status": payload["status"],
                "wall_seconds": payload.get("wall_seconds"),
                "peak_memory_mb": payload.get("peak_memory_mb"),
                "robust_objective": payload.get("robust_objective"),
                "result_path": payload.get("result_path"),
                "result_sha256": plan_result_hash,
                "failure": payload.get("failure"),
            }
            records.append(record)
            if payload["status"] != "optimal":
                failure = {
                    "stage": "plan_execution",
                    "plan_index": index,
                    "plan_id": plan["plan_id"],
                    "status": payload["status"],
                    "message": (
                        (payload.get("failure") or {}).get("message")
                        or "family plan did not solve optimally"
                    ),
                }
                for skipped_index, skipped in enumerate(
                    plans[index + 1 :],
                    start=index + 1,
                ):
                    records.append(
                        {
                            "plan_index": skipped_index,
                            "plan_id": skipped["plan_id"],
                            "policy": skipped.get("policy"),
                            "configuration_id": skipped.get(
                                "configuration_id"
                            ),
                            "status": "not_run_after_family_failure",
                            "wall_seconds": None,
                            "peak_memory_mb": None,
                            "robust_objective": None,
                            "result_path": None,
                            "result_sha256": None,
                            "failure": None,
                        }
                    )
                break
            save("running")
        if failure is None and normalized == "E2":
            try:
                full_results = [
                    load_verified_plan_result(row)
                    for row in records
                ]
                _validate_e2_dominance(full_results, matrix)
            except Exception as exc:
                failure = {
                    "stage": "endogenous_dominance",
                    "status": "structural_gate_failure",
                    "message": f"{type(exc).__name__}: {exc}",
                }
        status = "optimal" if failure is None else str(failure["status"])
        wall_seconds = perf_counter() - started
        result = {
            "run_id": run_id,
            "parent_run_id": parent_run_id,
            "family": normalized,
            "execution_mode": execution_mode,
            "tier_ids": sorted(
                {str(plan["tier_id"]) for plan in plans}
            ),
            "seed": int(seed),
            "status": status,
            "finalized": True,
            "planned_work_units": len(plans),
            "completed_work_units": sum(
                row.get("status") == "optimal" for row in records
            ),
            "wall_seconds": wall_seconds,
            "peak_memory_mb": max(
                (
                    float(row["peak_memory_mb"])
                    for row in records
                    if row.get("peak_memory_mb") is not None
                ),
                default=0.0,
            ),
            "plans": records,
            "failure": failure,
            "started_at_utc": started_at,
            "finished_at_utc": _utc_now(),
            "fingerprints": {
                "scientific_config_sha256": science_hash,
                "family_config_sha256": config_hash,
                "family_code_sha256": code_hash,
                "environment_sha256": environment_hash,
            },
        }
        save(status)
        _atomic_write_json(result_path, result)
        manifest_path = run_directory / "manifest.json"
        _atomic_write_json(
            manifest_path,
            {
                **result["fingerprints"],
                "artifact_state": "finalized",
                "run_id": run_id,
                "family": normalized,
                "matrix_path": str(matrix_path.resolve()),
                "matrix_sha256": sha256_lf_text_file(matrix_path),
                "family_config_path": str(family_config_path.resolve()),
                "result_path": str(result_path.resolve()),
                "result_sha256": sha256_file(result_path),
                **capture_runtime_context(
                    solver_preference=("gurobi",),
                    project_root=project_root,
                    solver_threads=1,
                ),
                "locked_environment": locked,
            },
        )
        upsert_family_registry(
            output_root,
            {
                "run_id": run_id,
                "parent_run_id": parent_run_id,
                "family": normalized,
                "execution_mode": execution_mode,
                "tier_id": ",".join(result["tier_ids"]),
                "seed": int(seed),
                "status": status,
                "planned_work_units": len(plans),
                "completed_work_units": result["completed_work_units"],
                "wall_seconds": wall_seconds,
                "peak_memory_mb": result["peak_memory_mb"],
                "scientific_config_sha256": science_hash,
                "family_config_sha256": config_hash,
                "family_code_sha256": code_hash,
                "environment_sha256": environment_hash,
                "started_at_utc": started_at,
                "updated_at_utc": result["finished_at_utc"],
                "failure_stage": (
                    failure.get("stage") if failure is not None else None
                ),
                "failure_message": (
                    (compact_failure(failure) or {}).get("message")
                ),
                "result_path": str(result_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
            },
        )
        returned = dict(result)
        try:
            projection = update_family_projection(
                output_root=output_root,
                matrix=matrix,
                scientific_config_hash=science_hash,
                family_config_hash=config_hash,
                family_code_hash=code_hash,
                environment_hash=environment_hash,
            )
            returned["projection_status"] = projection["status"]
            returned["formal_execution_authorized"] = projection[
                "formal_execution_authorized"
            ]
        except (OSError, ValueError, KeyError) as exc:
            returned["projection_status"] = "e3_projection_unavailable"
            returned["formal_execution_authorized"] = False
            returned["projection_message"] = f"{type(exc).__name__}: {exc}"
        return returned

"""Guarded formal executor for the frozen M2 algorithm-performance matrix."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping, Sequence

import numpy as np

from .model_common import validate_gurobi_runtime
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_json
from .phase6_locking import exclusive_file_lock
from .phase6_m2 import M2_E3_COMPONENT_FILES, M2_FAMILY_COMPONENT_FILES
from .phase6_m2_algorithm_performance import (
    SAFE_RUN_ID, _build_transferred_state, _canonical_sha, _component_sha,
    _confirmation_config, _load_yaml, _manifest, _objective_tolerance,
    _registry, _validate_formal_baseline_before_generation,
    _validate_synchronized_main, _validate_worker_evidence, _worker_executor,
    utc_now,
)
from .phase6_protocol import load_phase6_matrix
from .reproducibility import sha256_file, validate_execution_source


NAMESPACE = "phase6_m2_algorithm_performance_formal_v1_0"
PENDING_STATUS = "formal_runner_frozen_pending_authorization"
READY_STATUS = "frozen_for_formal_algorithm_performance_execution"
RUNNER_PATH = "configs/phase6_m2_algorithm_performance_formal_runner_v1_0.yaml"
APPROVAL_PATH = "configs/phase6_m2_algorithm_performance_formal_approval_v1_0.yaml"
DESIGN_PATH = "configs/phase6_m2_algorithm_performance_design_v1_0.yaml"
PILOT_AUDIT_PATH = "docs/handoffs/2026-08-25_phase6_m2_algorithm_performance_pilot_results_v1_1_audit.json"
PILOT_AUDIT_SHA256 = "d9ef03ea75e4cd7f5a2c0c988fe37adada4ef9ae9f94114133ff3aaeef0dfb3d"
FORMAL_FILES = (
    "src/phase6_m2_algorithm_performance_formal.py",
    "src/phase6_m2_algorithm_performance_worker.py",
    "src/run_phase6_m2_algorithm_performance_formal.py",
    "src/phase6_m2_algorithm_performance_formal_status.py",
    DESIGN_PATH, RUNNER_PATH,
)
E3_FILES = tuple(dict.fromkeys((*M2_E3_COMPONENT_FILES, *FORMAL_FILES)))
FAMILY_FILES = tuple(dict.fromkeys((*M2_FAMILY_COMPONENT_FILES, *FORMAL_FILES)))
WorkerExecutor = Callable[[dict[str, Any], float, Path], dict[str, Any]]
COMPONENT_FIELDS = (
    "latent_draw_sha256", "demand_sha256", "fulfillment_sha256",
    "emergency_price_sha256", "emergency_supply_sha256",
    "scenario_order_sha256",
)
CRN_FIELDS = tuple(field for field in COMPONENT_FIELDS if field != "fulfillment_sha256")


@dataclass(frozen=True)
class FormalCase:
    case_id: str
    seed: int
    profile_id: str


class FormalEvidenceError(RuntimeError):
    """An optimal-looking worker/result failed frozen evidence validation."""


def build_formal_cases(design: Mapping[str, Any]) -> tuple[FormalCase, ...]:
    seeds = tuple(int(v) for v in design["seed_protocol"]["formal_performance_seeds"])
    profiles = tuple(str(v) for v in design["profiles"])
    cases = tuple(FormalCase(
        case_id=f"M2AP2_formal_seed{seed}_profile{profile}",
        seed=seed, profile_id=profile,
    ) for seed in seeds for profile in profiles)
    if seeds != tuple(range(2026091101, 2026091111)) or profiles != ("C0", "T03"):
        raise ValueError("formal seed/profile matrix differs from frozen design")
    if len(cases) != 20:
        raise ValueError("formal matrix must contain 20 primary sequences")
    return cases


def formal_fingerprints(root: Path, runner_path: Path) -> dict[str, str]:
    from .phase6_m2_algorithm_performance import algorithm_performance_fingerprints
    scientific = algorithm_performance_fingerprints(root, root / DESIGN_PATH, runner_path)["scientific_config_sha256"]
    return {
        "scientific_config_sha256": scientific,
        "e3_component_sha256": _component_sha(root, E3_FILES),
        "family_component_sha256": _component_sha(root, FAMILY_FILES),
        "runner_config_sha256": sha256_file(runner_path),
        "environment_sha256": environment_sha256(validate_locked_environment(root)),
        "algorithm_performance_orchestrator_sha256": _component_sha(root, FORMAL_FILES),
    }


def _validate_pilot_evidence(root: Path) -> None:
    path = root / PILOT_AUDIT_PATH
    if sha256_file(path) != PILOT_AUDIT_SHA256:
        raise RuntimeError("reviewed PR #83 pilot audit hash mismatch")
    audit = json.loads(path.read_text(encoding="utf-8"))
    aggregate = audit["aggregate"]
    if not (
        audit["status"] == "passed"
        and aggregate["completed_primary_sequence_count"] == 6
        and aggregate["completed_budget_pair_count"] == 12
        and aggregate["completed_algorithm_solve_count"] == 36
        and aggregate["pilot_compute_gate_passed"] is True
        and aggregate["formal_authorized"] is False
    ):
        raise RuntimeError("reviewed pilot evidence does not pass its compute gate")
    for field in (
        "missing_case_ids", "duplicate_case_ids", "failed_primary_run_ids",
        "invalid_primary_runs", "diagnostic_run_ids", "common_random_number_mismatches",
    ):
        if aggregate[field]:
            raise RuntimeError(f"reviewed pilot evidence contains exceptions: {field}")


def validate_static_freeze(root: Path, runner_path: Path, approval_path: Path) -> dict[str, Any]:
    runner, approval = _load_yaml(runner_path), _load_yaml(approval_path)
    design = _load_yaml(root / str(runner["design_config"]))
    if runner.get("namespace") != NAMESPACE or approval.get("runner_namespace") != NAMESPACE:
        raise RuntimeError("formal namespace mismatch")
    if tuple(float(v) for v in design["budget_sequence"]["betas"]) != (1.1, 1.3):
        raise RuntimeError("formal budget sequence changed")
    formal = design["formal_matrix"]
    expected = {
        "primary_sequence_count": 20, "seed_count": 10, "profile_count": 2,
        "budget_count": 2, "algorithm_count": 2,
        "technical_repetitions_per_algorithm_budget": 3,
        "budget_pair_count": 40, "planned_algorithm_execution_count": 240,
    }
    if any(formal.get(k) != v for k, v in expected.items()):
        raise RuntimeError("formal 20/40/240 matrix changed")
    if runner["execution"] != {
        "strictly_serial": True, "complete_primary_batch_required": True,
        "explicit_cli_authorization_required": True, "immutable_run_ids": True,
        "failed_primary_permanently_blocks_gate": True,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
        "formal_execution_implemented": True, "formal_authorized": False,
        "primary_sequence_count": 20, "budget_pair_count": 40,
        "algorithm_execution_count": 240,
    }:
        raise RuntimeError("formal execution protocol changed")
    if runner["solver"] != {
        "preference": ["gurobi"], "interface": "gurobi_direct",
        "optimizer_version": "13.0.2", "gurobipy_version": "13.0.2",
        "threads": 1, "feasibility_tolerance": 1.0e-7,
        "optimality_tolerance": 1.0e-7, "call_time_limit_seconds": 120,
    }:
        raise RuntimeError("formal solver identity changed")
    if runner["limits"] != {"worker_wall_seconds": 180, "threads": 1}:
        raise RuntimeError("formal execution limits changed")
    if runner["objective_consistency"] != {
        "source": "frozen_M2_scientific_objective_consistency_tolerance",
        "absolute_tolerance": 1.0e-5, "relative_tolerance": 1.0e-7,
    }:
        raise RuntimeError("formal objective-consistency protocol changed")
    _validate_pilot_evidence(root)
    return {"runner": runner, "approval": approval, "design": design, "cases": build_formal_cases(design)}


def validate_preflight(
    root: Path, runner_path: Path, approval_path: Path, *, require_authorization: bool,
) -> dict[str, Any]:
    context = validate_static_freeze(root, runner_path, approval_path)
    runner, approval = context["runner"], context["approval"]
    if require_authorization:
        if approval.get("status") != READY_STATUS or approval.get("formal_authorized") is not True:
            raise RuntimeError("formal M2 algorithm performance is not authorized")
    elif approval.get("status") not in {PENDING_STATUS, READY_STATUS}:
        raise RuntimeError("unexpected formal approval lifecycle")
    false_scope = (
        "pilot_additional_runs_authorized", "M0_E3_additional_runs_authorized",
        "M2_mechanism_additional_runs_authorized", "M2_OOS_additional_runs_authorized",
        "M2_1_additional_runs_authorized",
    )
    if any(approval.get(field) is not False for field in false_scope):
        raise RuntimeError("formal approval exceeds reviewed scope")
    synchronized = None
    if require_authorization:
        synchronized = _validate_synchronized_main(
            root, reviewed_runner_merge_commit=str(approval.get("reviewed_runner_commit") or ""),
        )
    matrix = load_phase6_matrix(root / runner["base_matrix"])
    confirmation = _confirmation_config(root)
    formal_like = {
        "scientific_model": context["design"]["scientific_model"],
        "profiles": context["design"]["profiles"],
        "mechanism_experiment": {
            "primary_track": {"beta": 1.1, "budget": 2571.372016574617},
            "secondary_track": {"beta": 1.3, "budget": 3038.894201406366},
        },
    }
    for beta in (1.1, 1.3):
        _validate_formal_baseline_before_generation(matrix, formal_like, confirmation, beta=beta, scenario_count=100)
    required = tuple(root / value for value in (*FORMAL_FILES, runner["base_matrix"], str(approval_path.relative_to(root)), PILOT_AUDIT_PATH))
    validate_execution_source(root, required_tracked_paths=required)
    actual = formal_fingerprints(root, runner_path)
    if require_authorization and approval.get("approved_fingerprints") != actual:
        raise RuntimeError("approved formal fingerprints differ")
    artifacts = {
        "runner_config": runner_path, "orchestrator_module": root / FORMAL_FILES[0],
        "worker_module": root / FORMAL_FILES[1], "cli": root / FORMAL_FILES[2],
        "status_module": root / FORMAL_FILES[3],
    }
    if require_authorization:
        for name, path in artifacts.items():
            if approval.get("artifact_sha256", {}).get(name) != sha256_file(path):
                raise RuntimeError(f"approved formal artifact differs: {name}")
        validate_gurobi_runtime()
    context.update(matrix=matrix, fingerprints=actual, synchronized_main=synchronized)
    return context


def _finite(value: Any, *, name: str, nonnegative: bool = False) -> float:
    numeric = float(value)
    if not math.isfinite(numeric) or (nonnegative and numeric < 0.0):
        raise ValueError(f"{name} must be finite" + (" and nonnegative" if nonnegative else ""))
    return numeric


def _validate_worker_identity(
    row: Mapping[str, Any], *, case: FormalCase, algorithm: str,
    repetition: int, beta: float, budget: float, budget_index: int,
) -> None:
    if (
        row.get("status") != "optimal"
        or row.get("algorithm") != algorithm
        or int(row.get("repetition", -1)) != repetition
        or int(row.get("seed", -1)) != case.seed
        or row.get("profile_id") != case.profile_id
        or not math.isclose(float(row.get("beta", math.nan)), beta, rel_tol=0.0, abs_tol=1.0e-12)
        or not math.isclose(float(row.get("budget", math.nan)), budget, rel_tol=0.0, abs_tol=1.0e-9)
        or int(row.get("scenario_count", -1)) != 100
    ):
        raise ValueError("formal worker identity differs from its frozen request")
    joint = str(row.get("joint_scenario_set_sha256", ""))
    components = row.get("component_set_sha256", {})
    if len(joint) != 64 or set(components) != set(COMPONENT_FIELDS) or any(
        len(str(components[field])) != 64 for field in COMPONENT_FIELDS
    ):
        raise ValueError("formal worker scenario identity is incomplete")
    has_source = row.get("transfer_source_state_sha256") is not None
    transfer_names = list(row.get("transferred_exact_scenarios", []))
    transfer_count = int(row.get("transferred_exact_scenario_count", -1))
    reuse_rate = _finite(
        row.get("transferred_scenario_reuse_rate", math.nan),
        name="transferred scenario reuse rate", nonnegative=True,
    )
    if algorithm == "cold" or budget_index == 0:
        if (
            has_source or row.get("transfer_source_budget") is not None
            or transfer_names or transfer_count != 0 or reuse_rate != 0.0
        ):
            raise ValueError("cold and first-budget warm executions may not claim transfer")


def _method_metrics(row: Mapping[str, Any]) -> dict[str, Any]:
    ccg = row.get("ccg_result")
    if not isinstance(ccg, Mapping):
        raise ValueError("formal C&CG evidence is missing")
    objective = _finite(row["objective"], name="objective")
    lower = _finite(ccg["lower_bound"], name="lower bound")
    upper = _finite(ccg["upper_bound"], name="upper bound")
    gap = _finite(ccg["gap"], name="optimality gap", nonnegative=True)
    iterations = int(ccg["iterations"])
    if iterations <= 0:
        raise ValueError("iterations must be positive")
    if ccg.get("termination_status") != "optimal" or ccg.get("converged") is not True:
        raise ValueError("formal C&CG termination evidence is not optimal")
    if ccg.get("solver") != "gurobi_direct":
        raise ValueError("formal C&CG solver identity mismatch")
    master = _finite(ccg["master_runtime_seconds"], name="master runtime", nonnegative=True)
    oracle = _finite(ccg["oracle_runtime_seconds"], name="oracle runtime", nonnegative=True)
    wall = _finite(row["subprocess_wall_seconds"], name="subprocess wall time")
    memory = _finite(row["sampled_peak_RSS_MiB"], name="sampled peak RSS", nonnegative=True)
    initial = list(row.get("initial_scenarios", []))
    final = list(ccg.get("final_scenario_set", []))
    if wall <= 0.0:
        raise ValueError("subprocess wall time must be positive")
    if (
        lower > upper + 1.0e-9
        or objective < lower - 1.0e-6
        or objective > upper + 1.0e-6
        or not initial or not final
    ):
        raise ValueError("formal scenario-pool evidence is incomplete")
    return {
        "objective": objective, "lower_bound": lower, "upper_bound": upper,
        "optimality_gap": gap, "iterations": iterations,
        "master_solve_count": iterations, "oracle_call_count": iterations * 100,
        "master_runtime_seconds": master, "oracle_runtime_seconds": oracle,
        "subprocess_wall_seconds": wall, "sampled_peak_RSS_MiB": memory,
        "initial_scenario_pool_size": len(initial),
        "final_scenario_pool_size": len(final),
        "transferred_exact_scenario_count": int(row["transferred_exact_scenario_count"]),
        "transferred_scenario_reuse_rate": float(row["transferred_scenario_reuse_rate"]),
        "transferred_scenarios_becoming_active_or_worst_count": int(
            row["transferred_scenarios_becoming_active_or_worst_count"]
        ),
        "joint_scenario_set_sha256": str(row["joint_scenario_set_sha256"]),
        "component_set_sha256": dict(row["component_set_sha256"]),
    }


def _validate_second_budget_transfer(
    row: Mapping[str, Any], prior: Mapping[str, Any], *,
    source_budget: float, active_tolerance: float,
) -> None:
    if row.get("transfer_source_state_sha256") != _canonical_sha(prior):
        raise ValueError("formal warm repetition source mismatch")
    if not math.isclose(
        float(row.get("transfer_source_budget", math.nan)),
        source_budget, rel_tol=0.0, abs_tol=1.0e-9,
    ):
        raise ValueError("formal warm repetition source budget mismatch")
    initial_pool = list(row.get("initial_scenarios", []))
    reusable = set(prior["active_scenarios"]) | set(
        prior["historical_adversarial_scenarios"]
    )
    expected_transfer = [name for name in initial_pool if name in reusable]
    actual_transfer = list(row.get("transferred_exact_scenarios", []))
    if actual_transfer != expected_transfer or not expected_transfer:
        raise ValueError("formal transferred scenarios differ from prior state")
    if int(row.get("transferred_exact_scenario_count", -1)) != len(expected_transfer):
        raise ValueError("formal transferred scenario count mismatch")
    expected_rate = len(expected_transfer) / len(initial_pool)
    if not math.isclose(
        float(row.get("transferred_scenario_reuse_rate", math.nan)),
        expected_rate, rel_tol=0.0, abs_tol=1.0e-12,
    ):
        raise ValueError("formal transferred scenario reuse rate mismatch")
    exact_costs = row["ccg_result"]["exact_scenario_costs"]
    worst_cost = max(float(value) for value in exact_costs.values())
    active = {
        name for name, value in exact_costs.items()
        if worst_cost - float(value) <= active_tolerance
    }
    worst = row["ccg_result"].get("worst_scenario")
    expected_active_or_worst = [
        name for name in expected_transfer if name in active or name == worst
    ]
    if (
        row.get("transferred_scenarios_becoming_active_or_worst")
        != expected_active_or_worst
        or int(row.get("transferred_scenarios_becoming_active_or_worst_count", -1))
        != len(expected_active_or_worst)
    ):
        raise ValueError("formal transferred active/worst evidence mismatch")


def _run_formal_sequence(
    *, root: Path, context: Mapping[str, Any], case: FormalCase, run_id: str,
    execution_root: Path, worker_executor: WorkerExecutor = _worker_executor,
) -> dict[str, Any]:
    if SAFE_RUN_ID.fullmatch(run_id) is None or ".." in run_id:
        raise ValueError("unsafe run_id")
    run_dir = (execution_root / "runs" / run_id).resolve()
    if execution_root.resolve() not in run_dir.parents or run_dir.exists():
        raise FileExistsError("formal run_id is invalid or already exists")
    run_dir.mkdir(parents=True)
    result_path, manifest_path = run_dir / "result.json", run_dir / "manifest.json"
    status_path = run_dir / "status_summary.json"
    comparisons: list[dict[str, Any]] = []
    previous_states: dict[int, dict[str, Any]] = {}
    try:
        for budget_index, (beta, budget) in enumerate(zip(
            context["design"]["budget_sequence"]["betas"],
            context["design"]["budget_sequence"]["budgets"], strict=True,
        )):
            order = ("cold", "warm") if budget_index == 0 else ("warm", "cold")
            methods: dict[str, list[dict[str, Any]]] = {"cold": [], "warm": []}
            for algorithm in order:
                for repetition in (1, 2, 3):
                    prior = previous_states.get(repetition) if algorithm == "warm" else None
                    request = {
                        "project_root": str(root), "matrix_path": str(root / context["runner"]["base_matrix"]),
                        "design_path": str(root / context["runner"]["design_config"]),
                        "algorithm": algorithm, "budget_index": budget_index,
                        "beta": float(beta), "budget": float(budget), "seed": case.seed,
                        "profile_id": case.profile_id, "scenario_count": 100,
                        "repetition": repetition, "previous_state": prior,
                        "solver": context["runner"]["solver"], "ccg": context["runner"]["ccg"],
                        "objective_consistency": context["runner"]["objective_consistency"],
                    }
                    row = worker_executor(request, float(context["runner"]["limits"]["worker_wall_seconds"]), run_dir / "workers")
                    if row.get("status") != "optimal":
                        native = str(row.get("solver_status") or row.get("status"))
                        terminal = "timeout" if native in {"time_limit", "master_time_limit", "external_wall_timeout"} else "stage_failure"
                        raise RuntimeError(json.dumps({"terminal": terminal, "native_status": native}))
                    row = dict(row)
                    row["repetition"] = repetition
                    try:
                        _validate_worker_identity(
                            row, case=case, algorithm=algorithm, repetition=repetition,
                            beta=float(beta), budget=float(budget), budget_index=budget_index,
                        )
                        _validate_worker_evidence(row, expected_scenarios=100)
                        _method_metrics(row)
                        if budget_index == 1 and algorithm == "warm":
                            _validate_second_budget_transfer(
                                row, previous_states[repetition],
                                source_budget=float(context["design"]["budget_sequence"]["budgets"][0]),
                                active_tolerance=float(context["runner"]["ccg"]["active_scenario_tolerance"]),
                            )
                    except (KeyError, TypeError, ValueError) as exc:
                        raise FormalEvidenceError(str(exc)) from exc
                    methods[algorithm].append(row)
                    if algorithm == "warm":
                        previous_states[repetition] = _build_transferred_state(
                            row, prior, budget=float(budget),
                            tolerance=float(context["runner"]["ccg"]["active_scenario_tolerance"]),
                        )
            all_rows = [*methods["cold"], *methods["warm"]]
            objectives = [float(row["objective"]) for row in all_rows]
            tolerance = _objective_tolerance(objectives, context["runner"]["objective_consistency"])
            difference = max(objectives) - min(objectives)
            if difference > tolerance:
                raise RuntimeError("formal objective consistency failure")
            components = [row["component_set_sha256"] for row in all_rows]
            if any(value != components[0] for value in components[1:]):
                raise RuntimeError("formal repetitions do not share scenario identity")
            if budget_index == 1:
                for repetition, row in enumerate(methods["warm"], 1):
                    if row["transfer_source_state_sha256"] != _canonical_sha(comparisons[0]["transferred_states"][str(repetition)]):
                        raise RuntimeError("formal warm repetition source mismatch")
                    if int(row["transferred_exact_scenario_count"]) <= 0:
                        raise RuntimeError("formal second-budget transfer is empty")
            comparisons.append({
                "budget_index": budget_index, "beta": float(beta), "budget": float(budget),
                "execution_order": list(order), "status": "optimal", "methods": methods,
                "objective_tolerance": tolerance, "maximum_objective_difference": difference,
                "transferred_states": {str(k): v for k, v in previous_states.items()},
            })
            atomic_write_json(status_path, {"status": "running", "run_id": run_id, "completed_budget_count": len(comparisons), "updated_at_utc": utc_now()})
        result = {
            "artifact_state": "finalized", "status": "optimal", "run_id": run_id,
            "parent_run_id": None, "case_id": case.case_id, "tier_id": "M2AP2",
            "execution_mode": "formal", "seed": case.seed, "profile_id": case.profile_id,
            "planned_algorithm_execution_count": 12, "completed_algorithm_execution_count": 12,
            "comparisons": comparisons, "fingerprints": context["fingerprints"],
            "execution_identity": context["synchronized_main"], "completed_at_utc": utc_now(),
        }
        try:
            _validate_result(result, case, context, expected_run_id=run_id)
        except (KeyError, TypeError, ValueError) as exc:
            raise FormalEvidenceError(str(exc)) from exc
        atomic_write_json(result_path, result); atomic_write_json(manifest_path, _manifest(result_path, result, context["fingerprints"]))
        atomic_write_json(status_path, {"status": "optimal", "run_id": run_id, "completed_algorithm_execution_count": 12, "updated_at_utc": utc_now()})
        return result
    except BaseException as exc:
        message = str(exc)
        terminal = (
            "interrupted" if isinstance(exc, KeyboardInterrupt)
            else "timeout" if '"terminal": "timeout"' in message
            else "evidence_invalid" if isinstance(exc, FormalEvidenceError)
            else "runner_exception"
        )
        failure = {"artifact_state": "finalized", "status": terminal, "run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "comparisons": comparisons, "exception_type": type(exc).__name__, "message": message[:4096], "fingerprints": context["fingerprints"], "execution_identity": context["synchronized_main"], "completed_at_utc": utc_now()}
        atomic_write_json(result_path, failure); atomic_write_json(manifest_path, _manifest(result_path, failure, context["fingerprints"])); atomic_write_json(status_path, {"status": terminal, "run_id": run_id, "message": message[:4096], "updated_at_utc": utc_now()})
        raise


def _validate_result(
    result: Mapping[str, Any], case: FormalCase, context: Mapping[str, Any],
    *, expected_run_id: str,
) -> dict[str, Any]:
    if (
        result.get("status") != "optimal"
        or result.get("artifact_state") != "finalized"
        or result.get("execution_mode") != "formal"
        or result.get("run_id") != expected_run_id
        or result.get("parent_run_id") is not None
        or result.get("case_id") != case.case_id
        or result.get("tier_id") != "M2AP2"
        or int(result.get("seed", -1)) != case.seed
        or result.get("profile_id") != case.profile_id
        or int(result.get("planned_algorithm_execution_count", -1)) != 12
        or int(result.get("completed_algorithm_execution_count", -1)) != 12
    ):
        raise ValueError("formal result identity/status mismatch")
    if result.get("fingerprints") != context["fingerprints"] or result.get("execution_identity") != context["synchronized_main"]:
        raise ValueError("formal execution identity mismatch")
    comparisons = result.get("comparisons", [])
    executions = 0
    pair_rows: list[dict[str, Any]] = []
    if len(comparisons) != 2:
        raise ValueError("formal result must contain two budgets")
    prior_states = None
    prior_components = None
    prior_joint = None
    expected_betas = tuple(float(value) for value in context["design"]["budget_sequence"]["betas"])
    expected_budgets = tuple(float(value) for value in context["design"]["budget_sequence"]["budgets"])
    for index, comparison in enumerate(comparisons):
        expected_order = ["cold", "warm"] if index == 0 else ["warm", "cold"]
        beta, budget = expected_betas[index], expected_budgets[index]
        if (
            comparison.get("status") != "optimal"
            or comparison.get("execution_order") != expected_order
            or int(comparison.get("budget_index", -1)) != index
            or not math.isclose(float(comparison.get("beta", math.nan)), beta, rel_tol=0.0, abs_tol=1.0e-12)
            or not math.isclose(float(comparison.get("budget", math.nan)), budget, rel_tol=0.0, abs_tol=1.0e-9)
        ):
            raise ValueError("formal budget identity, status, or execution order mismatch")
        methods = comparison.get("methods", {})
        if set(methods) != {"cold", "warm"} or any(len(methods[name]) != 3 for name in methods):
            raise ValueError("formal technical repetitions are incomplete")
        objectives: list[float] = []
        metrics: dict[str, list[dict[str, Any]]] = {"cold": [], "warm": []}
        component_identities: list[dict[str, str]] = []
        joint_identities: list[str] = []
        for name in ("cold", "warm"):
            for repetition, row in enumerate(methods[name], 1):
                _validate_worker_identity(
                    row, case=case, algorithm=name, repetition=repetition,
                    beta=beta, budget=budget, budget_index=index,
                )
                _validate_worker_evidence(row, expected_scenarios=100)
                method_metrics = _method_metrics(row)
                metrics[name].append(method_metrics)
                objectives.append(method_metrics["objective"])
                component_identities.append(method_metrics["component_set_sha256"])
                joint_identities.append(method_metrics["joint_scenario_set_sha256"])
                executions += 1
        tolerance = _objective_tolerance(objectives, context["runner"]["objective_consistency"])
        difference = max(objectives) - min(objectives)
        if (
            not math.isclose(float(comparison.get("objective_tolerance", math.nan)), tolerance, rel_tol=0.0, abs_tol=1.0e-12)
            or not math.isclose(float(comparison.get("maximum_objective_difference", math.nan)), difference, rel_tol=0.0, abs_tol=1.0e-12)
            or difference > tolerance
        ):
            raise ValueError("formal objective consistency evidence mismatch")
        if any(value != component_identities[0] for value in component_identities[1:]):
            raise ValueError("formal repetitions do not share component identity")
        if len(set(joint_identities)) != 1:
            raise ValueError("formal repetitions do not share joint scenario identity")
        if (
            prior_components is not None and component_identities[0] != prior_components
        ) or (prior_joint is not None and joint_identities[0] != prior_joint):
            raise ValueError("formal sequence regenerated different scenarios across budgets")
        if index == 1:
            for repetition, row in enumerate(methods["warm"], 1):
                _validate_second_budget_transfer(
                    row, prior_states[str(repetition)],
                    source_budget=expected_budgets[0],
                    active_tolerance=float(context["runner"]["ccg"]["active_scenario_tolerance"]),
                )
        rebuilt_states = {
            str(repetition): _build_transferred_state(
                row, None if index == 0 else prior_states[str(repetition)],
                budget=budget,
                tolerance=float(context["runner"]["ccg"]["active_scenario_tolerance"]),
            )
            for repetition, row in enumerate(methods["warm"], 1)
        }
        if comparison.get("transferred_states") != rebuilt_states:
            raise ValueError("formal transferable states were not independently reproduced")
        cold_median = float(median(value["subprocess_wall_seconds"] for value in metrics["cold"]))
        warm_median = float(median(value["subprocess_wall_seconds"] for value in metrics["warm"]))
        if cold_median <= 0.0 or warm_median <= 0.0:
            raise ValueError("formal median timing must be positive")
        pair_rows.append({
            "seed": case.seed, "profile_id": case.profile_id,
            "budget_index": index, "beta": beta, "budget": budget,
            "cold_median_seconds": cold_median,
            "warm_median_seconds": warm_median,
            "speedup_cold_over_warm": cold_median / warm_median,
            "methods": metrics,
            "component_set_sha256": component_identities[0],
            "joint_scenario_set_sha256": joint_identities[0],
        })
        prior_states = comparison["transferred_states"]
        prior_components = component_identities[0]
        prior_joint = joint_identities[0]
    if executions != 12:
        raise ValueError("formal result does not contain 12 executions")
    return {"execution_count": executions, "budget_pair_count": 2, "timing": pair_rows}


def _percentile_interval(values: np.ndarray) -> list[float]:
    return [
        float(value)
        for value in np.percentile(values, [2.5, 97.5], method="linear")
    ]


def compute_formal_statistics(
    derived_rows: Sequence[Mapping[str, Any]], *, correctness_gate_passed: bool,
) -> dict[str, Any]:
    """Apply the pre-registered ten-seed formal analysis without selection."""

    timing = [
        row
        for value in derived_rows
        for row in value["derived"]["timing"]
    ]
    index = {
        (int(row["seed"]), str(row["profile_id"]), int(row["budget_index"])): row
        for row in timing
    }
    seeds = tuple(range(2026091101, 2026091111))
    if len(timing) != 40 or len(index) != 40:
        raise ValueError("formal statistics require exactly 40 unique seed/profile/budget rows")
    seed_level: list[dict[str, Any]] = []
    primary_logs: list[float] = []
    paired_log_differences: list[float] = []
    end_to_end_logs: dict[str, list[float]] = {"C0": [], "T03": []}
    for seed in seeds:
        profiles: dict[str, Any] = {}
        for profile in ("C0", "T03"):
            rows = [index[(seed, profile, budget_index)] for budget_index in (0, 1)]
            speedups = [float(row["speedup_cold_over_warm"]) for row in rows]
            if not all(math.isfinite(value) and value > 0.0 for value in speedups):
                raise ValueError("formal speedups must be finite and positive")
            end_to_end = (
                sum(float(row["cold_median_seconds"]) for row in rows)
                / sum(float(row["warm_median_seconds"]) for row in rows)
            )
            compact = [
                {
                    "beta": float(row["beta"]), "budget": float(row["budget"]),
                    "cold_median_seconds": float(row["cold_median_seconds"]),
                    "warm_median_seconds": float(row["warm_median_seconds"]),
                    "speedup_cold_over_warm": float(row["speedup_cold_over_warm"]),
                }
                for row in rows
            ]
            profiles[profile] = {
                "beta_1_1": compact[0], "beta_1_3": compact[1],
                "end_to_end_two_budget_speedup": end_to_end,
            }
            end_to_end_logs[profile].append(math.log(end_to_end))
        primary_log = math.log(profiles["T03"]["beta_1_3"]["speedup_cold_over_warm"])
        paired = primary_log - math.log(profiles["C0"]["beta_1_3"]["speedup_cold_over_warm"])
        primary_logs.append(primary_log)
        paired_log_differences.append(paired)
        seed_level.append({
            "seed": seed, "profiles": profiles,
            "T03_beta_1_3_log_speedup": primary_log,
            "paired_T03_minus_C0_beta_1_3_log_speedup": paired,
        })
    primary_point = math.exp(float(median(primary_logs)))
    enhancement_point = math.exp(float(median(paired_log_differences)))
    rng = np.random.Generator(np.random.PCG64DXSM(2026091299))
    draws = rng.integers(0, len(seeds), size=(10000, len(seeds)), endpoint=False)
    primary_source = np.asarray(primary_logs, dtype=float)
    enhancement_source = np.asarray(paired_log_differences, dtype=float)
    primary_bootstrap = np.exp(np.median(primary_source[draws], axis=1))
    enhancement_bootstrap = np.exp(np.median(enhancement_source[draws], axis=1))
    primary_ci = _percentile_interval(primary_bootstrap)
    enhancement_ci = _percentile_interval(enhancement_bootstrap)
    reliable = bool(correctness_gate_passed and primary_point > 1.0 and primary_ci[0] > 1.0)
    enhanced = bool(reliable and enhancement_point > 1.0 and enhancement_ci[0] > 1.0)
    return {
        "protocol": {
            "independent_unit": "formal_performance_seed",
            "technical_repetitions_reduced_by": "median",
            "random_number_generator": "numpy_Generator_PCG64DXSM",
            "random_seed": 2026091299, "resamples": 10000,
            "confidence_level": 0.95, "interval": "percentile_linear",
            "shared_paired_seed_resample_indices_for_both_estimands": True,
            "P_values_planned": False,
        },
        "seed_level_values": seed_level,
        "primary_estimand": {
            "name": "T03_beta_1_3_cross_budget_transfer_speedup",
            "point_estimate": primary_point,
            "bootstrap_95_percentile_CI": primary_ci,
            "beta_1_1_excluded_because_no_prior_budget_transfer": True,
        },
        "confirmatory_disruption_enhancement_estimand": {
            "name": "paired_T03_vs_C0_beta_1_3_speedup_ratio",
            "point_estimate": enhancement_point,
            "bootstrap_95_percentile_CI": enhancement_ci,
        },
        "secondary_end_to_end_two_budget_speedup": {
            profile: math.exp(float(median(values)))
            for profile, values in end_to_end_logs.items()
        },
        "reliable_M2_T03_acceleration_gate_passed": reliable,
        "supply_disruption_enhances_warm_start_benefit_gate_passed": enhanced,
        "effect_direction_does_not_control_execution_completeness_gate": True,
    }


def update_projection(execution_root: Path, context: Mapping[str, Any]) -> dict[str, Any]:
    rows=_registry(execution_root/"run_registry.json"); expected={c.case_id:c for c in context["cases"]}
    primary={key:[r for r in rows if r.get("case_id")==key and not r.get("parent_run_id")] for key in expected}
    missing=[k for k,v in primary.items() if not v]; duplicates=[k for k,v in primary.items() if len(v)>1]
    failed=[]; invalid=[]; derived=[]
    for case_id, values in primary.items():
        if len(values)!=1: continue
        row=values[0]
        if row.get("status")!="optimal": failed.append(row.get("run_id")); continue
        try:
            if (
                SAFE_RUN_ID.fullmatch(str(row.get("run_id", ""))) is None
                or not str(row["run_id"]).endswith("_" + case_id)
                or int(row.get("seed", -1)) != expected[case_id].seed
                or row.get("profile_id") != expected[case_id].profile_id
            ):
                raise ValueError("formal registry identity mismatch")
            path=(execution_root/"runs"/row["run_id"]/"result.json").resolve(); manifest=json.loads(path.with_name("manifest.json").read_text()); result=json.loads(path.read_text())
            if execution_root.resolve() not in path.parents or manifest["result_sha256"]!=sha256_file(path): raise ValueError("formal artifact binding mismatch")
            derived.append({
                "result": result,
                "derived": _validate_result(
                    result, expected[case_id], context,
                    expected_run_id=str(row["run_id"]),
                ),
            })
        except Exception as exc: invalid.append({"case_id":case_id,"message":f"{type(exc).__name__}: {exc}"})
    crn_mismatches=[]
    results=[value["result"] for value in derived]
    for seed in sorted({case.seed for case in context["cases"]}):
        seed_case_ids=[case.case_id for case in context["cases"] if case.seed==seed]
        if any(len(primary[case_id])!=1 for case_id in seed_case_ids):
            # A not-yet-run profile is ordinary in-progress state; missing and
            # duplicate primary collections are already reported separately.
            continue
        paired=[result for result in results if int(result["seed"])==seed]
        if len(paired)!=2:
            crn_mismatches.append({
                "seed": seed, "field": "paired_profile_record_count",
                "expected": 2, "actual": len(paired),
            })
            continue
        if {result["profile_id"] for result in paired}!={"C0","T03"}:
            crn_mismatches.append({"seed":seed,"field":"paired_profile_identity"})
            continue
        for budget_index in (0,1):
            components=[
                result["comparisons"][budget_index]["methods"]["cold"][0]["component_set_sha256"]
                for result in paired
            ]
            for field in CRN_FIELDS:
                if len({value[field] for value in components})!=1:
                    crn_mismatches.append({"seed":seed,"budget_index":budget_index,"field":field})
            if len({value["fulfillment_sha256"] for value in components})!=2:
                crn_mismatches.append({"seed":seed,"budget_index":budget_index,"field":"fulfillment_profile_separation"})
    diagnostics=[r["run_id"] for r in rows if r.get("parent_run_id")]
    pairs=sum(v["derived"]["budget_pair_count"] for v in derived); executions=sum(v["derived"]["execution_count"] for v in derived)
    evidence_gate=not(missing or duplicates or failed or invalid or diagnostics or crn_mismatches) and len(derived)==20 and pairs==40 and executions==240
    statistics_error=None
    statistics=None
    if evidence_gate:
        try:
            statistics=compute_formal_statistics(derived,correctness_gate_passed=True)
        except Exception as exc:
            statistics_error=f"{type(exc).__name__}: {exc}"
    gate=evidence_gate and statistics is not None
    payload={"status":"passed" if gate else "incomplete","required_primary_sequence_count":20,"completed_primary_sequence_count":len(derived),"required_budget_pair_count":40,"completed_budget_pair_count":pairs,"required_algorithm_execution_count":240,"completed_algorithm_execution_count":executions,"missing_case_ids":missing,"duplicate_case_ids":duplicates,"failed_primary_run_ids":failed,"invalid_primary_runs":invalid,"diagnostic_run_ids":diagnostics,"common_random_number_mismatches":crn_mismatches,"statistics_error":statistics_error,"formal_statistics":statistics,"fingerprints":context["fingerprints"],"execution_identity":context["synchronized_main"],"formal_algorithm_performance_gate_passed":gate,"effect_direction_controls_completion_gate":False,"other_experiments_authorized":False,"updated_at_utc":utc_now()}
    status_summary={
        "status": payload["status"],
        "completed_primary_sequence_count": len(derived),
        "completed_budget_pair_count": pairs,
        "completed_algorithm_execution_count": executions,
        "failure_count": len(failed)+len(invalid)+len(duplicates),
        "formal_algorithm_performance_gate_passed": gate,
        "reliable_M2_T03_acceleration_gate_passed": (
            None if statistics is None
            else statistics["reliable_M2_T03_acceleration_gate_passed"]
        ),
        "supply_disruption_enhances_warm_start_benefit_gate_passed": (
            None if statistics is None
            else statistics["supply_disruption_enhances_warm_start_benefit_gate_passed"]
        ),
        "updated_at_utc": payload["updated_at_utc"],
    }
    atomic_write_json(execution_root/"formal_projection.json",payload)
    atomic_write_json(execution_root/"status_summary.json",status_summary)
    return payload


def run_formal_batch(
    *, root: Path, runner_path: Path, approval_path: Path, authorize: bool,
    run_id_prefix: str, worker_executor: WorkerExecutor = _worker_executor,
) -> dict[str, Any]:
    if not authorize:
        raise RuntimeError("explicit formal algorithm-performance authorization is required")
    if SAFE_RUN_ID.fullmatch(run_id_prefix or "") is None or ".." in run_id_prefix:
        raise ValueError("unsafe run_id_prefix")
    context = validate_preflight(root, runner_path, approval_path, require_authorization=True)
    output_root = (root / context["runner"]["output_root"]).resolve()
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError("formal output root must be empty")
    execution_root = output_root / context["runner"]["formal_subdirectory"]
    execution_root.mkdir(parents=True)
    registry = execution_root / "run_registry.json"
    blocker_fields = (
        "duplicate_case_ids", "failed_primary_run_ids", "invalid_primary_runs",
        "diagnostic_run_ids", "common_random_number_mismatches",
    )
    with exclusive_file_lock(output_root / ".batch.lock", timeout_seconds=0.0):
        for case in context["cases"]:
            run_id = f"{run_id_prefix}_{case.case_id}"
            try:
                result = _run_formal_sequence(
                    root=root, context=context, case=case, run_id=run_id,
                    execution_root=execution_root, worker_executor=worker_executor,
                )
                rows = _registry(registry)
                rows.append({
                    "run_id": run_id, "parent_run_id": None,
                    "case_id": case.case_id, "seed": case.seed,
                    "profile_id": case.profile_id, "status": result["status"],
                })
                atomic_write_json(registry, {"namespace": NAMESPACE, "runs": rows})
                projection = update_projection(execution_root, context)
                if any(projection[field] for field in blocker_fields):
                    raise FormalEvidenceError(
                        "formal projection found invalid evidence after primary finalization"
                    )
            except BaseException:
                rows = _registry(registry)
                if not any(row.get("run_id") == run_id for row in rows):
                    status = json.loads(
                        (execution_root / "runs" / run_id / "status_summary.json").read_text()
                    )["status"]
                    rows.append({
                        "run_id": run_id, "parent_run_id": None,
                        "case_id": case.case_id, "seed": case.seed,
                        "profile_id": case.profile_id, "status": status,
                    })
                    atomic_write_json(registry, {"namespace": NAMESPACE, "runs": rows})
                update_projection(execution_root, context)
                raise
        return update_projection(execution_root, context)


def read_status(path: Path, maximum_bytes: int=16384) -> dict[str, Any]:
    if not path.is_file(): return {"status":"not_started","path":str(path)}
    if path.stat().st_size>maximum_bytes: raise ValueError("status file exceeds bounded limit")
    return json.loads(path.read_text(encoding="utf-8"))

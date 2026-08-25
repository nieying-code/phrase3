"""Guarded formal executor for the frozen M2 algorithm-performance matrix."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
from statistics import median
from typing import Any, Callable, Mapping, Sequence

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


@dataclass(frozen=True)
class FormalCase:
    case_id: str
    seed: int
    profile_id: str


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
                    _validate_worker_evidence(row, expected_scenarios=100)
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
        atomic_write_json(result_path, result); atomic_write_json(manifest_path, _manifest(result_path, result, context["fingerprints"]))
        atomic_write_json(status_path, {"status": "optimal", "run_id": run_id, "completed_algorithm_execution_count": 12, "updated_at_utc": utc_now()})
        return result
    except BaseException as exc:
        message = str(exc); terminal = "interrupted" if isinstance(exc, KeyboardInterrupt) else ("timeout" if '"terminal": "timeout"' in message else "runner_exception")
        failure = {"artifact_state": "finalized", "status": terminal, "run_id": run_id, "parent_run_id": None, "case_id": case.case_id, "seed": case.seed, "profile_id": case.profile_id, "comparisons": comparisons, "exception_type": type(exc).__name__, "message": message[:4096], "fingerprints": context["fingerprints"], "execution_identity": context["synchronized_main"], "completed_at_utc": utc_now()}
        atomic_write_json(result_path, failure); atomic_write_json(manifest_path, _manifest(result_path, failure, context["fingerprints"])); atomic_write_json(status_path, {"status": terminal, "run_id": run_id, "message": message[:4096], "updated_at_utc": utc_now()})
        raise


def _validate_result(result: Mapping[str, Any], case: FormalCase, context: Mapping[str, Any]) -> dict[str, Any]:
    if result.get("status") != "optimal" or result.get("execution_mode") != "formal" or result.get("case_id") != case.case_id:
        raise ValueError("formal result identity/status mismatch")
    if result.get("fingerprints") != context["fingerprints"] or result.get("execution_identity") != context["synchronized_main"]:
        raise ValueError("formal execution identity mismatch")
    comparisons = result.get("comparisons", []); executions = 0; pair_rows = []
    if len(comparisons) != 2:
        raise ValueError("formal result must contain two budgets")
    prior_states = None
    prior_components = None
    for index, comparison in enumerate(comparisons):
        expected_order = ["cold", "warm"] if index == 0 else ["warm", "cold"]
        if comparison.get("execution_order") != expected_order or comparison.get("budget_index") != index:
            raise ValueError("formal execution order mismatch")
        methods = comparison.get("methods", {})
        if set(methods) != {"cold", "warm"} or any(len(methods[name]) != 3 for name in methods):
            raise ValueError("formal technical repetitions are incomplete")
        objectives=[]
        for name in ("cold", "warm"):
            for repetition, row in enumerate(methods[name], 1):
                if (
                    row.get("algorithm") != name
                    or row.get("status") != "optimal"
                    or int(row.get("repetition", -1)) != repetition
                ):
                    raise ValueError("formal method identity mismatch")
                _validate_worker_evidence(row, expected_scenarios=100); objectives.append(float(row["objective"])); executions += 1
                if index == 1 and name == "warm":
                    prior = prior_states[str(repetition)]
                    if row["transfer_source_state_sha256"] != _canonical_sha(prior) or int(row["transferred_exact_scenario_count"]) <= 0:
                        raise ValueError("formal transfer chain mismatch")
        tolerance = _objective_tolerance(objectives, context["runner"]["objective_consistency"])
        if max(objectives)-min(objectives) > tolerance:
            raise ValueError("formal objective mismatch")
        component_identities = [
            row["component_set_sha256"]
            for name in ("cold", "warm") for row in methods[name]
        ]
        if any(value != component_identities[0] for value in component_identities[1:]):
            raise ValueError("formal repetitions do not share scenario identity")
        if prior_components is not None and component_identities[0] != prior_components:
            raise ValueError("formal sequence regenerated different scenarios across budgets")
        if index == 1:
            for repetition, row in enumerate(methods["warm"], 1):
                prior = prior_states[str(repetition)]
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
                    if worst_cost - float(value)
                    <= float(context["runner"]["ccg"]["active_scenario_tolerance"])
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
        rebuilt_states = {
            str(repetition): _build_transferred_state(
                row, None if index == 0 else prior_states[str(repetition)],
                budget=float(comparison["budget"]),
                tolerance=float(context["runner"]["ccg"]["active_scenario_tolerance"]),
            )
            for repetition, row in enumerate(methods["warm"], 1)
        }
        if comparison.get("transferred_states") != rebuilt_states:
            raise ValueError("formal transferable states were not independently reproduced")
        pair_rows.append({
            "budget_index": index,
            "cold_median_seconds": median(float(v["subprocess_wall_seconds"]) for v in methods["cold"]),
            "warm_median_seconds": median(float(v["subprocess_wall_seconds"]) for v in methods["warm"]),
            "component_set_sha256": component_identities[0],
        })
        prior_states = comparison["transferred_states"]
        prior_components = component_identities[0]
    if executions != 12:
        raise ValueError("formal result does not contain 12 executions")
    return {"execution_count": executions, "budget_pair_count": 2, "timing": pair_rows}


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
            path=(execution_root/"runs"/row["run_id"]/"result.json").resolve(); manifest=json.loads(path.with_name("manifest.json").read_text()); result=json.loads(path.read_text())
            if execution_root.resolve() not in path.parents or manifest["result_sha256"]!=sha256_file(path): raise ValueError("formal artifact binding mismatch")
            derived.append({"result":result,"derived":_validate_result(result,expected[case_id],context)})
        except Exception as exc: invalid.append({"case_id":case_id,"message":f"{type(exc).__name__}: {exc}"})
    crn_mismatches=[]
    results=[value["result"] for value in derived]
    for seed in sorted({case.seed for case in context["cases"]}):
        paired=[result for result in results if int(result["seed"])==seed]
        if len(paired)!=2:
            continue
        for budget_index in (0,1):
            components=[
                result["comparisons"][budget_index]["methods"]["cold"][0]["component_set_sha256"]
                for result in paired
            ]
            for field in (
                "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
                "emergency_supply_sha256", "scenario_order_sha256",
            ):
                if len({value[field] for value in components})!=1:
                    crn_mismatches.append({"seed":seed,"budget_index":budget_index,"field":field})
            if len({value["fulfillment_sha256"] for value in components})!=2:
                crn_mismatches.append({"seed":seed,"budget_index":budget_index,"field":"fulfillment_profile_separation"})
    diagnostics=[r["run_id"] for r in rows if r.get("parent_run_id")]
    pairs=sum(v["derived"]["budget_pair_count"] for v in derived); executions=sum(v["derived"]["execution_count"] for v in derived)
    gate=not(missing or duplicates or failed or invalid or diagnostics or crn_mismatches) and len(derived)==20 and pairs==40 and executions==240
    payload={"status":"passed" if gate else "incomplete","required_primary_sequence_count":20,"completed_primary_sequence_count":len(derived),"required_budget_pair_count":40,"completed_budget_pair_count":pairs,"required_algorithm_execution_count":240,"completed_algorithm_execution_count":executions,"missing_case_ids":missing,"duplicate_case_ids":duplicates,"failed_primary_run_ids":failed,"invalid_primary_runs":invalid,"diagnostic_run_ids":diagnostics,"common_random_number_mismatches":crn_mismatches,"fingerprints":context["fingerprints"],"execution_identity":context["synchronized_main"],"formal_algorithm_performance_gate_passed":gate,"other_experiments_authorized":False,"updated_at_utc":utc_now()}
    atomic_write_json(execution_root/"formal_projection.json",payload); atomic_write_json(execution_root/"status_summary.json",payload); return payload


def run_formal_batch(*, root: Path, runner_path: Path, approval_path: Path, authorize: bool, run_id_prefix: str, worker_executor: WorkerExecutor=_worker_executor) -> dict[str, Any]:
    if not authorize: raise RuntimeError("explicit formal algorithm-performance authorization is required")
    if SAFE_RUN_ID.fullmatch(run_id_prefix or "") is None or ".." in run_id_prefix: raise ValueError("unsafe run_id_prefix")
    context=validate_preflight(root,runner_path,approval_path,require_authorization=True)
    output_root=(root/context["runner"]["output_root"]).resolve()
    if output_root.exists() and any(output_root.iterdir()): raise RuntimeError("formal output root must be empty")
    execution_root=output_root/context["runner"]["formal_subdirectory"]; execution_root.mkdir(parents=True); registry=execution_root/"run_registry.json"
    with exclusive_file_lock(output_root/".batch.lock",timeout_seconds=0.0):
        for case in context["cases"]:
            run_id=f"{run_id_prefix}_{case.case_id}"
            try:
                result=_run_formal_sequence(root=root,context=context,case=case,run_id=run_id,execution_root=execution_root,worker_executor=worker_executor)
                rows=_registry(registry); rows.append({"run_id":run_id,"parent_run_id":None,"case_id":case.case_id,"seed":case.seed,"profile_id":case.profile_id,"status":result["status"]}); atomic_write_json(registry,{"namespace":NAMESPACE,"runs":rows}); update_projection(execution_root,context)
            except BaseException:
                rows=_registry(registry); status=json.loads((execution_root/"runs"/run_id/"status_summary.json").read_text())["status"]
                rows.append({"run_id":run_id,"parent_run_id":None,"case_id":case.case_id,"seed":case.seed,"profile_id":case.profile_id,"status":status}); atomic_write_json(registry,{"namespace":NAMESPACE,"runs":rows}); update_projection(execution_root,context); raise
        return update_projection(execution_root,context)


def read_status(path: Path, maximum_bytes: int=16384) -> dict[str, Any]:
    if not path.is_file(): return {"status":"not_started","path":str(path)}
    if path.stat().st_size>maximum_bytes: raise ValueError("status file exceeds bounded limit")
    return json.loads(path.read_text(encoding="utf-8"))

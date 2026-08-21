"""Audited executor for the frozen ten-pair M2 formal OOS batch.

The executor consumes the reviewed, finalized first-stage plans from the
formal mechanism namespace.  It never rewrites that namespace and never
authorizes the later algorithm-performance experiment.
"""

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

from .evaluation import EvaluationResult, evaluate_first_stage, regular_cost
from .phase6_environment import validate_locked_environment
from .phase6_families import aggregate_oos_evaluation, generate_oos_data
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes
from .phase6_locking import exclusive_file_lock
from .phase6_m2 import m2_model_context, reconstruct_frozen_demand_latent, resolve_supply_disruption_profile
from .phase6_m2_development import PeakRSSSampler, compact_failure, validate_run_id
from .phase6_m2_formal_extension import (
    FAMILY_COMPONENT_FILES,
    FINGERPRINT_FIELDS,
    PROTOCOL_ID,
    _confirmation_component_hashes,
    _confirmation_config,
    _cross_item_from_evaluation,
    _derive_probe,
    _science_config_for_formal,
    _validate_formal_baseline_before_generation,
    formal_extension_fingerprints,
    load_formal_extension_config,
)
from .phase6_m2_formal_mechanism import (
    FORMAL_ORCHESTRATOR_FILES as SOURCE_ORCHESTRATOR_FILES,
    _read_registry as _read_source_registry,
    _validate_artifact as _validate_source_artifact,
    _validate_formal_plan_artifact,
)
from .phase6_m2c2_confirmation import apply_m2c2_supply_disruption
from .phase6_protocol import load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


OOS_NAMESPACE = "phase6_m2_formal_oos_v1_1"
OOS_STATUS = "frozen_for_formal_oos_execution"
OOS_OUTPUT_ROOT = "outputs/phase6_m2_formal_oos_v1_1"
OOS_SUBDIRECTORY = "formal/OOS"
SOURCE_OUTPUT_ROOT = "outputs/phase6_m2_formal_extension_v1_1"
SOURCE_SUBDIRECTORY = "formal/mechanism"
OOS_RUNNER_PATH = "configs/phase6_m2_formal_oos_runner.yaml"
OOS_APPROVAL_PATH = "configs/phase6_m2_formal_oos_approval.yaml"
PILOT_RUNNER_PATH = "configs/phase6_m2_formal_extension_runner.yaml"
MECHANISM_AUDIT_PATH = "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json"
REQUIRED_STRATEGIES = (
    "endogenous_reserve",
    "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10",
    "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)
OOS_ORCHESTRATOR_FILES = tuple(dict.fromkeys(SOURCE_ORCHESTRATOR_FILES + (
    "src/phase6_m2_formal_oos.py",
    "src/run_phase6_m2_formal_oos.py",
    "src/phase6_m2_formal_oos_status.py",
    OOS_RUNNER_PATH,
)))
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "run_kind", "tier_id", "seed",
    "test_seed", "beta", "profile_id", "source_mechanism_run_id", "status",
    "wall_seconds", "peak_memory_mb", *FINGERPRINT_FIELDS,
    "formal_OOS_orchestrator_sha256", "result_path", "manifest_path",
    "manifest_sha256", "failure_stage", "updated_at_utc",
)


@dataclass(frozen=True)
class FormalOOSCase:
    case_id: str
    run_kind: str
    tier_id: str
    seed: int
    test_seed: int
    beta: float
    profile_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def build_formal_oos_cases(config: Mapping[str, Any]) -> tuple[FormalOOSCase, ...]:
    training = tuple(int(value) for value in config["seed_protocol"]["formal_training_seeds"])
    testing = tuple(int(value) for value in config["seed_protocol"]["formal_test_seeds"])
    if training != tuple(range(2026081401, 2026081411)):
        raise ValueError("formal OOS training seed identity mismatch")
    if testing != tuple(range(2026081501, 2026081511)) or set(training) & set(testing):
        raise ValueError("formal OOS test seed identity mismatch")
    cases = tuple(
        FormalOOSCase(
            case_id=f"M2F2_formal_OOS_train{seed}_test{test_seed}_beta1p10_profileT03",
            run_kind="formal_OOS",
            tier_id="M2F2",
            seed=seed,
            test_seed=test_seed,
            beta=1.1,
            profile_id="T03",
        )
        for seed, test_seed in zip(training, testing, strict=True)
    )
    if len(cases) != 10 or len({case.case_id for case in cases}) != 10:
        raise ValueError("formal OOS matrix is not exactly ten paired cases")
    return cases


def formal_oos_orchestrator_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in OOS_ORCHESTRATOR_FILES:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def _base(output_root: Path) -> Path:
    return output_root / OOS_SUBDIRECTORY


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (_base(output_root) / "runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("formal OOS run path escapes controlled output root")
    return path


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = _base(output_root)
    path = base / "formal_OOS_run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("formal OOS run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _controlled_artifact_paths(output_root: Path, row: Mapping[str, str]) -> tuple[Path, Path]:
    run_id = str(row["run_id"]); validate_run_id(run_id)
    directory = (_base(output_root) / "runs" / run_id).resolve()
    result = Path(row["result_path"]).resolve()
    manifest = Path(row["manifest_path"]).resolve()
    if result != directory / "result.json" or manifest != directory / "manifest.json":
        raise ValueError("registry artifact path leaves formal OOS namespace")
    return result, manifest


def _validate_artifact(
    output_root: Path,
    row: Mapping[str, str],
    *,
    fingerprints: Mapping[str, str],
    orchestrator_sha256: str,
) -> dict[str, Any]:
    result_path, manifest_path = _controlled_artifact_paths(output_root, row)
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("formal OOS artifact is missing")
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("formal OOS manifest hash mismatch")
    manifest = _load_json(manifest_path)
    if manifest.get("artifact_state") != "finalized" or sha256_file(result_path) != manifest.get("result_sha256"):
        raise ValueError("formal OOS result is not finalized")
    result = _load_json(result_path)
    case = result.get("case") or {}
    if (
        result.get("finalized") is not True
        or result.get("run_id") != row["run_id"]
        or result.get("case_id") != row["case_id"]
        or result.get("status") != row["status"]
        or result.get("fingerprints") != dict(fingerprints)
        or result.get("formal_OOS_orchestrator_sha256") != orchestrator_sha256
        or manifest.get("fingerprints") != dict(fingerprints)
        or manifest.get("formal_OOS_orchestrator_sha256") != orchestrator_sha256
        or case.get("run_kind") != "formal_OOS"
        or str(case.get("seed")) != str(row["seed"])
        or str(case.get("test_seed")) != str(row["test_seed"])
        or case.get("profile_id") != row["profile_id"]
    ):
        raise ValueError("formal OOS artifact identity mismatch")
    return result


def _source_paths(root: Path) -> tuple[Path, Path, Path]:
    base = (root / SOURCE_OUTPUT_ROOT / SOURCE_SUBDIRECTORY).resolve()
    return (
        base / "formal_mechanism_run_registry.csv",
        base / "formal_mechanism_progress.json",
        (root / MECHANISM_AUDIT_PATH).resolve(),
    )


def _validate_source_evidence(
    *,
    root: Path,
    approval: Mapping[str, Any],
    fingerprints: Mapping[str, str],
) -> dict[int, dict[str, Any]]:
    registry_path, progress_path, audit_path = _source_paths(root)
    evidence = approval.get("mechanism_evidence") or {}
    expected_paths = (
        (root / evidence.get("registry_path", "")).resolve(),
        (root / evidence.get("progress_path", "")).resolve(),
        (root / evidence.get("audit_path", "")).resolve(),
    )
    if expected_paths != (registry_path, progress_path, audit_path):
        raise RuntimeError("reviewed mechanism evidence path leaves its approved namespace")
    for path, field in (
        (registry_path, "registry_sha256"),
        (progress_path, "progress_sha256"),
        (audit_path, "audit_sha256"),
    ):
        if not path.is_file() or sha256_file(path) != evidence.get(field):
            raise RuntimeError(f"reviewed mechanism evidence hash mismatch: {field}")
    audit = _load_json(audit_path)
    progress = _load_json(progress_path)
    global_artifacts = audit.get("global_artifacts") or {}
    if (
        evidence.get("registry_sha256") != global_artifacts.get("formal_mechanism_run_registry_sha256")
        or evidence.get("progress_sha256") != global_artifacts.get("formal_mechanism_progress_sha256")
        or audit.get("fingerprints") != dict(fingerprints)
        or progress.get("fingerprints") != dict(fingerprints)
        or audit.get("formal_orchestrator_sha256") != approval.get("source_formal_mechanism_orchestrator_sha256")
        or progress.get("formal_orchestrator_sha256") != approval.get("source_formal_mechanism_orchestrator_sha256")
    ):
        raise RuntimeError("local mechanism evidence is not bound to the PR #58 audit")
    audit_progress = audit.get("progress") or {}
    if evidence.get("required_decision") != "permit_mechanism_results_review_only":
        raise RuntimeError("reviewed mechanism evidence decision identity mismatch")
    empty_fields = (
        "missing_case_ids", "invalid_primary_run_ids", "failed_primary_run_ids",
        "duplicate_case_ids", "diagnostic_run_ids", "finalization_failure_run_ids",
    )
    if (
        audit_progress.get("completed_primary_run_count") != 50
        or audit_progress.get("required_primary_run_count") != 50
        or audit_progress.get("formal_mechanism_gate_passed") is not True
        or audit_progress.get("formal_OOS_authorized") is not False
        or audit_progress.get("next_decision") != evidence["required_decision"]
        or progress.get("formal_mechanism_gate_passed") is not True
        or progress.get("formal_OOS_authorized") is not False
        or progress.get("next_decision") != evidence["required_decision"]
        or audit.get("stop_boundary", {}).get("formal_OOS_runs_started") != 0
        or audit.get("stop_boundary", {}).get("algorithm_performance_runs_started") != 0
        or any(audit_progress.get(field) != [] or progress.get(field) != [] for field in empty_fields)
    ):
        raise RuntimeError("reviewed mechanism evidence gate is incomplete")
    rows = _read_source_registry(registry_path)
    source_orchestrator = str(approval["source_formal_mechanism_orchestrator_sha256"])
    audit_rows = {row["run_id"]: row for row in audit.get("runs", [])}
    selected = [
        row for row in rows
        if row.get("status") == "optimal"
        and not row.get("parent_run_id", "").strip()
        and row.get("profile_id") == "T03"
        and math.isclose(float(row.get("beta", -1.0)), 1.1, abs_tol=1e-12)
        and all(row.get(key) == value for key, value in fingerprints.items())
        and row.get("formal_orchestrator_sha256") == source_orchestrator
    ]
    if len(selected) != 10 or {int(row["seed"]) for row in selected} != set(range(2026081401, 2026081411)):
        raise RuntimeError("reviewed mechanism source set is not exactly ten beta=1.1/T03 runs")
    results: dict[int, dict[str, Any]] = {}
    source_root = root / SOURCE_OUTPUT_ROOT
    for row in selected:
        result = _validate_source_artifact(
            source_root, row,
            fingerprints=fingerprints,
            orchestrator_sha256=source_orchestrator,
        )
        reviewed = audit_rows.get(result["run_id"]) or {}
        if (
            reviewed.get("seed") != int(row["seed"])
            or reviewed.get("beta") != 1.1
            or reviewed.get("profile_id") != "T03"
            or reviewed.get("status") != "optimal"
            or reviewed.get("artifacts", {}).get("result_sha256") != sha256_file(Path(row["result_path"]))
            or reviewed.get("artifacts", {}).get("manifest_sha256") != row["manifest_sha256"]
        ):
            raise RuntimeError("source run identity is not bound to the compact PR #58 evidence")
        identities = result.get("science", {}).get("first_stage_plan_artifacts") or {}
        reviewed_identities = reviewed.get("science", {}).get("first_stage_plan_identities") or {}
        if set(identities) != set(REQUIRED_STRATEGIES) or set(reviewed_identities) != set(REQUIRED_STRATEGIES):
            raise RuntimeError("source first-stage plan set is incomplete")
        for strategy in REQUIRED_STRATEGIES:
            payload = _validate_formal_plan_artifact(
                output_root=source_root,
                source_run_id=result["run_id"],
                identity=identities[strategy],
            )
            for field in (
                "reserve_amount", "regular_purchase_sha256", "exact_training_objective",
                "training_joint_scenario_set_sha256", "finalized_plan_artifact_sha256",
            ):
                actual = identities[strategy].get(field)
                expected = reviewed_identities[strategy].get(field)
                if isinstance(actual, (int, float)):
                    if not math.isclose(float(actual), float(expected), abs_tol=1e-8):
                        raise RuntimeError("source plan differs from reviewed PR #58 identity")
                elif actual != expected:
                    raise RuntimeError("source plan differs from reviewed PR #58 identity")
            payload["finalized_plan_artifact_sha256"] = identities[strategy]["finalized_plan_artifact_sha256"]
        results[int(row["seed"])] = result
    return results


def validate_formal_oos_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_formal_extension_config(config_path)
    if config.get("status") != "frozen_for_pilot_execution":
        raise RuntimeError("reviewed M2 scientific baseline status changed")
    if not authorize:
        raise PermissionError("--authorize-formal-oos-execution is required")
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    expected_runner = {
        "namespace": OOS_NAMESPACE,
        "protocol": PROTOCOL_ID,
        "output_root": OOS_OUTPUT_ROOT,
        "formal_subdirectory": OOS_SUBDIRECTORY,
        "source_output_root": SOURCE_OUTPUT_ROOT,
        "source_subdirectory": SOURCE_SUBDIRECTORY,
    }
    if any(runner.get(key) != value for key, value in expected_runner.items()):
        raise RuntimeError("formal OOS runner identity mismatch")
    execution = runner.get("execution") or {}
    expected_execution = {
        "strictly_serial": True,
        "formal_OOS_execution_requires_explicit_authorization": True,
        "immutable_run_ids": True,
        "full_primary_batch_required": True,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
        "failed_primary_permanently_blocks_batch_gate": True,
        "reviewed_mechanism_evidence_is_read_only": True,
        "OOS_worker_reoptimization_or_plan_substitution_forbidden": True,
        "formal_OOS_primary_run_count": 10,
        "formal_OOS_plan_count": 50,
        "formal_OOS_recourse_evaluation_count": 100000,
        "algorithm_performance_authorized": False,
    }
    if any(execution.get(key) != value for key, value in expected_execution.items()):
        raise RuntimeError("formal OOS safety metadata mismatch")
    expected_limits = {
        "solver_call_seconds": 120,
        "OOS_plan_wall_seconds": 7200,
        "threads": 1,
    }
    if runner.get("limits") != expected_limits:
        raise RuntimeError("formal OOS frozen execution limits mismatch")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    expected_approval = {
        "approval_id": "phase6_m2_formal_oos_execution_v1_1",
        "status": OOS_STATUS,
        "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": OOS_NAMESPACE,
        "formal_OOS_primary_run_count": 10,
        "formal_OOS_plan_count": 50,
        "formal_OOS_recourse_evaluation_count": 100000,
        "explicit_cli_authorization_required": True,
        "formal_OOS_authorized": True,
        "algorithm_performance_authorized": False,
        "accept_prior_track_authorization": False,
    }
    if any(approval.get(key) != value for key, value in expected_approval.items()):
        raise RuntimeError("formal OOS approval metadata mismatch")
    actual = formal_extension_fingerprints(root, config_path, root / PILOT_RUNNER_PATH)
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("formal OOS scientific fingerprint mismatch")
    orchestrator = formal_oos_orchestrator_sha256(root)
    if approval.get("formal_OOS_orchestrator_sha256") != orchestrator:
        raise RuntimeError("formal OOS orchestrator fingerprint mismatch")
    source_results = _validate_source_evidence(
        root=root, approval=approval, fingerprints=actual,
    )
    build_formal_oos_cases(config)
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [root / path for path in OOS_ORCHESTRATOR_FILES]
    required += [
        config_path, runner_path, approval_path, root / MECHANISM_AUDIT_PATH,
        root / "requirements-gurobi-lock.txt",
    ]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    return {
        "config": config,
        "runner": runner,
        "approval": approval,
        "fingerprints": actual,
        "formal_OOS_orchestrator_sha256": orchestrator,
        "source_mechanism_results": source_results,
        "locked_environment": validate_locked_environment(root),
        "source": source,
    }


def _evaluate_plan_with_wall_limit(
    data: Any,
    regular_purchase: Mapping[str, Sequence[float]],
    reserve: float,
    *,
    solver_call_seconds: float,
    plan_wall_seconds: float,
    evaluator: Callable[..., EvaluationResult] | None = None,
    clock: Callable[[], float] = perf_counter,
) -> EvaluationResult:
    """Evaluate one plan exactly while enforcing its wall-clock deadline.

    The deadline is checked at every scenario boundary, and the remaining plan
    time also caps the next Gurobi call.  Consequently a timed-out plan cannot
    start another scenario or allow the runner to advance to another strategy.
    """

    if not math.isfinite(solver_call_seconds) or solver_call_seconds <= 0:
        raise ValueError("solver_call_seconds must be finite and positive")
    if not math.isfinite(plan_wall_seconds) or plan_wall_seconds <= 0:
        raise ValueError("OOS_plan_wall_seconds must be finite and positive")
    evaluator = evaluator or evaluate_first_stage
    started = clock()
    scenario_results: dict[str, Any] = {}
    infeasible: list[str] = []
    failed: list[str] = []
    for scenario in tuple(data.scenarios):
        remaining = plan_wall_seconds - (clock() - started)
        if remaining <= 0:
            raise TimeoutError("OOS_plan_wall_seconds exceeded before next scenario")
        partial = evaluator(
            data,
            regular_purchase,
            reserve,
            scenario_names=(scenario,),
            time_limit_seconds=min(solver_call_seconds, remaining),
            solver_threads=1,
        )
        scenario_results.update(partial.scenario_results)
        infeasible.extend(partial.infeasible_scenarios)
        failed.extend(partial.failed_scenarios)
        if partial.failed_scenarios or partial.status == "oracle_failure":
            scenario_result = partial.scenario_results.get(scenario)
            solver_status = str(getattr(scenario_result, "status", "unknown"))
            if solver_status in {"time_limit", "master_time_limit"}:
                raise TimeoutError(
                    f"Gurobi recourse solve reached {solver_status} for scenario {scenario}"
                )
            raise RuntimeError(
                f"recourse oracle failure for scenario {scenario}: {solver_status}"
            )
        if clock() - started > plan_wall_seconds:
            raise TimeoutError("OOS_plan_wall_seconds exceeded during scenario evaluation")

    first_stage_cost = regular_cost(data, regular_purchase)
    elapsed = clock() - started
    if elapsed > plan_wall_seconds:
        raise TimeoutError("OOS_plan_wall_seconds exceeded during result aggregation")
    if failed:
        return EvaluationResult(
            status="oracle_failure", regular_cost=first_stage_cost,
            robust_objective=None, worst_scenario=None, worst_recourse_cost=None,
            scenario_results=scenario_results,
            infeasible_scenarios=tuple(infeasible), failed_scenarios=tuple(failed),
            runtime_seconds=elapsed,
        )
    if infeasible:
        return EvaluationResult(
            status="infeasible_recourse", regular_cost=first_stage_cost,
            robust_objective=None, worst_scenario=None, worst_recourse_cost=None,
            scenario_results=scenario_results,
            infeasible_scenarios=tuple(infeasible), failed_scenarios=(),
            runtime_seconds=elapsed,
        )
    costs = {
        name: float(result.objective)
        for name, result in scenario_results.items()
        if result.objective is not None
    }
    worst = max(tuple(data.scenarios), key=lambda name: costs[name])
    worst_cost = costs[worst]
    return EvaluationResult(
        status="optimal", regular_cost=first_stage_cost,
        robust_objective=first_stage_cost + worst_cost,
        worst_scenario=worst, worst_recourse_cost=worst_cost,
        scenario_results=scenario_results,
        infeasible_scenarios=(), failed_scenarios=(), runtime_seconds=elapsed,
    )


def execute_formal_oos_science(**kwargs: Any) -> dict[str, Any]:
    root: Path = kwargs["project_root"]
    config = kwargs["config"]
    case: FormalOOSCase = kwargs["case"]
    progress = kwargs["progress"]
    source = kwargs["source_mechanism_result"]
    source_science = source["science"]
    identities = source_science.get("first_stage_plan_artifacts") or {}
    if tuple(identities) != REQUIRED_STRATEGIES:
        raise ValueError("formal OOS source plan set is incomplete")
    source_root = root / SOURCE_OUTPUT_ROOT
    plans: dict[str, dict[str, Any]] = {}
    for strategy in REQUIRED_STRATEGIES:
        plan = _validate_formal_plan_artifact(
            output_root=source_root,
            source_run_id=source["run_id"],
            identity=identities[strategy],
        )
        plan["finalized_plan_artifact_sha256"] = identities[strategy]["finalized_plan_artifact_sha256"]
        plans[strategy] = plan
    confirmation = _confirmation_config(root)
    matrix, reference, budget, expected_capacity = _validate_formal_baseline_before_generation(
        kwargs["matrix"], config, confirmation, beta=case.beta, scenario_count=2000,
    )
    progress("OOS_scenario_generation", {
        "training_seed": case.seed,
        "test_seed": case.test_seed,
        "scenario_count": 2000,
    })
    base_generated = generate_oos_data(
        matrix,
        matrix_path=kwargs["matrix_path"],
        tier_id="M2F2",
        test_seed=case.test_seed,
        budget=budget,
    )
    if any(
        not math.isclose(actual, expected, abs_tol=1e-9)
        for actual, expected in zip(
            base_generated.data.storage_capacity, expected_capacity, strict=True,
        )
    ):
        raise ValueError("formal OOS M2F2 storage capacity mismatch")
    latent = reconstruct_frozen_demand_latent(matrix, base_generated)
    generated = apply_m2c2_supply_disruption(
        base_generated,
        profile=resolve_supply_disruption_profile(
            _science_config_for_formal(root, config), "T03",
        ),
        demand_latent=latent,
        item_vulnerability_multiplier={"relief_food_1": 0.8, "relief_food_2": 1.2},
    )
    runner_limits = kwargs.get("runner_limits") or {
        "solver_call_seconds": 120,
        "OOS_plan_wall_seconds": 7200,
        "threads": 1,
    }
    seconds = float(runner_limits["solver_call_seconds"])
    plan_wall_seconds = float(runner_limits["OOS_plan_wall_seconds"])
    results: dict[str, Any] = {}
    for strategy in REQUIRED_STRATEGIES:
        plan = plans[strategy]
        progress(f"OOS_evaluate_{strategy}", {"strategy_id": strategy})
        started = perf_counter()
        with m2_model_context():
            evaluation = _evaluate_plan_with_wall_limit(
                generated.data,
                plan["regular_purchase"],
                float(plan["reserve_amount"]),
                solver_call_seconds=seconds,
                plan_wall_seconds=plan_wall_seconds,
            )
        metrics = aggregate_oos_evaluation(
            generated.data, evaluation, reserve=float(plan["reserve_amount"]),
        )
        if metrics["plan_oos_status"] != "complete_feasible":
            raise RuntimeError(
                f"unexpected_infeasible_recourse for {strategy}: {metrics['plan_oos_status']}"
            )
        results[strategy] = {
            "strategy_id": strategy,
            "source_plan_artifact_sha256": plan["finalized_plan_artifact_sha256"],
            "source_plan_training_joint_scenario_set_sha256": plan["training_joint_scenario_set_sha256"],
            "source_plan_exact_training_objective": plan["exact_training_objective"],
            "reserve_amount": plan["reserve_amount"],
            "regular_purchase_sha256": plan["regular_purchase_sha256"],
            "test_joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
            "wall_seconds": perf_counter() - started,
            "metrics": metrics,
            "cross_item_allocation": _cross_item_from_evaluation(
                generated.data, evaluation, 1e-7,
            ),
        }
    science = {
        "tier_id": "M2F2",
        "seed": case.seed,
        "test_seed": case.test_seed,
        "beta": case.beta,
        "profile_id": case.profile_id,
        "budget": budget,
        "reference_budget": reference,
        "source_mechanism_run_id": source["run_id"],
        "source_training_joint_scenario_set_sha256": source_science["joint_scenario_set_sha256"],
        "test_joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
        "test_scenario_component_set_sha256": _confirmation_component_hashes(generated),
        "test_scenario_identity_count": len(generated.scenario_identities),
        "strategy_results": results,
        "solver": "gurobi_direct",
        "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2",
        "threads": 1,
        "execution_limits": {
            "solver_call_seconds": seconds,
            "OOS_plan_wall_seconds": plan_wall_seconds,
            "threads": 1,
        },
    }
    _derive_probe(science, case.as_dict(), source)
    return science


def _write_terminal_diagnostic(
    directory: Path, *, run_id: str, case_id: str, stage: str,
    status: str, error: BaseException,
) -> None:
    failure = {
        "stage": stage,
        "status": status,
        "message": f"{type(error).__name__}: {error}"[:1000],
        "exception_type": type(error).__name__,
    }
    payload = {
        "run_id": run_id,
        "case_id": case_id,
        "status": status,
        "current_stage": stage,
        "completed_stage_count": 0,
        "failure": failure,
        "updated_at_utc": utc_now(),
    }
    for name in ("runner_exception.json", "status_summary.json", "heartbeat.json"):
        try:
            atomic_write_json(directory / name, payload)
        except Exception:
            pass


def _finalization_failure_ids(base: Path) -> list[str]:
    if not (base / "runs").is_dir():
        return []
    return sorted({
        path.parent.name
        for name in ("runner_exception.json", "registry_failure.json", "progress_failure.json")
        for path in (base / "runs").glob(f"*/{name}")
    })


def update_formal_oos_progress(
    *, output_root: Path, config: Mapping[str, Any], fingerprints: Mapping[str, str],
    orchestrator_sha256: str, source_mechanism_results: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    base = _base(output_root)
    with exclusive_file_lock(base / ".progress.lock"):
        rows = _read_registry(base / "formal_OOS_run_registry.csv")
        matching = [
            row for row in rows
            if all(row.get(key) == value for key, value in fingerprints.items())
            and row.get("formal_OOS_orchestrator_sha256") == orchestrator_sha256
        ]
        primary: dict[str, dict[str, Any]] = {}
        invalid: list[str] = []
        failed: list[str] = []
        diagnostics: list[str] = []
        duplicates: list[str] = []
        for row in matching:
            try:
                result = _validate_artifact(
                    output_root, row,
                    fingerprints=fingerprints,
                    orchestrator_sha256=orchestrator_sha256,
                )
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(result["run_id"]); continue
                case_id = result["case_id"]
                if case_id in primary:
                    duplicates.append(case_id); continue
                if result["status"] != "optimal":
                    failed.append(result["run_id"]); primary[case_id] = result; continue
                source = source_mechanism_results[int(result["case"]["seed"])]
                _derive_probe(result["science"], result["case"], source)
                primary[case_id] = result
            except Exception:
                invalid.append(row.get("run_id", ""))
        cases = build_formal_oos_cases(config)
        missing = [case.case_id for case in cases if case.case_id not in primary]
        finalization = _finalization_failure_ids(base)
        complete = bool(
            len(primary) == 10
            and not missing and not invalid and not failed and not diagnostics
            and not duplicates and not finalization
        )
        strategy_count = sum(
            len((result.get("science") or {}).get("strategy_results") or {})
            for result in primary.values() if result.get("status") == "optimal"
        )
        recourse_count = sum(
            int(strategy["metrics"]["optimal_scenario_count"])
            for result in primary.values() if result.get("status") == "optimal"
            for strategy in result["science"]["strategy_results"].values()
        )
        if complete and (strategy_count != 50 or recourse_count != 100000):
            complete = False
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints),
            "formal_OOS_orchestrator_sha256": orchestrator_sha256,
            "required_primary_run_count": 10,
            "completed_primary_run_count": len(primary),
            "completed_plan_count": strategy_count,
            "completed_exact_recourse_evaluation_count": recourse_count,
            "missing_case_ids": missing,
            "invalid_primary_run_ids": sorted(invalid),
            "failed_primary_run_ids": sorted(failed),
            "duplicate_case_ids": sorted(set(duplicates)),
            "diagnostic_run_ids": sorted(diagnostics),
            "finalization_failure_run_ids": finalization,
            "formal_OOS_gate_passed": complete,
            "next_decision": "permit_OOS_results_review_only" if complete else "formal_OOS_incomplete_or_failed",
            "algorithm_performance_authorized": False,
            "formal_extension_complete": False,
            "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "formal_OOS_progress.json", payload)
        return payload


def _validate_diagnostic_parent(output_root: Path, *, case_id: str, parent_run_id: str) -> None:
    validate_run_id(parent_run_id)
    rows = _read_registry(_base(output_root) / "formal_OOS_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1:
        raise ValueError("diagnostic parent_run_id must identify one existing OOS run")
    parent = matches[0]
    if parent.get("parent_run_id", "").strip() or parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must be a primary run of the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must have a failure terminal state")


def run_formal_oos_case(
    *, root: Path, output_root: Path, matrix_path: Path, config: Mapping[str, Any],
    fingerprints: Mapping[str, str], orchestrator_sha256: str,
    locked_environment: Mapping[str, str], source: Mapping[str, Any],
    source_mechanism_results: Mapping[int, Mapping[str, Any]],
    case: FormalOOSCase, run_id: str, parent_run_id: str | None = None,
    runner_limits: Mapping[str, Any] | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("formal OOS run_id is immutable")
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
                "failure": None, "updated_at_utc": utc_now(),
            }
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)

        try:
            matrix = load_phase6_matrix(matrix_path)
            science = (science_executor or execute_formal_oos_science)(
                project_root=root,
                matrix=matrix,
                matrix_path=matrix_path,
                config=config,
                case=case,
                source_mechanism_result=source_mechanism_results[case.seed],
                progress=progress,
                runner_limits=runner_limits or {
                    "solver_call_seconds": 120,
                    "OOS_plan_wall_seconds": 7200,
                    "threads": 1,
                },
            )
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"
            failure = {
                "stage": stages[-1]["stage"] if stages else "initialization",
                "status": status, "message": "KeyboardInterrupt",
                "exception_type": "KeyboardInterrupt",
            }
        except Exception as exc:
            text = str(exc).lower()
            status = "timeout" if isinstance(exc, TimeoutError) or "time_limit" in text else "stage_failure"
            failure = {
                "stage": stages[-1]["stage"] if stages else "initialization",
                "status": status, "message": f"{type(exc).__name__}: {exc}"[:1000],
                "exception_type": type(exc).__name__,
            }
        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(
                solver_preference=("gurobi",), project_root=root, solver_threads=1,
            )
            result = {
                "run_id": run_id, "parent_run_id": parent_run_id,
                "case_id": case.case_id, "case": case.as_dict(),
                "status": status, "finalized": True, "science": science,
                "stages": stages, "failure": failure, "wall_seconds": wall,
                "peak_memory_mb": peak, "fingerprints": dict(fingerprints),
                "formal_OOS_orchestrator_sha256": orchestrator_sha256,
                "git_sha": source["commit_sha"], "git_tree_sha": source["tree_sha"],
                "finished_at_utc": utc_now(),
            }
            result_path = directory / "result.json"; manifest_path = directory / "manifest.json"
            compact = {
                "run_id": run_id, "case_id": case.case_id, "status": status,
                "current_stage": failure.get("stage") if failure else None,
                "completed_stage_count": len(stages), "failure": compact_failure(failure),
                "updated_at_utc": utc_now(),
            }
            finalization_stage = "artifact_finalization"
            atomic_write_json(checkpoint, {
                "run_id": run_id, "case": case.as_dict(), "status": status,
                "completed_stages": stages, "failure": compact_failure(failure),
                "updated_at_utc": utc_now(),
            })
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {
                "artifact_state": "finalized", "run_id": run_id, "case_id": case.case_id,
                "result_sha256": sha256_file(result_path),
                "checkpoint_sha256": sha256_file(checkpoint),
                "status_summary_sha256": sha256_file(status_path),
                "heartbeat_sha256": sha256_file(heartbeat),
                "fingerprints": dict(fingerprints),
                "formal_OOS_orchestrator_sha256": orchestrator_sha256,
                "source": dict(source), "locked_environment": dict(locked_environment),
                "runtime_context": runtime,
            })
            source_run_id = (science or {}).get("source_mechanism_run_id", "")
            row = {
                "run_id": run_id, "parent_run_id": parent_run_id or "",
                "case_id": case.case_id, "run_kind": case.run_kind,
                "tier_id": case.tier_id, "seed": case.seed, "test_seed": case.test_seed,
                "beta": case.beta, "profile_id": case.profile_id,
                "source_mechanism_run_id": source_run_id, "status": status,
                "wall_seconds": wall, "peak_memory_mb": peak, **dict(fingerprints),
                "formal_OOS_orchestrator_sha256": orchestrator_sha256,
                "result_path": str(result_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": sha256_file(manifest_path),
                "failure_stage": failure.get("stage") if failure else "",
                "updated_at_utc": result["finished_at_utc"],
            }
            finalization_stage = "registry_finalization"; _write_registry(output_root, row)
            finalization_stage = "progress_finalization"
            formal_progress = update_formal_oos_progress(
                output_root=output_root, config=config, fingerprints=fingerprints,
                orchestrator_sha256=orchestrator_sha256,
                source_mechanism_results=source_mechanism_results,
            )
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(
                directory, run_id=run_id, case_id=case.case_id,
                stage=finalization_stage, status="interrupted", error=exc,
            )
            raise
        except Exception as exc:
            _write_terminal_diagnostic(
                directory, run_id=run_id, case_id=case.case_id,
                stage=finalization_stage, status="runner_exception", error=exc,
            )
            raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "formal_OOS_progress": formal_progress}


def run_formal_oos(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_formal_oos_preflight(
        root=root, config_path=config_path, runner_path=runner_path,
        approval_path=approval_path, authorize=authorize,
    )
    cases = build_formal_oos_cases(preflight["config"]); all_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary formal OOS execution must run the complete frozen ten-case batch")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("formal OOS diagnostic execution requires one case_id and parent_run_id")
    requested = set(case_ids or all_ids)
    if requested - all_ids:
        raise ValueError("unknown formal OOS case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OOS_OUTPUT_ROOT; results: list[dict[str, Any]] = []
    base = _base(output_root)
    with exclusive_file_lock(base / ".serial-execution.lock", timeout_seconds=1.0):
        if parent_run_id is None and base.exists() and any(
            path.name != ".serial-execution.lock" for path in base.iterdir()
        ):
            raise RuntimeError("primary formal OOS batch requires an empty OOS namespace")
        if parent_run_id is not None:
            _validate_diagnostic_parent(
                output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id,
            )
        for case in selected:
            result = run_formal_oos_case(
                root=root, output_root=output_root,
                matrix_path=root / "configs/phase6_experiment_matrix.yaml",
                config=preflight["config"], fingerprints=preflight["fingerprints"],
                orchestrator_sha256=preflight["formal_OOS_orchestrator_sha256"],
                locked_environment=preflight["locked_environment"], source=preflight["source"],
                source_mechanism_results=preflight["source_mechanism_results"],
                case=case, run_id=f"{run_id_prefix}_{case.case_id}",
                runner_limits=preflight["runner"]["limits"],
                parent_run_id=parent_run_id, science_executor=science_executor,
            )
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

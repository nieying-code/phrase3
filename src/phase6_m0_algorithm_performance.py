"""One-time guarded executor for the frozen M0 E3 performance matrix."""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
from typing import Any, Callable, Mapping, Sequence

import yaml

from .model_common import validate_gurobi_runtime
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_json, read_lf_bytes
from .phase6_locking import exclusive_file_lock
from .phase6_protocol import load_phase6_matrix
from .phase6_reporting import validate_e3_run_artifacts
from .phase6_runner import (
    PHASE6_E3_COMPONENT_FILES,
    PHASE6_E3_REQUIREMENTS_FILE,
    _e3_component_code_sha256,
    _scientific_config_sha256,
    load_phase6_runner_config,
    run_phase6_sequence,
)
from .reproducibility import sha256_file, validate_execution_source


NAMESPACE = "phase6_m0_e3_algorithm_performance_v1_0"
STATUS = "frozen_for_m0_e3_algorithm_performance_execution"
RUNNER_PATH = "configs/phase6_m0_algorithm_performance_runner.yaml"
APPROVAL_PATH = "configs/phase6_m0_algorithm_performance_approval_v1_0.yaml"
ORCHESTRATOR_FILES = (
    "src/phase6_m0_algorithm_performance.py",
    "src/run_phase6_m0_algorithm_performance.py",
    "src/phase6_m0_algorithm_performance_status.py",
    RUNNER_PATH,
)
EXPECTED_ALGORITHMS = ("standard_ccg_cold", "spw_ccg_warm")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9._-]+$")
RunExecutor = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PerformanceCase:
    position: int
    tier_id: str
    seed: int
    timing_repetitions: int
    algorithm_execution_count: int

    @property
    def case_id(self) -> str:
        return f"M0_E3_{self.tier_id}_seed{self.seed}"

    def as_dict(self) -> dict[str, Any]:
        return {"case_id": self.case_id, **asdict(self)}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_yaml(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected YAML object: {path}")
    return payload


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def _sha256_lf_text(path: Path) -> str:
    payload = path.read_bytes().replace(b"\r\n", b"\n")
    if b"\r" in payload:
        raise RuntimeError(f"reviewed text evidence contains a lone CR byte: {path}")
    return hashlib.sha256(payload).hexdigest()


def algorithm_performance_orchestrator_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in ORCHESTRATOR_FILES:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def _formal_seeds(matrix: Mapping[str, Any], count: int) -> tuple[int, ...]:
    seeds = tuple(int(value) for value in matrix["seed_plan"]["formal_training_seeds"])
    return seeds[:count]


def build_performance_cases(matrix: Mapping[str, Any]) -> tuple[PerformanceCase, ...]:
    algorithms = tuple(str(value) for value in matrix["algorithm_comparison"]["algorithms"])
    if algorithms != EXPECTED_ALGORITHMS:
        raise ValueError(f"frozen E3 algorithm identity mismatch: {algorithms}")
    factors = tuple(float(value) for value in matrix["budget_plan"]["formal_factors"])
    if factors != (0.9, 1.1, 1.3):
        raise ValueError("frozen E3 budget factors changed")
    tiers = {str(row["id"]): row for row in matrix["scale_tiers"]}
    ordered = tuple(str(value) for value in matrix["algorithm_comparison"]["tiers"])
    if ordered != ("V1", "V2", "P1", "P2"):
        raise ValueError("frozen E3 tier order changed")
    cases: list[PerformanceCase] = []
    position = 0
    for tier_id in ordered:
        tier = tiers[tier_id]
        count = int(tier["formal_seed_count"])
        repetitions = int(tier["timing_repetitions"])
        if tier_id == "V2" and repetitions != 3:
            raise ValueError("V2 technical repetition count changed")
        for seed in _formal_seeds(matrix, count):
            position += 1
            cases.append(PerformanceCase(
                position=position,
                tier_id=tier_id,
                seed=seed,
                timing_repetitions=repetitions,
                algorithm_execution_count=len(factors) * len(algorithms) * repetitions,
            ))
    result = tuple(cases)
    execution_count = sum(case.algorithm_execution_count for case in result)
    if len(result) != 21 or execution_count != 246:
        raise ValueError(f"frozen E3 matrix must be 21 runs and 246 executions; got {len(result)}/{execution_count}")
    if int(matrix["workload_estimation"]["E3_algorithm_executions"]) != 246:
        raise ValueError("matrix workload_estimation no longer freezes 246 executions")
    return result


def _git(root: Path, *args: str) -> str:
    return subprocess.check_output(("git", *args), cwd=root, text=True).strip()


def _validate_synchronized_main(root: Path, *, reviewed_base_commit: str) -> dict[str, str]:
    """Prove execution is on the locally fetched, reviewed remote main tip.

    This deliberately does not fetch, pull, switch branches, or otherwise
    mutate Git state. The operator must synchronize refs before execution.
    """

    branch = _git(root, "branch", "--show-current")
    if branch != "main":
        raise RuntimeError("formal algorithm performance must execute from main")
    try:
        upstream_remote = _git(root, "config", "--get", "branch.main.remote")
        upstream_merge = _git(root, "config", "--get", "branch.main.merge")
        head = _git(root, "rev-parse", "HEAD")
        remote_main = _git(root, "rev-parse", "refs/remotes/origin/main")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("formal algorithm performance requires a configured and fetched origin/main") from exc
    if upstream_remote != "origin" or upstream_merge != "refs/heads/main":
        raise RuntimeError("local main must track origin/main")
    if head != remote_main:
        raise RuntimeError("formal algorithm performance requires main synchronized with origin/main")
    try:
        _git(root, "merge-base", "--is-ancestor", reviewed_base_commit, head)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError("reviewed PR #75 base is not an ancestor of synchronized main") from exc
    return {
        "branch": branch,
        "upstream_remote": upstream_remote,
        "upstream_merge": upstream_merge,
        "head": head,
        "remote_main": remote_main,
    }


def _validate_reviewed_evidence(root: Path, approval: Mapping[str, Any], actual: Mapping[str, str]) -> None:
    evidence = approval["reviewed_gate_evidence"]
    projection_path = root / str(evidence["final_projection_audit_path"])
    e1_path = root / str(evidence["E1_formal_audit_path"])
    if _sha256_lf_text(projection_path) != evidence["final_projection_audit_sha256"]:
        raise RuntimeError("reviewed final projection audit hash mismatch")
    if _sha256_lf_text(e1_path) != evidence["E1_formal_audit_sha256"]:
        raise RuntimeError("reviewed E1 audit hash mismatch")
    projection_audit = _load_json(projection_path)
    fingerprints = projection_audit["fingerprints"]
    expected_projection = {
        "scientific_config_sha256": actual["scientific_config_sha256"],
        "e3_component_sha256": actual["e3_component_sha256"],
        "e3_runner_config_sha256": actual["runner_config_sha256"],
        "environment_sha256": actual["environment_sha256"],
    }
    for field, expected in expected_projection.items():
        if fingerprints.get(field) != expected:
            raise RuntimeError(f"reviewed compute gate fingerprint mismatch: {field}")
    gate = projection_audit["compute_gate"]
    e3 = projection_audit["e3_gate_inputs"]
    if gate.get("compute_gate_passed") is not True or gate.get("formal_execution_authorized") is not True:
        raise RuntimeError("reviewed M0 compute gate is not authorized")
    if e3.get("completed_run_count") != 12 or e3.get("required_run_count") != 12:
        raise RuntimeError("reviewed M0 E3 pilot coverage is not 12/12")
    if any(e3.get(field) for field in ("missing_runs", "failed_primary_runs", "artifact_invalid_runs", "duplicate_primary_runs", "diagnostic_attempts")):
        raise RuntimeError("reviewed M0 E3 pilot evidence contains exceptions")
    e1 = _load_json(e1_path)
    counts = e1["counts"]
    if counts.get("primary_run_count") != 14 or counts.get("completed_work_unit_count") != 45:
        raise RuntimeError("reviewed E1 exactness evidence is incomplete")
    if counts.get("failed_primary_run_count") != 0:
        raise RuntimeError("reviewed E1 exactness evidence contains failures")
    consistency = e1["numerical_consistency"]
    if consistency.get("all_objective_differences_within_plan_tolerance") is not True:
        raise RuntimeError("reviewed E1 objective consistency gate is not satisfied")
    if consistency.get("all_exact_evaluations_optimal") is not True:
        raise RuntimeError("reviewed E1 exact recourse evaluations are incomplete")


def validate_preflight(
    *, root: Path, runner_path: Path, approval_path: Path,
    require_execution_branch: bool,
) -> dict[str, Any]:
    runner = _load_yaml(runner_path)
    approval = _load_yaml(approval_path)
    if runner.get("namespace") != NAMESPACE or approval.get("runner_namespace") != NAMESPACE:
        raise RuntimeError("algorithm performance namespace mismatch")
    if approval.get("status") != STATUS:
        raise RuntimeError("algorithm performance approval is not frozen")
    expected_auth = {
        "M0_E3_algorithm_performance_authorized": True,
        "M2_formal_authorized": False,
        "M2_formal_OOS_authorized": False,
        "M2_1_authorized": False,
        "other_formal_experiments_authorized": False,
    }
    if approval.get("authorizations") != expected_auth or runner.get("authorizations") != expected_auth:
        raise RuntimeError("authorization scope is not exact")
    matrix_path = root / str(runner["matrix_path"])
    e3_runner_path = root / str(runner["e3_runner_config_path"])
    matrix = load_phase6_matrix(matrix_path)
    e3_config = load_phase6_runner_config(e3_runner_path)
    cases = build_performance_cases(matrix)
    validate_execution_source(
        root,
        required_tracked_paths=(
            matrix_path, e3_runner_path, runner_path, approval_path,
            root / PHASE6_E3_REQUIREMENTS_FILE,
            *(root / relative for relative in PHASE6_E3_COMPONENT_FILES),
            *(root / relative for relative in ORCHESTRATOR_FILES),
        ),
    )
    actual = {
        "scientific_config_sha256": _scientific_config_sha256(matrix),
        "e3_component_sha256": _e3_component_code_sha256(root),
        "runner_config_sha256": sha256_file(e3_runner_path),
        "environment_sha256": environment_sha256(validate_locked_environment(root)),
        "algorithm_performance_orchestrator_sha256": algorithm_performance_orchestrator_sha256(root),
    }
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("approved M0 algorithm performance fingerprint mismatch")
    artifacts = approval["artifact_sha256"]
    paths = {
        "runner_config": runner_path,
        "orchestrator_module": root / "src/phase6_m0_algorithm_performance.py",
        "cli": root / "src/run_phase6_m0_algorithm_performance.py",
        "status_module": root / "src/phase6_m0_algorithm_performance_status.py",
    }
    for name, path in paths.items():
        if artifacts.get(name) != sha256_file(path):
            raise RuntimeError(f"approved execution artifact mismatch: {name}")
    _validate_reviewed_evidence(root, approval, actual)
    synchronized_main = None
    if require_execution_branch:
        synchronized_main = _validate_synchronized_main(
            root,
            reviewed_base_commit=str(approval["review_base_commit"]),
        )
    validate_gurobi_runtime()
    limits = runner["limits"]
    if limits != {"threads": 1, "optimizer_version": "13.0.2", "gurobipy_version": "13.0.2", "interface": "gurobi_direct"}:
        raise RuntimeError("solver limits changed")
    return {
        "runner": runner, "approval": approval, "matrix": matrix,
        "e3_config": e3_config, "cases": cases, "fingerprints": actual,
        "synchronized_main": synchronized_main,
    }


def _compatibility_projection(*, matrix: Mapping[str, Any], fingerprints: Mapping[str, str], approval: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "matrix_id": matrix["matrix_id"],
        "scientific_config_sha256": fingerprints["scientific_config_sha256"],
        "runner_config_sha256": fingerprints["runner_config_sha256"],
        "e3_component_sha256": fingerprints["e3_component_sha256"],
        "environment_sha256": fingerprints["environment_sha256"],
        "required_run_count": 12,
        "completed_run_count": 12,
        "failed_primary_runs": [], "artifact_invalid_runs": [],
        "duplicate_primary_runs": [], "missing_runs": [],
        "status": "passed", "compute_gate_passed": True,
        "formal_execution_authorized": True,
        "source_reviewed_audit_sha256": approval["reviewed_gate_evidence"]["final_projection_audit_sha256"],
        "role": "immutable compatibility projection reconstructed from reviewed PR33 audit for the isolated M0 E3 namespace",
    }


def _registry_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def update_batch_projection(*, execution_root: Path, matrix: Mapping[str, Any], cases: Sequence[PerformanceCase], fingerprints: Mapping[str, str], orchestrator_sha256: str) -> dict[str, Any]:
    base = execution_root / "experiments/phase6"
    registry_path = base / "run_registry.csv"
    rows = _registry_rows(registry_path)
    expected = {case.case_id: case for case in cases}
    primary: dict[str, list[dict[str, str]]] = {case_id: [] for case_id in expected}
    diagnostics: list[str] = []
    for row in rows:
        run_id = row.get("run_id", "")
        case_id = next((case_id for case_id in expected if run_id.endswith(case_id)), None)
        if row.get("parent_run_id", "").strip():
            diagnostics.append(run_id)
        elif case_id is not None:
            primary[case_id].append(row)
    missing = [case_id for case_id, items in primary.items() if not items]
    duplicates = [case_id for case_id, items in primary.items() if len(items) > 1]
    failed: list[str] = []
    invalid: list[dict[str, str]] = []
    completed_pairs = 0
    completed_executions = 0
    maximum_objective_difference = 0.0
    for case_id, items in primary.items():
        if len(items) != 1:
            continue
        row = items[0]
        if row.get("status") != "optimal":
            failed.append(row.get("run_id", case_id)); continue
        try:
            result = validate_e3_run_artifacts(row)
            case = expected[case_id]
            if result.get("tier_id") != case.tier_id or int(result.get("seed")) != case.seed:
                raise ValueError("formal E3 result case identity mismatch")
            if result.get("fingerprints") != {key: fingerprints[key] for key in ("scientific_config_sha256", "runner_config_sha256", "e3_component_sha256", "environment_sha256")}:
                raise ValueError("formal E3 result fingerprint mismatch")
            comparisons = result.get("comparisons", [])
            if len(comparisons) != 3:
                raise ValueError("formal E3 result does not contain three budget pairs")
            for comparison in comparisons:
                if comparison.get("status") != "optimal":
                    raise ValueError("formal E3 budget pair is not optimal")
                difference = float(comparison["objective_difference"])
                tolerance = float(comparison["consistency_tolerance"])
                if not all(math.isfinite(value) and value >= 0.0 for value in (difference, tolerance)):
                    raise ValueError("formal E3 objective evidence is non-finite or negative")
                if difference > tolerance:
                    raise ValueError("formal E3 cold/warm objective mismatch")
                cold = comparison["cold"]["repetitions"]
                warm = comparison["warm"]["repetitions"]
                if len(cold) != case.timing_repetitions or len(warm) != case.timing_repetitions:
                    raise ValueError("technical repetition count mismatch")
                completed_executions += len(cold) + len(warm)
                completed_pairs += 1
                maximum_objective_difference = max(maximum_objective_difference, difference)
        except Exception as exc:
            invalid.append({"run_id": row.get("run_id", ""), "message": f"{type(exc).__name__}: {exc}"})
    gate = not (missing or duplicates or failed or invalid or diagnostics) and completed_pairs == 63 and completed_executions == 246
    payload = {
        "status": "complete" if gate else "incomplete",
        "fingerprints": dict(fingerprints),
        "algorithm_performance_orchestrator_sha256": orchestrator_sha256,
        "required_primary_run_count": 21,
        "completed_primary_run_count": sum(len(items) == 1 and items[0].get("status") == "optimal" for items in primary.values()),
        "required_budget_pair_count": 63, "completed_budget_pair_count": completed_pairs,
        "required_algorithm_execution_count": 246, "completed_algorithm_execution_count": completed_executions,
        "maximum_cold_warm_objective_difference": maximum_objective_difference,
        "missing_case_ids": missing, "failed_primary_run_ids": failed,
        "duplicate_case_ids": duplicates, "invalid_primary_runs": invalid,
        "diagnostic_run_ids": diagnostics,
        "M0_E3_algorithm_performance_gate_passed": gate,
        "M2_formal_authorized": False, "M2_formal_OOS_authorized": False,
        "M2_1_authorized": False, "other_formal_experiments_authorized": False,
        "updated_at_utc": utc_now(),
    }
    atomic_write_json(base / "algorithm_performance_projection.json", payload)
    atomic_write_json(base / "algorithm_performance_status_summary.json", payload)
    return payload


def _write_orchestrator_failure(*, execution_root: Path, run_id: str | None, case_id: str | None, exc: BaseException) -> None:
    base = execution_root / "experiments/phase6"
    payload = {
        "status": "interrupted" if isinstance(exc, KeyboardInterrupt) else "runner_exception",
        "run_id": run_id,
        "case_id": case_id,
        "exception_type": type(exc).__name__,
        "message": str(exc)[:4096],
        "updated_at_utc": utc_now(),
        "M0_E3_algorithm_performance_gate_passed": False,
    }
    try:
        atomic_write_json(base / "algorithm_performance_orchestrator_failure.json", payload)
        atomic_write_json(base / "algorithm_performance_status_summary.json", payload)
    except Exception:
        # Preserve the original exception. The existing E3 runner owns its own
        # finalized run-level evidence; this is the bounded batch-level fallback.
        pass


def run_batch(*, root: Path, runner_path: Path, approval_path: Path, authorize: bool, run_id_prefix: str, run_executor: RunExecutor = run_phase6_sequence) -> dict[str, Any]:
    if not authorize:
        raise RuntimeError("explicit --authorize-m0-e3-algorithm-performance is required")
    if not run_id_prefix or SAFE_RUN_ID.fullmatch(run_id_prefix) is None or ".." in run_id_prefix:
        raise ValueError("unsafe run_id_prefix")
    context = validate_preflight(root=root, runner_path=runner_path, approval_path=approval_path, require_execution_branch=True)
    runner = context["runner"]; matrix = context["matrix"]; cases = context["cases"]
    output_root = (root / str(runner["output_root"])).resolve()
    execution_root = output_root / str(runner["formal_subdirectory"])
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError("primary M0 E3 output namespace must not already exist")
    orchestrator = context["fingerprints"]["algorithm_performance_orchestrator_sha256"]
    with exclusive_file_lock(output_root / ".batch.lock", timeout_seconds=0.0):
        base = execution_root / "experiments/phase6"
        base.mkdir(parents=True, exist_ok=True)
        atomic_write_json(base / "pilot_throughput_projection.json", _compatibility_projection(matrix=matrix, fingerprints=context["fingerprints"], approval=context["approval"]))
        latest: dict[str, Any] = {}
        active_case: PerformanceCase | None = None
        active_run_id: str | None = None
        try:
            for active_case in cases:
                active_run_id = f"{run_id_prefix}_{active_case.case_id}"
                resolved_run = (base / "runs" / active_run_id).resolve()
                if base.resolve() not in resolved_run.parents:
                    raise ValueError("run path escapes controlled M0 E3 output root")
                result = run_executor(
                    matrix_path=root / str(runner["matrix_path"]),
                    runner_config_path=root / str(runner["e3_runner_config_path"]),
                    output_root=execution_root,
                    tier_id=active_case.tier_id,
                    seed=active_case.seed,
                    execution_mode="formal",
                    run_id=active_run_id,
                    resume=False,
                    parent_run_id=None,
                )
                latest = update_batch_projection(execution_root=execution_root, matrix=matrix, cases=cases, fingerprints=context["fingerprints"], orchestrator_sha256=orchestrator)
                if result.get("status") != "optimal":
                    return latest
            return latest
        except BaseException as exc:
            _write_orchestrator_failure(
                execution_root=execution_root,
                run_id=active_run_id,
                case_id=active_case.case_id if active_case else None,
                exc=exc,
            )
            raise


def run_diagnostic(
    *, root: Path, runner_path: Path, approval_path: Path, authorize: bool,
    run_id_prefix: str, case_id: str, parent_run_id: str,
    run_executor: RunExecutor = run_phase6_sequence,
) -> dict[str, Any]:
    """Run one explicitly linked diagnostic without repairing the primary gate."""

    if not authorize:
        raise RuntimeError("explicit --authorize-m0-e3-algorithm-performance is required")
    if not run_id_prefix or SAFE_RUN_ID.fullmatch(run_id_prefix) is None or ".." in run_id_prefix:
        raise ValueError("unsafe run_id_prefix")
    if SAFE_RUN_ID.fullmatch(parent_run_id or "") is None:
        raise ValueError("unsafe parent_run_id")
    context = validate_preflight(
        root=root, runner_path=runner_path, approval_path=approval_path,
        require_execution_branch=True,
    )
    runner = context["runner"]
    cases = tuple(context["cases"])
    case = next((row for row in cases if row.case_id == case_id), None)
    if case is None:
        raise ValueError("diagnostic case_id is not in the frozen matrix")
    output_root = (root / str(runner["output_root"])).resolve()
    execution_root = output_root / str(runner["formal_subdirectory"])
    base = execution_root / "experiments/phase6"
    rows = _registry_rows(base / "run_registry.csv")
    parents = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(parents) != 1:
        raise RuntimeError("diagnostic parent_run_id must identify exactly one primary run")
    parent = parents[0]
    if parent.get("parent_run_id", "").strip():
        raise RuntimeError("diagnostic parent must be a primary run")
    if parent.get("status") in ("optimal", "running", ""):
        raise RuntimeError("diagnostic parent must have a failed or timeout terminal state")
    expected_suffix = case.case_id
    if not parent_run_id.endswith(expected_suffix):
        raise RuntimeError("diagnostic parent does not belong to case_id")
    run_id = f"{run_id_prefix}_{case.case_id}_diagnostic"
    if any(row.get("run_id") == run_id for row in rows):
        raise RuntimeError("diagnostic run_id already exists")
    result = run_executor(
        matrix_path=root / str(runner["matrix_path"]),
        runner_config_path=root / str(runner["e3_runner_config_path"]),
        output_root=execution_root,
        tier_id=case.tier_id,
        seed=case.seed,
        execution_mode="formal",
        run_id=run_id,
        resume=False,
        parent_run_id=parent_run_id,
    )
    update_batch_projection(
        execution_root=execution_root,
        matrix=context["matrix"], cases=cases,
        fingerprints=context["fingerprints"],
        orchestrator_sha256=context["fingerprints"]["algorithm_performance_orchestrator_sha256"],
    )
    return result

"""Audited, disabled-by-default runner for the frozen M2.1 formal test batch."""

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

from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes, sha256_lf_text_file
from .phase6_locking import exclusive_file_lock
from .phase6_m2_1_endpoint_selection import PLAN_IDENTITY_FIELDS, TEST_STRATEGIES
from .phase6_m2_1_formal_training_validation import (
    E3_COMPONENT_FILES,
    FAMILY_COMPONENT_FILES,
    FINGERPRINT_FIELDS,
    _component_sha256,
    _canonical_sha256,
)
from .phase6_families import aggregate_oos_evaluation
from .phase6_m2 import m2_model_context
from .phase6_m2_1_pilot import _generate_data, _scenario_identity
from .phase6_m2_development import PeakRSSSampler, compact_failure, validate_run_id
from .phase6_m2_formal_extension import _cross_item_from_evaluation
from .phase6_m2_formal_oos import _evaluate_plan_with_wall_limit
from .phase6_protocol import load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_1_selected_plan_freeze_v1_0"
RUNNER_NAMESPACE = "phase6_m2_1_formal_test_v1_0"
OUTPUT_ROOT = "outputs/phase6_m2_1_formal_test_v1_0"
SUBDIRECTORY = "formal/test"
SOURCE_OUTPUT_ROOT = "outputs/phase6_m2_1_formal_training_validation_v1_0"
SOURCE_SUBDIRECTORY = "training_validation"
FREEZE_PATH = "configs/phase6_m2_1_selected_plan_freeze_v1_0.yaml"
FREEZE_AUDIT_PATH = "docs/handoffs/2026-08-22_phase6_m2_1_selected_plan_freeze_v1_0_audit.json"
SOURCE_AUDIT_PATH = "docs/handoffs/2026-08-22_phase6_m2_1_formal_training_validation_results_v1_0_audit.json"
RUNNER_PATH = "configs/phase6_m2_1_formal_test_runner.yaml"
APPROVAL_PATH = "configs/phase6_m2_1_formal_test_approval.yaml"
FORMAL_BASE_PATH = "configs/phase6_m2_formal_extension.yaml"
ORCHESTRATOR_FILES = (
    "src/phase6_m2_1_formal_test.py",
    "src/run_phase6_m2_1_formal_test.py",
    "src/phase6_m2_1_formal_test_status.py",
    RUNNER_PATH,
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "triplet_position", "test_seed",
    "status", "wall_seconds", "peak_memory_mb", *FINGERPRINT_FIELDS,
    "formal_test_orchestrator_sha256", "result_path", "manifest_path",
    "manifest_sha256", "failure_stage", "updated_at_utc",
)


@dataclass(frozen=True)
class FormalTestCase:
    case_id: str
    triplet_position: int
    training_seed: int
    validation_seed: int
    test_seed: int
    source_run_id: str
    selected_candidate_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload


def _load_freeze(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("M2.1 selected-plan freeze protocol mismatch")
    if payload.get("status") != "frozen_selected_plans_pending_formal_test_runner_review":
        raise ValueError("M2.1 selected-plan freeze lifecycle mismatch")
    scope = payload.get("scientific_scope") or {}
    if scope != {
        "tier_id": "M2F2", "beta": 1.1, "profile_id": "T03",
        "formal_test_scenario_count_per_triplet": 2000,
        "formal_test_triplet_count": 10,
        "strategy_ids": list(TEST_STRATEGIES),
        "formal_test_plan_count": 60,
        "formal_test_exact_recourse_evaluation_count": 120000,
        "test_data_use_for_selection_forbidden": True,
        "selected_plans_are_immutable": True,
        "M2_control_uses_minimum_endpoint_from_same_source_run": True,
        "fixed_strategy_plans_use_same_finalized_training_run_artifacts": True,
        "all_six_strategies_share_one_formal_test_scenario_set_per_triplet": True,
    }:
        raise ValueError("M2.1 formal-test scientific scope changed")
    boundary = payload.get("execution_boundaries") or {}
    if (
        boundary.get("selected_plan_freeze_authorized") is not True
        or boundary.get("formal_test_runner_implemented") is not False
        or boundary.get("formal_test_authorized") is not False
        or boundary.get("formal_extension_authorized") is not False
        or any(int(boundary.get(field, -1)) != 0 for field in (
            "formal_test_scenario_generations", "formal_test_runs",
            "algorithm_performance_runs", "M0_E3_runs",
        ))
    ):
        raise ValueError("M2.1 selected-plan freeze exceeds its authorization")
    return payload


def build_cases(freeze: Mapping[str, Any]) -> tuple[FormalTestCase, ...]:
    rows = freeze.get("selected_plans") or []
    cases = tuple(FormalTestCase(
        case_id=str(row["case_id"]), triplet_position=int(row["triplet_position"]),
        training_seed=int(row["training_seed"]), validation_seed=int(row["validation_seed"]),
        test_seed=int(row["formal_test_seed"]), source_run_id=str(row["source_run_id"]),
        selected_candidate_id=str(row["selected_candidate_id"]),
    ) for row in rows)
    if (
        len(cases) != 10
        or [case.triplet_position for case in cases] != list(range(1, 11))
        or len({case.case_id for case in cases}) != 10
        or len({case.test_seed for case in cases}) != 10
        or any(case.selected_candidate_id not in {"minimum_endpoint", "maximum_endpoint"} for case in cases)
    ):
        raise ValueError("M2.1 formal-test case matrix is not the frozen ten-triplet batch")
    return cases


def formal_test_fingerprints(root: Path, freeze_path: Path, runner_path: Path) -> dict[str, str]:
    freeze = _load_freeze(freeze_path)
    scientific = {key: value for key, value in freeze.items() if key not in {"status", "frozen_on", "execution_boundaries"}}
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": _canonical_sha256(scientific),
        "e3_component_sha256": _component_sha256(root, tuple(E3_COMPONENT_FILES)),
        "family_component_sha256": _component_sha256(root, tuple(FAMILY_COMPONENT_FILES)),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def orchestrator_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in ORCHESTRATOR_FILES:
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def _source_base(root: Path) -> Path:
    return (root / SOURCE_OUTPUT_ROOT / SOURCE_SUBDIRECTORY).resolve()


def _source_registry(root: Path) -> list[dict[str, str]]:
    path = _source_base(root) / "run_registry.csv"
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _validate_source_result(root: Path, case: FormalTestCase, freeze_row: Mapping[str, Any]) -> dict[str, Any]:
    rows = [row for row in _source_registry(root) if row.get("run_id") == case.source_run_id]
    if len(rows) != 1 or rows[0].get("status") != "optimal":
        raise RuntimeError("frozen source run is missing or non-optimal")
    row = rows[0]
    directory = (_source_base(root) / "runs" / case.source_run_id).resolve()
    result_path = Path(row["result_path"]).resolve(); manifest_path = Path(row["manifest_path"]).resolve()
    if result_path != directory / "result.json" or manifest_path != directory / "manifest.json":
        raise RuntimeError("source artifact path leaves reviewed training-validation namespace")
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise RuntimeError("source manifest hash mismatch")
    manifest = _load_json(manifest_path)
    if manifest.get("artifact_state") != "finalized" or sha256_file(result_path) != manifest.get("result_sha256"):
        raise RuntimeError("source result is not finalized")
    result = _load_json(result_path); science = result.get("science") or {}
    if (
        result.get("status") != "optimal" or result.get("case_id") != case.case_id
        or science.get("test_scenario_count") != 0 or science.get("test_results") != {}
        or science.get("validation_selection", {}).get("selected_candidate_id") != case.selected_candidate_id
    ):
        raise RuntimeError("source result identity or phase boundary mismatch")
    selected = science.get("first_stage_plan_artifacts", {}).get(case.selected_candidate_id) or {}
    if {field: selected.get(field) for field in PLAN_IDENTITY_FIELDS} != dict(freeze_row["plan_identity"]):
        raise RuntimeError("selected plan differs from PR #70 frozen identity")
    return result


def _load_plan(root: Path, source: Mapping[str, Any], strategy_id: str) -> dict[str, Any]:
    metadata = source["science"]["first_stage_plan_artifacts"][strategy_id]
    path = Path(metadata["path"]).resolve()
    expected_parent = (_source_base(root) / "runs" / source["run_id"] / "plans").resolve()
    if path.parent != expected_parent or path.name != f"{strategy_id}.json":
        raise RuntimeError("plan artifact path leaves finalized source run")
    if sha256_file(path) != metadata["finalized_plan_artifact_sha256"]:
        raise RuntimeError("plan artifact hash mismatch")
    plan = _load_json(path)
    if plan.get("artifact_state") != "finalized" or plan.get("strategy_id") != strategy_id:
        raise RuntimeError("plan artifact identity mismatch")
    for field in ("regular_purchase_sha256", "reserve_amount", "exact_training_objective", "training_joint_scenario_set_sha256"):
        if plan.get(field) != metadata.get(field):
            raise RuntimeError(f"plan metadata mismatch: {field}")
    return {**plan, "finalized_plan_artifact_sha256": metadata["finalized_plan_artifact_sha256"]}


def validate_preflight(*, root: Path, freeze_path: Path, runner_path: Path, approval_path: Path, authorize: bool) -> dict[str, Any]:
    freeze = _load_freeze(freeze_path)
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8")); approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    if not authorize:
        raise PermissionError("--authorize-formal-test-execution is required")
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("protocol") != PROTOCOL_ID or runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("M2.1 formal-test runner identity mismatch")
    if runner.get("limits") != {"solver_call_seconds": 120, "test_plan_wall_seconds": 7200, "threads": 1}:
        raise RuntimeError("M2.1 formal-test limits changed")
    expected = {
        "approval_id": "phase6_m2_1_formal_test_execution_v1_0",
        "status": "frozen_for_formal_test_execution",
        "scientific_protocol": PROTOCOL_ID, "runner_namespace": RUNNER_NAMESPACE,
        "explicit_cli_authorization_required": True,
        "complete_ten_triplet_primary_batch_required": True,
        "selected_plan_freeze_authorized": True,
        "formal_test_runner_implemented": True, "formal_test_authorized": True,
        "formal_extension_authorized": False, "algorithm_performance_authorized": False,
        "accept_prior_track_authorization": False,
    }
    if any(approval.get(key) != value for key, value in expected.items()):
        raise PermissionError("M2.1 formal-test approval is absent or exceeds scope")
    counts = approval.get("execution_counts_in_this_revision") or {}
    if not counts or any(int(value) != 0 for value in counts.values()):
        raise RuntimeError("formal-test approval revision contains experiment output")
    binding = approval.get("selected_plan_freeze") or {}
    if (
        (root / binding.get("path", "")).resolve() != freeze_path.resolve()
        or binding.get("sha256") != sha256_file(freeze_path)
        or (root / binding.get("audit_path", "")).resolve() != (root / FREEZE_AUDIT_PATH).resolve()
        or binding.get("audit_sha256") != sha256_file(root / FREEZE_AUDIT_PATH)
    ):
        raise RuntimeError("approval is not bound to reviewed PR #70 freeze")
    freeze_audit = _load_json(root / FREEZE_AUDIT_PATH)
    if (
        freeze_audit.get("freeze_artifact", {}).get("sha256") != binding["sha256"]
        or freeze_audit.get("execution_boundaries", {}).get("selected_plan_freeze_authorized") is not True
        or freeze_audit.get("execution_boundaries", {}).get("formal_test_authorized") is not False
    ):
        raise RuntimeError("PR #70 freeze audit boundary mismatch")
    fingerprints = formal_test_fingerprints(root, freeze_path, runner_path)
    if approval.get("approved_fingerprints") != fingerprints:
        raise RuntimeError("M2.1 formal-test fingerprint mismatch")
    orchestrator = orchestrator_sha256(root)
    if approval.get("formal_test_orchestrator_sha256") != orchestrator:
        raise RuntimeError("M2.1 formal-test orchestrator mismatch")
    source_audit = _load_json(root / SOURCE_AUDIT_PATH)
    reviewed = freeze["reviewed_training_validation_evidence"]
    if sha256_file(root / reviewed["pr69_audit_path"]) != reviewed["pr69_audit_sha256"]:
        raise RuntimeError("PR #69 audit hash mismatch")
    source_registry_path = _source_base(root) / "run_registry.csv"
    source_projection_path = _source_base(root) / "projection.json"
    if (
        source_audit.get("global_artifacts", {}).get("formal_training_validation_run_registry_sha256") != reviewed["training_validation_registry_sha256"]
        or source_audit.get("global_artifacts", {}).get("formal_training_validation_projection_sha256") != reviewed["training_validation_projection_sha256"]
        or sha256_file(source_registry_path) != reviewed["training_validation_registry_sha256"]
        or sha256_file(source_projection_path) != reviewed["training_validation_projection_sha256"]
    ):
        raise RuntimeError("PR #69 registry binding mismatch")
    cases = build_cases(freeze); freeze_rows = {row["case_id"]: row for row in freeze["selected_plans"]}
    sources = {case.case_id: _validate_source_result(root, case, freeze_rows[case.case_id]) for case in cases}
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [freeze_path, runner_path, approval_path, root / FREEZE_AUDIT_PATH, root / SOURCE_AUDIT_PATH, root / "requirements-gurobi-lock.txt"]
    required += [root / path for path in ORCHESTRATOR_FILES]
    source = validate_execution_source(root, required_tracked_paths=tuple(sorted(set(required))))
    return {"freeze": freeze, "runner": runner, "approval": approval, "fingerprints": fingerprints, "orchestrator": orchestrator, "cases": cases, "sources": sources, "source": source, "locked_environment": validate_locked_environment(root)}


def execute_formal_test_science(**kwargs: Any) -> dict[str, Any]:
    root: Path = kwargs["project_root"]; matrix = kwargs["matrix"]; matrix_path: Path = kwargs["matrix_path"]
    case: FormalTestCase = kwargs["case"]; source = kwargs["source_result"]; progress = kwargs["progress"]
    limits = kwargs["runner_limits"]; formal = yaml.safe_load((root / FORMAL_BASE_PATH).read_text(encoding="utf-8"))
    progress("test_scenario_generation", {"test_seed": case.test_seed})
    generated, budget = _generate_data(root=root, matrix=matrix, matrix_path=matrix_path, formal=formal, seed=case.test_seed, scenario_count=2000, phase="test")
    identity = _scenario_identity(generated)
    selected = case.selected_candidate_id
    plan_ids = {
        "M2_minimum_endpoint": "minimum_endpoint",
        "M2_1_validation_selected_endpoint": selected,
        "zero_autonomous_reserve": "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10": "fixed_autonomous_reserve_0_10",
        "fixed_autonomous_reserve_0_30": "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50": "fixed_autonomous_reserve_0_50",
    }
    results: dict[str, Any] = {}
    for strategy_id in TEST_STRATEGIES:
        source_id = plan_ids[strategy_id]; plan = _load_plan(root, source, source_id)
        progress(f"test_{strategy_id}", {"source_candidate_id": source_id})
        started = perf_counter()
        with m2_model_context():
            evaluation = _evaluate_plan_with_wall_limit(
                generated.data, plan["regular_purchase"], float(plan["reserve_amount"]),
                solver_call_seconds=float(limits["solver_call_seconds"]),
                plan_wall_seconds=float(limits["test_plan_wall_seconds"]),
            )
        metrics = aggregate_oos_evaluation(
            generated.data, evaluation, reserve=float(plan["reserve_amount"]),
        )
        if (
            metrics.get("plan_oos_status") != "complete_feasible"
            or metrics.get("optimal_scenario_count") != 2000
            or metrics.get("infeasible_scenario_count") != 0
            or metrics.get("solver_failure_count") != 0
        ):
            raise RuntimeError(f"unexpected_infeasible_recourse for {strategy_id}")
        results[strategy_id] = {
            "strategy_id": strategy_id, "source_candidate_id": source_id,
            "source_run_id": source["run_id"], "source_case_id": source["case_id"],
            "plan_identity": {field: plan[field] for field in PLAN_IDENTITY_FIELDS},
            "test_scenario_identity": identity, "test_scenario_count": 2000,
            "wall_seconds": perf_counter() - started, "metrics": metrics,
            "cross_item_allocation": _cross_item_from_evaluation(
                generated.data, evaluation, 1.0e-7,
            ),
        }
    if len({json.dumps(row["test_scenario_identity"], sort_keys=True) for row in results.values()}) != 1:
        raise RuntimeError("formal-test strategies did not share one test scenario set")
    return {
        "tier_id": "M2F2", "beta": 1.1, "profile_id": "T03", "budget": budget,
        "training_seed": case.training_seed, "validation_seed": case.validation_seed,
        "test_seed": case.test_seed, "selected_candidate_id": selected,
        "source_run_id": source["run_id"], "test_scenario_identity": identity,
        "test_scenario_count": 2000, "strategy_results": results,
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def _base(output_root: Path) -> Path:
    return output_root / SUBDIRECTORY


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id); parent = (_base(output_root) / "runs").resolve(); path = (parent / run_id).resolve()
    if path.parent != parent:
        raise ValueError("formal-test run path escapes controlled output root")
    return path


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file(): return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle: return list(csv.DictReader(handle))


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    path = _base(output_root) / "formal_test_run_registry.csv"
    with exclusive_file_lock(_base(output_root) / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows): raise ValueError("formal-test run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS}); atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _validate_artifact(output_root: Path, row: Mapping[str, str], fingerprints: Mapping[str, str], orchestrator: str) -> dict[str, Any]:
    directory = (_base(output_root) / "runs" / row["run_id"]).resolve(); result_path = Path(row["result_path"]).resolve(); manifest_path = Path(row["manifest_path"]).resolve()
    if result_path != directory / "result.json" or manifest_path != directory / "manifest.json": raise ValueError("formal-test artifact path mismatch")
    if sha256_file(manifest_path) != row["manifest_sha256"]: raise ValueError("formal-test manifest hash mismatch")
    manifest = _load_json(manifest_path); result = _load_json(result_path)
    if manifest.get("artifact_state") != "finalized" or sha256_file(result_path) != manifest.get("result_sha256"): raise ValueError("formal-test result is not finalized")
    if result.get("fingerprints") != dict(fingerprints) or result.get("formal_test_orchestrator_sha256") != orchestrator or result.get("status") != row["status"]: raise ValueError("formal-test artifact identity mismatch")
    return result


def _derive_science(science: Mapping[str, Any], case: FormalTestCase, source: Mapping[str, Any]) -> int:
    if any(science.get(field) != value for field, value in {"tier_id":"M2F2", "beta":1.1, "profile_id":"T03", "training_seed":case.training_seed, "validation_seed":case.validation_seed, "test_seed":case.test_seed, "selected_candidate_id":case.selected_candidate_id, "source_run_id":case.source_run_id, "test_scenario_count":2000, "solver":"gurobi_direct", "gurobi_optimizer_version":"13.0.2", "gurobipy_version":"13.0.2", "threads":1}.items()): raise ValueError("formal-test science identity mismatch")
    expected_test_identity = science.get("test_scenario_identity")
    if not isinstance(expected_test_identity, Mapping) or len(expected_test_identity) != 7:
        raise ValueError("formal-test top-level scenario identity missing")
    results = science.get("strategy_results") or {}
    if set(results) != set(TEST_STRATEGIES): raise ValueError("formal-test strategy set mismatch")
    identities = set(); total = 0
    plan_ids = {"M2_minimum_endpoint":"minimum_endpoint", "M2_1_validation_selected_endpoint":case.selected_candidate_id, "zero_autonomous_reserve":"zero_autonomous_reserve", "fixed_autonomous_reserve_0_10":"fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30":"fixed_autonomous_reserve_0_30", "fixed_autonomous_reserve_0_50":"fixed_autonomous_reserve_0_50"}
    for strategy_id, row in results.items():
        expected = source["science"]["first_stage_plan_artifacts"][plan_ids[strategy_id]]
        if row.get("source_candidate_id") != plan_ids[strategy_id] or row.get("source_run_id") != case.source_run_id or row.get("plan_identity") != {field: expected[field] for field in PLAN_IDENTITY_FIELDS}: raise ValueError("formal-test plan-source binding mismatch")
        metrics = row.get("metrics") or {}
        if metrics.get("plan_oos_status") != "complete_feasible" or metrics.get("optimal_scenario_count") != 2000 or metrics.get("infeasible_scenario_count") != 0 or metrics.get("solver_failure_count") != 0: raise ValueError("formal-test recourse evaluation incomplete")
        for field in ("mean_total_cost", "total_cost_cvar95", "service_level"):
            if not math.isfinite(float(metrics.get(field, math.nan))): raise ValueError("formal-test metric missing")
        if not math.isfinite(float(row.get("wall_seconds", math.nan))) or float(row["wall_seconds"]) <= 0: raise ValueError("formal-test strategy runtime invalid")
        if row.get("test_scenario_identity") != expected_test_identity:
            raise ValueError("formal-test strategy scenario identity mismatch")
        identities.add(json.dumps(row.get("test_scenario_identity"), sort_keys=True)); total += int(metrics["optimal_scenario_count"])
    if len(identities) != 1 or total != 12000: raise ValueError("formal-test CRN or evaluation count mismatch")
    return total


def _finalization_failures(base: Path) -> list[str]:
    if not (base / "runs").is_dir(): return []
    return sorted({path.parent.name for name in ("runner_exception.json", "registry_failure.json", "projection_failure.json") for path in (base / "runs").glob(f"*/{name}")})


def update_projection(*, output_root: Path, freeze: Mapping[str, Any], fingerprints: Mapping[str, str], orchestrator: str, sources: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    base = _base(output_root)
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [row for row in _read_registry(base / "formal_test_run_registry.csv") if all(row.get(key) == value for key, value in fingerprints.items()) and row.get("formal_test_orchestrator_sha256") == orchestrator]
        primary: dict[str, dict[str, Any]] = {}; invalid=[]; failed=[]; diagnostics=[]; duplicates=[]; evaluation_count=0
        cases = build_cases(freeze); case_map={case.case_id:case for case in cases}
        for row in rows:
            try:
                result = _validate_artifact(output_root, row, fingerprints, orchestrator)
                if row.get("parent_run_id", "").strip(): diagnostics.append(result["run_id"]); continue
                case_id=result["case_id"]
                if case_id in primary: duplicates.append(case_id); continue
                primary[case_id]=result
                if result["status"] != "optimal": failed.append(result["run_id"]); continue
                evaluation_count += _derive_science(result["science"], case_map[case_id], sources[case_id])
            except Exception: invalid.append(row.get("run_id", ""))
        missing=[case.case_id for case in cases if case.case_id not in primary]; finalization=_finalization_failures(base)
        complete=(len(primary)==10 and evaluation_count==120000 and not any((missing,invalid,failed,diagnostics,duplicates,finalization)))
        payload={"status":"complete" if complete else "incomplete", "fingerprints":dict(fingerprints), "formal_test_orchestrator_sha256":orchestrator, "required_primary_run_count":10, "completed_primary_run_count":len(primary), "required_plan_count":60, "completed_plan_count":sum(len((r.get("science") or {}).get("strategy_results") or {}) for r in primary.values() if r.get("status")=="optimal"), "required_exact_recourse_evaluation_count":120000, "completed_exact_recourse_evaluation_count":evaluation_count, "missing_case_ids":missing, "invalid_primary_run_ids":sorted(invalid), "failed_primary_run_ids":sorted(failed), "duplicate_case_ids":sorted(set(duplicates)), "diagnostic_run_ids":sorted(diagnostics), "finalization_failure_run_ids":finalization, "formal_test_gate_passed":complete, "formal_extension_authorized":False, "algorithm_performance_authorized":False, "next_decision":"permit_formal_test_results_review_only" if complete else "formal_test_incomplete_or_failed", "updated_at_utc":utc_now()}
        atomic_write_json(base / "formal_test_projection.json", payload); return payload


def _terminal(directory: Path, run_id: str, case_id: str, stage: str, status: str, error: BaseException) -> None:
    payload={"run_id":run_id,"case_id":case_id,"status":status,"current_stage":stage,"failure":{"stage":stage,"status":status,"message":f"{type(error).__name__}: {error}"[:1000],"exception_type":type(error).__name__},"updated_at_utc":utc_now()}
    for name in ("runner_exception.json","status_summary.json","heartbeat.json"):
        try: atomic_write_json(directory/name,payload)
        except Exception: pass


def _validate_diagnostic_parent(output_root: Path, case_id: str, parent_run_id: str) -> None:
    validate_run_id(parent_run_id)
    rows = [row for row in _read_registry(_base(output_root) / "formal_test_run_registry.csv") if row.get("run_id") == parent_run_id]
    if len(rows) != 1:
        raise ValueError("diagnostic parent_run_id must identify one formal-test run")
    parent = rows[0]
    if parent.get("parent_run_id", "").strip() or parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must be a primary run of the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must have a terminal failure status")


def run_case(*, root: Path, output_root: Path, freeze: Mapping[str, Any], fingerprints: Mapping[str,str], orchestrator: str, locked_environment: Mapping[str,str], source_identity: Mapping[str,Any], source_result: Mapping[str,Any], sources: Mapping[str,Mapping[str,Any]], case: FormalTestCase, run_id: str, runner_limits: Mapping[str,Any], parent_run_id: str|None=None, science_executor: Callable[...,dict[str,Any]]|None=None) -> dict[str,Any]:
    directory=_run_directory(output_root,run_id); directory.mkdir(parents=True,exist_ok=True)
    with exclusive_file_lock(directory/".run.lock"):
        if any(path.name!=".run.lock" for path in directory.iterdir()): raise ValueError("formal-test run_id is immutable")
        started=perf_counter(); stages=[]; failure=None; science=None; status="running"; sampler=PeakRSSSampler(); sampler.start(); checkpoint=directory/"checkpoint.json"; summary=directory/"status_summary.json"; heartbeat=directory/"heartbeat.json"
        def progress(stage:str,details:Mapping[str,Any])->None:
            stages.append({"stage":stage,**details,"updated_at_utc":utc_now()}); compact={"run_id":run_id,"case_id":case.case_id,"status":"running","current_stage":stage,"completed_stage_count":max(0,len(stages)-1),"failure":None,"updated_at_utc":utc_now()}; atomic_write_json(checkpoint,{**compact,"case":case.as_dict(),"completed_stages":stages[:-1]}); atomic_write_json(summary,compact); atomic_write_json(heartbeat,compact)
        try:
            matrix=load_phase6_matrix(root/"configs/phase6_experiment_matrix.yaml"); science=(science_executor or execute_formal_test_science)(project_root=root,matrix=matrix,matrix_path=root/"configs/phase6_experiment_matrix.yaml",case=case,source_result=source_result,progress=progress,runner_limits=runner_limits); status="optimal"
        except KeyboardInterrupt: status="interrupted"; failure={"stage":stages[-1]["stage"] if stages else "initialization","status":status,"message":"KeyboardInterrupt","exception_type":"KeyboardInterrupt"}
        except Exception as exc: status="timeout" if isinstance(exc,TimeoutError) or "time_limit" in str(exc).lower() else "stage_failure"; failure={"stage":stages[-1]["stage"] if stages else "initialization","status":status,"message":f"{type(exc).__name__}: {exc}"[:1000],"exception_type":type(exc).__name__}
        stage="memory_sampling"
        try:
            peak=sampler.stop(); wall=perf_counter()-started; stage="runtime_context"; runtime=capture_runtime_context(solver_preference=("gurobi",),project_root=root,solver_threads=1); result={"run_id":run_id,"parent_run_id":parent_run_id,"case_id":case.case_id,"case":case.as_dict(),"status":status,"finalized":True,"science":science,"stages":stages,"failure":failure,"wall_seconds":wall,"peak_memory_mb":peak,"fingerprints":dict(fingerprints),"formal_test_orchestrator_sha256":orchestrator,"git_sha":source_identity["commit_sha"],"git_tree_sha":source_identity["tree_sha"],"finished_at_utc":utc_now()}; result_path=directory/"result.json"; manifest_path=directory/"manifest.json"; compact={"run_id":run_id,"case_id":case.case_id,"status":status,"current_stage":failure.get("stage") if failure else None,"completed_stage_count":len(stages),"failure":compact_failure(failure),"updated_at_utc":utc_now()}; stage="artifact_finalization"; atomic_write_json(checkpoint,{**compact,"case":case.as_dict(),"completed_stages":stages}); atomic_write_json(summary,compact); atomic_write_json(heartbeat,compact); atomic_write_json(result_path,result); atomic_write_json(manifest_path,{"artifact_state":"finalized","run_id":run_id,"case_id":case.case_id,"result_sha256":sha256_file(result_path),"checkpoint_sha256":sha256_file(checkpoint),"status_summary_sha256":sha256_file(summary),"heartbeat_sha256":sha256_file(heartbeat),"fingerprints":dict(fingerprints),"formal_test_orchestrator_sha256":orchestrator,"source":dict(source_identity),"locked_environment":dict(locked_environment),"runtime_context":runtime}); row={"run_id":run_id,"parent_run_id":parent_run_id or "","case_id":case.case_id,"triplet_position":case.triplet_position,"test_seed":case.test_seed,"status":status,"wall_seconds":wall,"peak_memory_mb":peak,**dict(fingerprints),"formal_test_orchestrator_sha256":orchestrator,"result_path":str(result_path.resolve()),"manifest_path":str(manifest_path.resolve()),"manifest_sha256":sha256_file(manifest_path),"failure_stage":failure.get("stage") if failure else "","updated_at_utc":result["finished_at_utc"]}; stage="registry_finalization"; _write_registry(output_root,row); stage="projection_finalization"; projection=update_projection(output_root=output_root,freeze=freeze,fingerprints=fingerprints,orchestrator=orchestrator,sources=sources)
        except KeyboardInterrupt as exc: _terminal(directory,run_id,case.case_id,stage,"interrupted",exc); raise
        except Exception as exc: _terminal(directory,run_id,case.case_id,stage,"runner_exception",exc); raise
        if status=="interrupted": raise KeyboardInterrupt
        return {**result,"formal_test_projection":projection}


def run_formal_test(*, root: Path, freeze_path: Path, runner_path: Path, approval_path: Path, authorize: bool, run_id_prefix: str, case_ids: Sequence[str]|None=None, parent_run_id: str|None=None, science_executor: Callable[...,dict[str,Any]]|None=None) -> list[dict[str,Any]]:
    validate_run_id(run_id_prefix); preflight=validate_preflight(root=root,freeze_path=freeze_path,runner_path=runner_path,approval_path=approval_path,authorize=authorize); cases=preflight["cases"]; all_ids={case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None: raise ValueError("primary formal-test execution must run the complete frozen ten-case batch")
    if parent_run_id is not None and (case_ids is None or len(case_ids)!=1): raise ValueError("diagnostic execution requires one case_id and parent_run_id")
    requested=set(case_ids or all_ids)
    if requested-all_ids: raise ValueError("unknown M2.1 formal-test case")
    selected=[case for case in cases if case.case_id in requested]; output_root=root/OUTPUT_ROOT; results=[]; base=_base(output_root)
    with exclusive_file_lock(base/".serial-execution.lock",timeout_seconds=1.0):
        if parent_run_id is None and base.exists() and any(path.name!=".serial-execution.lock" for path in base.iterdir()): raise RuntimeError("primary formal-test batch requires an empty namespace")
        if parent_run_id is not None: _validate_diagnostic_parent(output_root,selected[0].case_id,parent_run_id)
        for case in selected:
            result=run_case(root=root,output_root=output_root,freeze=preflight["freeze"],fingerprints=preflight["fingerprints"],orchestrator=preflight["orchestrator"],locked_environment=preflight["locked_environment"],source_identity=preflight["source"],source_result=preflight["sources"][case.case_id],sources=preflight["sources"],case=case,run_id=f"{run_id_prefix}_{case.case_id}",runner_limits=preflight["runner"]["limits"],parent_run_id=parent_run_id,science_executor=science_executor); results.append(result)
            if result["status"]!="optimal": break
    return results

"""Safe formal training/validation runner for frozen M2.1 endpoint selection."""

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
from .phase6_m2 import M2_E3_COMPONENT_FILES, M2_FAMILY_COMPONENT_FILES
from .phase6_m2_1_endpoint_selection import (
    CANDIDATE_IDS,
    PLAN_IDENTITY_FIELDS,
    build_seed_triplets,
    load_m2_1_config,
)
from .phase6_m2_1_pilot import (
    _derive_triplet,
    _gurobi_release_triplet,
    _read_registry,
    execute_triplet_science,
)
from .phase6_m2_development import (
    DevelopmentStageError,
    PeakRSSSampler,
    compact_failure,
    validate_run_id,
)
from .phase6_m2_formal_extension import _write_plan_artifacts
from .phase6_protocol import load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_1_formal_training_validation_v1_0"
RUNNER_NAMESPACE = PROTOCOL_ID
OUTPUT_ROOT = "outputs/phase6_m2_1_formal_training_validation_v1_0"
READY_STATUS = "frozen_for_formal_training_validation_execution"
CONFIG_PATH = "configs/phase6_m2_1_formal_training_validation.yaml"
RUNNER_CONFIG_PATH = "configs/phase6_m2_1_formal_training_validation_runner.yaml"
APPROVAL_PATH = "configs/phase6_m2_1_formal_training_validation_approval.yaml"
DESIGN_CONFIG_PATH = "configs/phase6_m2_1_endpoint_selection.yaml"
PILOT_AUDIT_PATH = "docs/handoffs/2026-08-22_phase6_m2_1_endpoint_selection_pilot_results_v1_0_audit.json"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256", "e3_component_sha256", "family_component_sha256",
    "runner_config_sha256", "environment_sha256",
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "run_kind", "triplet_position",
    "training_seed", "validation_seed", "test_seed", "status", "wall_seconds",
    "peak_memory_mb", *FINGERPRINT_FIELDS, "result_path", "manifest_path",
    "manifest_sha256", "failure_stage", "updated_at_utc",
)
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2_1_endpoint_selection.py",
    "src/phase6_m2_1_pilot.py",
    "src/phase6_m2_1_formal_training_validation.py",
    "src/run_phase6_m2_1_formal_training_validation.py",
    "src/phase6_m2_1_formal_training_validation_status.py",
    CONFIG_PATH,
    RUNNER_CONFIG_PATH,
    DESIGN_CONFIG_PATH,
    "configs/phase6_m2_formal_extension.yaml",
    "configs/phase6_m2_two_item_confirmation.yaml",
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


@dataclass(frozen=True)
class FormalTrainingValidationCase:
    case_id: str
    run_kind: str
    triplet_position: int
    training_seed: int
    validation_seed: int
    test_seed: int
    includes_test_probe: bool = False

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def load_formal_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("unsupported M2.1 formal training/validation protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE or payload.get("output_root") != OUTPUT_ROOT:
        raise ValueError("M2.1 formal namespace mismatch")
    if payload.get("status") != READY_STATUS:
        raise PermissionError("M2.1 formal training/validation protocol is not frozen")
    if payload.get("frozen_design") != {
        "path": DESIGN_CONFIG_PATH,
        "sha256": "75668fa7a4759d02f4325113aa5abd9ffaa0e1031ea435ef43fc130297700e5c",
        "protocol_id": "phase6_m2_1_endpoint_selection_design_v1_0",
    }:
        raise ValueError("M2.1 frozen design identity changed")
    if payload.get("reviewed_pilot_evidence") != {
        "pr67_merge_commit": "5d40f93f1cf323501941343b34592053a26cccef",
        "audit_path": PILOT_AUDIT_PATH,
        "audit_sha256": "fe63e0e8965503eceb1e0ec99f9e9f9906de322a756e5a3e9fcfbf6f7ddee74b",
        "registry_path": "outputs/phase6_m2_1_endpoint_selection_pilot_v1_0/pilot/pilot_run_registry.csv",
        "registry_sha256": "557ea06ea074a4625d0c89524080c3a38f9cff2d80c62bd9e896bb8c2259f553",
        "projection_path": "outputs/phase6_m2_1_endpoint_selection_pilot_v1_0/pilot/pilot_projection.json",
        "projection_sha256": "42200d72ee02a304383f3d04a0f7749b29db5df1d5994b385dbfa1b256e5f058",
        "required_primary_runs": 3,
        "required_validation_evaluations": 18000,
        "required_test_probe_evaluations": 12000,
        "pilot_compute_gate_passed": True,
    }:
        raise ValueError("M2.1 reviewed pilot evidence declaration changed")
    if payload.get("scientific_base") != {
        "formal_extension_config": "configs/phase6_m2_formal_extension.yaml",
        "formal_extension_config_sha256": "e3eb0ae4c79e9e0859ecc33e4707aecc7ce1a7a1aed3166453f8af2ed2db6792",
        "confirmation_config": "configs/phase6_m2_two_item_confirmation.yaml",
        "confirmation_config_sha256": "d6e28d2171aceacd750a74bcc58a01c3c7383ffdab7ce7fca53e7451fe5f39a5",
        "model": "unchanged_M2_supply_disruption", "tier_id": "M2F2",
        "beta": 1.1, "profile_id": "T03", "training_scenario_count": 100,
        "validation_scenario_count": 2000, "test_scenario_count": 2000,
    }:
        raise ValueError("M2.1 formal scientific base changed")
    matrix = payload.get("formal_matrix") or {}
    expected = {
        "training_seeds": list(range(2026090101, 2026090111)),
        "validation_seeds": list(range(2026090201, 2026090211)),
        "test_seeds": list(range(2026090301, 2026090311)),
        "candidate_ids": list(CANDIDATE_IDS),
    }
    if any(matrix.get(field) != value for field, value in expected.items()):
        raise ValueError("M2.1 formal seed or candidate matrix changed")
    if (
        matrix.get("primary_run_count") != 10
        or matrix.get("validation_candidate_plan_count") != 30
        or matrix.get("validation_exact_recourse_evaluation_count") != 60000
        or matrix.get("test_scenario_generation_count") != 0
        or matrix.get("test_recourse_evaluation_count") != 0
    ):
        raise ValueError("M2.1 formal training/validation counts changed")
    boundary = payload.get("phase_boundary") or {}
    if not all(boundary.get(field) is True for field in (
        "training_and_validation_only",
        "selected_plan_identities_are_finalized_but_not_yet_authorized_for_test",
        "formal_test_data_access_forbidden",
        "all_ten_runs_must_finish_before_plan_freeze_review",
        "validation_outcome_may_not_change_frozen_matrix",
    )):
        raise ValueError("M2.1 phase boundary changed")
    execution = payload.get("execution_boundaries") or {}
    expected_flags = {
        "runner_implemented": True,
        "formal_training_authorized": True,
        "formal_validation_authorized": True,
        "selected_plan_freeze_authorized": False,
        "formal_test_authorized": False,
        "formal_extension_authorized": False,
        "explicit_cli_authorization_required": True,
    }
    if any(execution.get(field) != value for field, value in expected_flags.items()):
        raise ValueError("M2.1 formal authorization boundary changed")
    if any(int(execution.get(field, -1)) != 0 for field in (
        "scenario_generation_count", "gurobi_call_count", "formal_primary_run_count",
        "formal_test_run_count", "algorithm_performance_runs", "M0_E3_runs",
    )):
        raise ValueError("M2.1 formal freeze revision contains scientific execution")
    return payload


def build_formal_cases(config: Mapping[str, Any], design: Mapping[str, Any]) -> tuple[FormalTrainingValidationCase, ...]:
    triplets = build_seed_triplets(design, "formal")
    cases = tuple(FormalTrainingValidationCase(
        case_id=(f"M2_1_formal_triplet{row.position:02d}_train{row.training_seed}_"
                 f"validation{row.validation_seed}_test{row.test_seed}"),
        run_kind="formal_training_validation", triplet_position=row.position,
        training_seed=row.training_seed, validation_seed=row.validation_seed,
        test_seed=row.test_seed,
    ) for row in triplets)
    matrix = config["formal_matrix"]
    if len(cases) != 10 or [case.training_seed for case in cases] != matrix["training_seeds"]:
        raise ValueError("M2.1 formal case construction failed")
    if [case.validation_seed for case in cases] != matrix["validation_seeds"]:
        raise ValueError("M2.1 formal validation pairing changed")
    if [case.test_seed for case in cases] != matrix["test_seeds"]:
        raise ValueError("M2.1 formal test identity pairing changed")
    return cases


def formal_fingerprints(root: Path, config_path: Path, runner_path: Path) -> dict[str, str]:
    config = load_formal_config(config_path)
    design = load_m2_1_config(root / DESIGN_CONFIG_PATH)
    scientific = {
        "formal": {key: value for key, value in config.items() if key not in LIFECYCLE_FIELDS},
        "design": {key: value for key, value in design.items() if key not in LIFECYCLE_FIELDS},
    }
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": _canonical_sha256(scientific),
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def _validate_reviewed_pilot(root: Path, config: Mapping[str, Any], approval: Mapping[str, Any]) -> dict[str, Any]:
    parent = config["reviewed_pilot_evidence"]
    audit_path = root / parent["audit_path"]
    registry_path = root / parent["registry_path"]
    projection_path = root / parent["projection_path"]
    expected = {
        "audit": parent["audit_sha256"], "registry": parent["registry_sha256"],
        "projection": parent["projection_sha256"],
    }
    observed = {
        "audit": sha256_file(audit_path), "registry": sha256_file(registry_path),
        "projection": sha256_file(projection_path),
    }
    if observed != expected:
        raise RuntimeError("reviewed PR #67 pilot evidence hash mismatch")
    if (
        approval.get("reviewed_pilot_audit_sha256") != expected["audit"]
        or approval.get("reviewed_pilot_registry_sha256") != expected["registry"]
        or approval.get("reviewed_pilot_projection_sha256") != expected["projection"]
    ):
        raise RuntimeError("formal approval is not bound to reviewed pilot evidence")
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    projection = json.loads(projection_path.read_text(encoding="utf-8"))
    aggregate = audit.get("aggregate") or {}
    if (
        aggregate.get("completed_primary_run_count") != 3
        or aggregate.get("optimal_primary_run_count") != 3
        or aggregate.get("validation_optimal_recourse_evaluation_count") != 18000
        or aggregate.get("test_probe_optimal_recourse_evaluation_count") != 12000
        or any(aggregate.get(field) for field in (
            "failed_primary_run_ids", "invalid_primary_run_ids", "duplicate_case_ids",
            "diagnostic_run_ids", "finalization_failure_run_ids",
        ))
        or projection.get("pilot_compute_gate_passed") is not True
        or projection.get("formal_extension_authorized") is not False
        or audit.get("fingerprints") != projection.get("fingerprints")
    ):
        raise RuntimeError("reviewed PR #67 pilot gate evidence is incomplete")
    return {"audit": audit, "projection": projection, "hashes": observed}


def validate_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_formal_config(config_path)
    design = load_m2_1_config(root / DESIGN_CONFIG_PATH)
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    if not authorize:
        raise PermissionError("--authorize-formal-training-validation-execution is required")
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("protocol") != PROTOCOL_ID:
        raise RuntimeError("M2.1 formal runner identity mismatch")
    if runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("M2.1 formal output root mismatch")
    if runner.get("limits") != {
        "solver_call_seconds": 120,
        "training_triplet_wall_seconds": 1800,
        "validation_candidate_wall_seconds": 7200,
        "test_plan_wall_seconds": 7200,
        "threads": 1,
    }:
        raise RuntimeError("M2.1 formal solver limits changed")
    if runner.get("execution") != {
        "strictly_serial": True,
        "empty_output_namespace_required_for_primary_batch": True,
        "explicit_cli_authorization_required": True,
        "immutable_run_ids": True,
        "complete_ten_triplet_primary_batch_required": True,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
        "failure_stops_batch": True,
        "formal_test_data_access_forbidden": True,
        "reviewed_pilot_evidence_is_read_only": True,
    }:
        raise RuntimeError("M2.1 formal runner safety protocol changed")
    if runner.get("solver") != {
        "interface": "gurobi_direct", "optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "fallback_allowed": False,
    }:
        raise RuntimeError("M2.1 formal solver identity changed")
    expected_approval = {
        "approval_id": "phase6_m2_1_formal_training_validation_execution_v1_0",
        "status": "approved_for_formal_training_validation_execution",
        "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": RUNNER_NAMESPACE,
        "explicit_cli_authorization_required": True,
        "complete_ten_triplet_primary_batch_required": True,
        "formal_training_authorized": True,
        "formal_validation_authorized": True,
        "selected_plan_freeze_authorized": False,
        "formal_test_authorized": False,
        "formal_extension_authorized": False,
        "accept_M2_authorization": False,
    }
    if any(approval.get(field) != value for field, value in expected_approval.items()):
        raise PermissionError("M2.1 formal approval is not active or exceeds this phase")
    counts = approval.get("execution_counts_in_this_revision") or {}
    if not counts or any(int(value) != 0 for value in counts.values()):
        raise RuntimeError("M2.1 formal approval revision contains experiment output")
    fingerprints = formal_fingerprints(root, config_path, runner_path)
    if approval.get("approved_fingerprints") != fingerprints:
        raise RuntimeError("M2.1 formal fingerprint mismatch")
    reviewed = _validate_reviewed_pilot(root, config, approval)
    design_parent = config["frozen_design"]
    if sha256_file(root / design_parent["path"]) != design_parent["sha256"]:
        raise RuntimeError("M2.1 frozen design bytes changed")
    for path_field, hash_field in (
        ("formal_extension_config", "formal_extension_config_sha256"),
        ("confirmation_config", "confirmation_config_sha256"),
    ):
        if sha256_file(root / config["scientific_base"][path_field]) != config["scientific_base"][hash_field]:
            raise RuntimeError(f"M2.1 scientific base hash mismatch: {path_field}")
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [config_path, runner_path, approval_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=tuple(required))
    locked = validate_locked_environment(root)
    runtime = capture_runtime_context(solver_preference=("gurobi",), project_root=root, solver_threads=1)
    solver = runtime.get("solver") or {}
    if (
        solver.get("selected") != "gurobi_direct"
        or _gurobi_release_triplet(solver.get("version")) != (13, 0, 2)
        or int(solver.get("threads", -1)) != 1
    ):
        raise RuntimeError("M2.1 formal runtime is not Gurobi 13.0.2 via gurobi_direct Threads=1")
    return {
        "config": config, "design": design, "runner": runner,
        "approval": approval, "fingerprints": fingerprints,
        "reviewed_pilot": reviewed, "source": source, "locked_environment": locked,
        "preflight_runtime": runtime,
    }


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (output_root / "training_validation/runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("M2.1 formal run path escapes controlled output root")
    return path


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = output_root / "training_validation"
    path = base / "run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("M2.1 formal run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _validate_artifact(output_root: Path, row: Mapping[str, str]) -> dict[str, Any]:
    run_id = row["run_id"]; validate_run_id(run_id)
    directory = (output_root / "training_validation/runs" / run_id).resolve()
    expected_result = directory / "result.json"; expected_manifest = directory / "manifest.json"
    result_path = Path(row["result_path"]).resolve(); manifest_path = Path(row["manifest_path"]).resolve()
    if result_path != expected_result or manifest_path != expected_manifest:
        raise ValueError("M2.1 formal registry artifact path mismatch")
    if not result_path.is_file() or not manifest_path.is_file():
        raise ValueError("M2.1 formal artifact is missing")
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("M2.1 formal manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if (
        manifest.get("artifact_state") != "finalized"
        or manifest.get("run_id") != run_id
        or manifest.get("case_id") != row.get("case_id")
        or manifest.get("result_sha256") != sha256_file(result_path)
        or manifest.get("fingerprints") != {field: row[field] for field in FINGERPRINT_FIELDS}
        or result.get("run_id") != run_id
        or result.get("case_id") != row.get("case_id")
        or result.get("finalized") is not True
        or result.get("status") != row.get("status")
        or result.get("fingerprints") != {field: row[field] for field in FINGERPRINT_FIELDS}
    ):
        raise ValueError("M2.1 formal artifact identity mismatch")
    return result


def _validate_plan(output_root: Path, run_id: str, identity: Mapping[str, Any]) -> None:
    strategy = str(identity.get("strategy_id", "")); validate_run_id(strategy)
    expected = (output_root / "training_validation/runs" / run_id / "plans" / f"{strategy}.json").resolve()
    path = Path(str(identity.get("path", ""))).resolve()
    if path != expected or not path.is_file() or sha256_file(path) != identity.get("finalized_plan_artifact_sha256"):
        raise ValueError("M2.1 formal plan artifact mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("artifact_state") != "finalized"
        or payload.get("source_run_id") != run_id
        or payload.get("strategy_id") != strategy
        or payload.get("regular_purchase_sha256") != identity.get("regular_purchase_sha256")
        or payload.get("training_joint_scenario_set_sha256") != identity.get("training_joint_scenario_set_sha256")
        or not math.isclose(float(payload.get("reserve_amount", math.nan)), float(identity.get("reserve_amount", math.nan)), abs_tol=1e-9)
        or not math.isclose(float(payload.get("exact_training_objective", math.nan)), float(identity.get("exact_training_objective", math.nan)), abs_tol=1e-8)
    ):
        raise ValueError("M2.1 formal plan is not finalized")


def _failure_ids(base: Path) -> list[str]:
    runs = base / "runs"
    return sorted(path.parent.name for path in runs.glob("*/runner_exception.json")) if runs.is_dir() else []


def update_projection(
    *, output_root: Path, config: Mapping[str, Any], design: Mapping[str, Any],
    fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    base = output_root / "training_validation"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [
            row for row in _read_registry(base / "run_registry.csv")
            if all(row.get(field) == value for field, value in fingerprints.items())
        ]
        verified: dict[str, dict[str, Any]] = {}; failed: list[str] = []
        invalid: list[str] = []; diagnostics: list[str] = []; duplicates: list[str] = []
        for row in rows:
            try:
                result = _validate_artifact(output_root, row)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"]); continue
                if result["case_id"] in verified:
                    duplicates.append(result["case_id"]); continue
                if result["status"] != "optimal":
                    failed.append(result["run_id"]); continue
                for identity in (result["science"].get("first_stage_plan_artifacts") or {}).values():
                    _validate_plan(output_root, result["run_id"], identity)
                verified[result["case_id"]] = result
            except Exception:
                invalid.append(row.get("run_id", ""))
        cases = build_formal_cases(config, design)
        derived: list[dict[str, Any] | None] = []
        selected_plan_mapping: dict[str, dict[str, Any]] = {}
        for case in cases:
            result = verified.get(case.case_id)
            try:
                row = _derive_triplet(result["science"], result["case"]) if result else None
                derived.append(row)
                if row:
                    selected = row["selected_candidate_id"]
                    identity = result["science"]["first_stage_plan_artifacts"][selected]
                    selected_plan_mapping[case.case_id] = {
                        field: identity[field] for field in PLAN_IDENTITY_FIELDS
                    }
            except Exception:
                invalid.append(result.get("run_id", "") if result else "")
                derived.append(None)
        finalization = _failure_ids(base)
        complete = bool(
            len(verified) == 10 and all(derived) and not failed and not invalid
            and not diagnostics and not duplicates and not finalization
        )
        validation_plans = sum(row["validation_plan_count"] for row in derived if row)
        validation_evaluations = sum(row["validation_recourse_evaluation_count"] for row in derived if row)
        gate = bool(complete and validation_plans == 30 and validation_evaluations == 60000)
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints),
            "required_primary_run_count": 10,
            "verified_primary_run_count": sum(row is not None for row in derived),
            "validation_candidate_plan_count": validation_plans,
            "validation_exact_recourse_evaluation_count": validation_evaluations,
            "selected_candidate_ids": [row["selected_candidate_id"] for row in derived if row],
            "selected_plan_identity_mapping_sha256": _canonical_sha256(selected_plan_mapping),
            "failed_primary_run_ids": sorted(failed),
            "invalid_primary_run_ids": sorted(set(invalid)),
            "duplicate_case_ids": sorted(set(duplicates)),
            "diagnostic_run_ids": sorted(diagnostics),
            "finalization_failure_run_ids": finalization,
            "formal_training_validation_gate_passed": gate,
            "selected_plan_freeze_authorized": False,
            "formal_test_authorized": False,
            "formal_extension_authorized": False,
            "next_decision": "permit_separate_selected_plan_freeze_review_PR_only" if gate else "training_validation_incomplete_or_failed",
            "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "projection.json", payload)
        return payload


def _terminal_diagnostic(directory: Path, *, run_id: str, case_id: str, stage: str, status: str, error: BaseException) -> None:
    payload = {
        "run_id": run_id, "case_id": case_id, "status": status, "stage": stage,
        "failure": compact_failure({"stage": stage, "status": status, "message": f"{type(error).__name__}: {error}"[:1000]}),
        "updated_at_utc": utc_now(),
    }
    for name in ("runner_exception.json", "status_summary.json", "heartbeat.json"):
        try:
            atomic_write_json(directory / name, payload)
        except Exception:
            pass


def run_case(
    *, root: Path, output_root: Path, matrix_path: Path,
    config: Mapping[str, Any], design: Mapping[str, Any], runner: Mapping[str, Any],
    fingerprints: Mapping[str, str], locked_environment: Mapping[str, str],
    source: Mapping[str, Any], case: FormalTrainingValidationCase, run_id: str,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("M2.1 formal run_id is immutable")
        started = perf_counter(); stages: list[dict[str, Any]] = []
        failure = None; science = None; status = "running"
        sampler = PeakRSSSampler(); sampler.start()
        checkpoint = directory / "checkpoint.json"; status_path = directory / "status_summary.json"
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
                "failure": None,
            }
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)

        try:
            matrix = load_phase6_matrix(matrix_path)
            science = (science_executor or execute_triplet_science)(
                project_root=root, matrix=matrix, matrix_path=matrix_path,
                pilot_config=config, design_config=design, runner_config=runner,
                case=case, progress=progress,
            )
            if science.get("test_results") or science.get("test_scenario_count") != 0:
                raise RuntimeError("formal test data was accessed during training/validation phase")
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": "KeyboardInterrupt", "exception_type": "KeyboardInterrupt"}
        except Exception as exc:
            solver_status = str(exc.solver_status).lower() if isinstance(exc, DevelopmentStageError) else ""
            timeout = isinstance(exc, TimeoutError) or solver_status in {"time_limit", "master_time_limit"} or solver_status.endswith("_time_limit")
            status = "timeout" if timeout else "stage_failure"
            failure = {
                "stage": getattr(exc, "stage", stages[-1]["stage"] if stages else "initialization"),
                "status": status, "solver_status": solver_status or None,
                "message": f"{type(exc).__name__}: {exc}"[:1000], "exception_type": type(exc).__name__,
            }

        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "plan_artifact_finalization"
            if science is not None and "_plan_payloads" in science:
                payloads = science.pop("_plan_payloads")
                identities = _write_plan_artifacts(directory=directory, run_id=run_id, case_id=case.case_id, payloads=payloads)
                science["first_stage_plan_artifacts"] = identities
                minimum = identities["minimum_endpoint"]
                science["minimum_endpoint_M2_control_identity"] = {field: minimum[field] for field in PLAN_IDENTITY_FIELDS}
                for candidate_id, row in science["validation_results"].items():
                    row["source_plan_identity"] = {field: identities[candidate_id][field] for field in PLAN_IDENTITY_FIELDS}
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(solver_preference=("gurobi",), project_root=root, solver_threads=1)
            result = {
                "run_id": run_id, "parent_run_id": parent_run_id, "case_id": case.case_id,
                "case": case.as_dict(), "status": status, "finalized": True, "science": science,
                "stages": stages, "failure": failure, "wall_seconds": wall, "peak_memory_mb": peak,
                "fingerprints": dict(fingerprints), "git_sha": source["commit_sha"],
                "git_tree_sha": source["tree_sha"], "finished_at_utc": utc_now(),
            }
            result_path = directory / "result.json"; manifest_path = directory / "manifest.json"
            compact = {
                "run_id": run_id, "case_id": case.case_id, "status": status,
                "current_stage": failure.get("stage") if failure else None,
                "completed_stage_count": len(stages), "failure": compact_failure(failure),
                "updated_at_utc": utc_now(),
            }
            finalization_stage = "artifact_finalization"
            atomic_write_json(checkpoint, {"run_id": run_id, "case": case.as_dict(), "status": status, "completed_stages": stages, "failure": compact_failure(failure), "updated_at_utc": utc_now()})
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {
                "artifact_state": "finalized", "run_id": run_id, "case_id": case.case_id,
                "result_sha256": sha256_file(result_path), "checkpoint_sha256": sha256_file(checkpoint),
                "status_summary_sha256": sha256_file(status_path), "heartbeat_sha256": sha256_file(heartbeat),
                "fingerprints": dict(fingerprints), "source": dict(source),
                "locked_environment": dict(locked_environment), "runtime_context": runtime,
            })
            finalization_stage = "registry_finalization"
            _write_registry(output_root, {
                "run_id": run_id, "parent_run_id": parent_run_id or "", "case_id": case.case_id,
                "run_kind": case.run_kind, "triplet_position": case.triplet_position,
                "training_seed": case.training_seed, "validation_seed": case.validation_seed,
                "test_seed": case.test_seed, "status": status, "wall_seconds": wall,
                "peak_memory_mb": peak, **dict(fingerprints), "result_path": str(result_path.resolve()),
                "manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256_file(manifest_path),
                "failure_stage": failure.get("stage") if failure else "", "updated_at_utc": result["finished_at_utc"],
            })
            finalization_stage = "projection_finalization"
            projection = update_projection(output_root=output_root, config=config, design=design, fingerprints=fingerprints)
        except KeyboardInterrupt as exc:
            _terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="interrupted", error=exc); raise
        except Exception as exc:
            _terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="runner_exception", error=exc); raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "projection": projection}


def _validate_diagnostic_parent(output_root: Path, *, case_id: str, parent_run_id: str) -> None:
    rows = _read_registry(output_root / "training_validation/run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1 or matches[0].get("case_id") != case_id:
        raise ValueError("M2.1 formal diagnostic parent mismatch")
    if matches[0].get("parent_run_id", "").strip() or matches[0].get("status") not in {"stage_failure", "timeout", "interrupted", "runner_exception"}:
        raise ValueError("M2.1 formal diagnostic parent is not a failed primary")


def run_formal_training_validation(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_preflight(root=root, config_path=config_path, runner_path=runner_path, approval_path=approval_path, authorize=authorize)
    cases = build_formal_cases(preflight["config"], preflight["design"])
    all_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary execution must run all ten frozen formal triplets")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("diagnostic execution requires one case_id and parent_run_id")
    requested = set(case_ids or all_ids)
    if requested - all_ids:
        raise ValueError("unknown M2.1 formal case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OUTPUT_ROOT; results: list[dict[str, Any]] = []
    with exclusive_file_lock(output_root / "training_validation/.serial-execution.lock", timeout_seconds=1.0):
        existing = output_root / "training_validation"
        if parent_run_id is None and existing.exists() and any(path.name != ".serial-execution.lock" for path in existing.iterdir()):
            raise RuntimeError("primary M2.1 formal batch requires an empty output namespace")
        if parent_run_id is not None:
            _validate_diagnostic_parent(output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id)
        for case in selected:
            result = run_case(
                root=root, output_root=output_root,
                matrix_path=root / "configs/phase6_experiment_matrix.yaml",
                config=preflight["config"], design=preflight["design"], runner=preflight["runner"],
                fingerprints=preflight["fingerprints"], locked_environment=preflight["locked_environment"],
                source=preflight["source"], case=case,
                run_id=f"{run_id_prefix}_{case.case_id}", parent_run_id=parent_run_id,
                science_executor=science_executor,
            )
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

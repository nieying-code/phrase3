"""Audited executor for the frozen 50-run M2 formal mechanism batch.

This orchestration layer is deliberately separate from the pilot-tested science
kernel.  It never updates the pilot registry/projection and never authorizes or
executes the formal out-of-sample batch.
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

from .phase6_environment import validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes
from .phase6_locking import exclusive_file_lock
from .phase6_m2_development import PeakRSSSampler, compact_failure, validate_run_id
from .phase6_m2_formal_extension import (
    FAMILY_COMPONENT_FILES,
    FINGERPRINT_FIELDS,
    OUTPUT_ROOT,
    PROTOCOL_ID,
    RUNNER_NAMESPACE,
    _derive_mechanism,
    _write_plan_artifacts,
    execute_mechanism_science,
    formal_extension_fingerprints,
    load_formal_extension_config,
)
from .phase6_protocol import load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


FORMAL_NAMESPACE = "phase6_m2_formal_mechanism_v1_1"
FORMAL_STATUS = "frozen_for_formal_mechanism_execution"
FORMAL_SUBDIRECTORY = "formal/mechanism"
FORMAL_RUNNER_PATH = "configs/phase6_m2_formal_mechanism_runner.yaml"
FORMAL_APPROVAL_PATH = "configs/phase6_m2_formal_mechanism_approval.yaml"
PILOT_AUDIT_PATH = "docs/handoffs/2026-08-14_phase6_m2_formal_extension_pilot_v1_1_audit.json"
FORMAL_ORCHESTRATOR_FILES = (
    "src/phase6_m2_formal_mechanism.py",
    "src/run_phase6_m2_formal_mechanism.py",
    "src/phase6_m2_formal_mechanism_status.py",
    FORMAL_RUNNER_PATH,
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "run_kind", "tier_id", "seed",
    "beta", "profile_id", "status", "wall_seconds", "peak_memory_mb",
    *FINGERPRINT_FIELDS, "formal_orchestrator_sha256", "result_path",
    "manifest_path", "manifest_sha256", "failure_stage", "updated_at_utc",
)


@dataclass(frozen=True)
class FormalMechanismCase:
    case_id: str
    run_kind: str
    tier_id: str
    seed: int
    beta: float
    profile_id: str
    test_seed: None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_formal_mechanism_cases(config: Mapping[str, Any]) -> tuple[FormalMechanismCase, ...]:
    seeds = tuple(int(value) for value in config["seed_protocol"]["formal_training_seeds"])
    if seeds != tuple(range(2026081401, 2026081411)):
        raise ValueError("formal training seed identity mismatch")
    cases = tuple(
        FormalMechanismCase(
            case_id=(f"M2F2_formal_seed{seed}_beta{beta:.2f}_profile{profile}").replace(".", "p"),
            run_kind="mechanism",
            tier_id="M2F2",
            seed=seed,
            beta=beta,
            profile_id=profile,
        )
        for seed in seeds
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    )
    if len(cases) != 50 or len({case.case_id for case in cases}) != 50:
        raise ValueError("formal mechanism Cartesian product is not exactly 50 cases")
    return cases


def formal_orchestrator_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for relative in FORMAL_ORCHESTRATOR_FILES:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected object in {path}")
    return payload


def _validate_reviewed_pilot_evidence(
    *, evidence: Mapping[str, Any], audit: Mapping[str, Any],
    projection: Mapping[str, Any], actual_fingerprints: Mapping[str, str],
) -> None:
    """Bind local pilot artifacts to the compact evidence reviewed in PR #56."""
    global_artifacts = audit.get("global_artifacts") or {}
    if (
        evidence.get("projection_sha256")
        != global_artifacts.get("pilot_projection_sha256")
        or evidence.get("registry_sha256")
        != global_artifacts.get("pilot_run_registry_sha256")
    ):
        raise RuntimeError("pilot evidence is not bound to the reviewed PR #56 audit")

    reviewed_projection = audit.get("projection") or {}
    aggregate = audit.get("aggregate") or {}
    if audit.get("fingerprints") != dict(actual_fingerprints):
        raise RuntimeError("pilot audit fingerprint mismatch")
    if (
        reviewed_projection.get("fingerprints") != dict(actual_fingerprints)
        or projection.get("fingerprints") != dict(actual_fingerprints)
    ):
        raise RuntimeError("pilot projection fingerprint mismatch")

    exact_counts = {
        "required_mechanism_run_count": 15,
        "verified_mechanism_run_count": 15,
        "required_OOS_probe_run_count": 1,
        "verified_OOS_probe_run_count": 1,
    }
    for field, expected in exact_counts.items():
        if reviewed_projection.get(field) != expected or projection.get(field) != expected:
            raise RuntimeError(f"reviewed pilot coverage mismatch: {field}")
    if aggregate.get("mechanism_run_count") != 15 or aggregate.get("oos_probe_run_count") != 1:
        raise RuntimeError("reviewed pilot aggregate count mismatch")

    empty_failure_fields = (
        "invalid_primary_run_ids",
        "diagnostic_run_ids",
        "duplicate_case_ids",
        "failed_primary_run_ids",
        "finalization_failure_run_ids",
    )
    for field in empty_failure_fields:
        if reviewed_projection.get(field) != [] or projection.get(field) != []:
            raise RuntimeError(f"reviewed pilot exception set is not empty: {field}")
    if (
        reviewed_projection.get("pilot_compute_gate_passed") is not True
        or projection.get("pilot_compute_gate_passed") is not True
        or reviewed_projection.get("formal_extension_authorized") is not False
        or projection.get("formal_extension_authorized") is not False
        or reviewed_projection.get("next_decision") != evidence.get("required_decision")
        or projection.get("next_decision") != evidence.get("required_decision")
    ):
        raise RuntimeError("reviewed pilot gate identity mismatch")


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _formal_base(output_root: Path) -> Path:
    return output_root / FORMAL_SUBDIRECTORY


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (_formal_base(output_root) / "runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("formal run path escapes controlled output root")
    return path


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = _formal_base(output_root)
    path = base / "formal_mechanism_run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("formal mechanism run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _controlled_artifact_paths(output_root: Path, row: Mapping[str, str]) -> tuple[Path, Path]:
    run_id = str(row["run_id"]); validate_run_id(run_id)
    directory = (_formal_base(output_root) / "runs" / run_id).resolve()
    result = Path(row["result_path"]).resolve()
    manifest = Path(row["manifest_path"]).resolve()
    if result != directory / "result.json" or manifest != directory / "manifest.json":
        raise ValueError("registry artifact path leaves formal mechanism namespace")
    return result, manifest


def _validate_artifact(
    output_root: Path, row: Mapping[str, str], *, fingerprints: Mapping[str, str],
    orchestrator_sha256: str,
) -> dict[str, Any]:
    result_path, manifest_path = _controlled_artifact_paths(output_root, row)
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("formal manifest hash mismatch")
    manifest = _load_json(manifest_path)
    result = _load_json(result_path)
    if (
        manifest.get("artifact_state") != "finalized"
        or sha256_file(result_path) != manifest.get("result_sha256")
        or result.get("finalized") is not True
        or result.get("run_id") != row["run_id"]
        or result.get("case_id") != row["case_id"]
        or result.get("status") != row["status"]
        or result.get("fingerprints") != dict(fingerprints)
        or manifest.get("fingerprints") != dict(fingerprints)
        or result.get("formal_orchestrator_sha256") != orchestrator_sha256
        or manifest.get("formal_orchestrator_sha256") != orchestrator_sha256
    ):
        raise ValueError("formal result identity or protected hash mismatch")
    case = result.get("case") or {}
    expected = {
        "run_kind": "mechanism", "tier_id": row["tier_id"],
        "seed": int(row["seed"]), "beta": float(row["beta"]),
        "profile_id": row["profile_id"], "test_seed": None,
    }
    if any(case.get(key) != value for key, value in expected.items()):
        raise ValueError("formal result case identity mismatches registry")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("formal result parent identity mismatches registry")
    wall = float(row["wall_seconds"])
    if not math.isfinite(wall) or not math.isclose(wall, float(result["wall_seconds"]), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("formal result wall time mismatches registry")
    directory = result_path.parent
    for name, field in (("checkpoint.json", "checkpoint_sha256"), ("status_summary.json", "status_summary_sha256"), ("heartbeat.json", "heartbeat_sha256")):
        if manifest.get(field) != sha256_file(directory / name):
            raise ValueError(f"formal terminal artifact mismatch: {name}")
    return result


def _validate_formal_plan_artifact(
    *, output_root: Path, source_run_id: str, identity: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = str(identity["strategy_id"])
    validate_run_id(source_run_id)
    expected = (
        _formal_base(output_root) / "runs" / source_run_id / "plans" / f"{strategy_id}.json"
    ).resolve()
    path = Path(identity["path"]).resolve()
    if path != expected or not path.is_file():
        raise ValueError("formal plan artifact path leaves its source run")
    if sha256_file(path) != identity["finalized_plan_artifact_sha256"]:
        raise ValueError("formal plan artifact hash mismatch")
    payload = _load_json(path)
    if (
        payload.get("artifact_state") != "finalized"
        or payload.get("source_run_id") != source_run_id
        or payload.get("strategy_id") != strategy_id
        or payload.get("regular_purchase_sha256") != identity["regular_purchase_sha256"]
        or not math.isclose(float(payload.get("reserve_amount", math.nan)), float(identity.get("reserve_amount", math.nan)), abs_tol=1e-9)
        or not math.isclose(float(payload.get("exact_training_objective", math.nan)), float(identity.get("exact_training_objective", math.nan)), abs_tol=1e-8)
        or payload.get("training_joint_scenario_set_sha256") != identity.get("training_joint_scenario_set_sha256")
    ):
        raise ValueError("formal plan artifact identity mismatch")
    return payload


def validate_formal_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_formal_extension_config(config_path)
    if config.get("status") != "frozen_for_pilot_execution":
        raise RuntimeError("pilot-reviewed scientific baseline status changed")
    if not authorize:
        raise PermissionError("--authorize-formal-mechanism-execution is required")
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    required_runner = {
        "namespace": FORMAL_NAMESPACE,
        "protocol": PROTOCOL_ID,
        "output_root": OUTPUT_ROOT,
        "formal_subdirectory": FORMAL_SUBDIRECTORY,
    }
    if any(runner.get(key) != value for key, value in required_runner.items()):
        raise RuntimeError("formal mechanism runner identity mismatch")
    execution = runner.get("execution") or {}
    required_execution = {
        "strictly_serial": True,
        "formal_mechanism_execution_requires_explicit_authorization": True,
        "immutable_run_ids": True,
        "full_primary_batch_required": True,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
        "failed_primary_permanently_blocks_batch_gate": True,
        "pilot_projection_is_read_only": True,
        "formal_OOS_authorized": False,
        "mechanism_primary_run_count": 50,
    }
    if any(execution.get(key) != value for key, value in required_execution.items()):
        raise RuntimeError("formal mechanism safety metadata mismatch")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    expected_approval = {
        "approval_id": "phase6_m2_formal_mechanism_execution_v1_1",
        "status": FORMAL_STATUS,
        "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": FORMAL_NAMESPACE,
        "mechanism_case_count": 50,
        "explicit_cli_authorization_required": True,
        "formal_mechanism_authorized": True,
        "formal_OOS_authorized": False,
        "accept_prior_track_authorization": False,
    }
    if any(approval.get(key) != value for key, value in expected_approval.items()):
        raise RuntimeError("formal mechanism approval metadata mismatch")
    actual = formal_extension_fingerprints(
        root, config_path, root / "configs/phase6_m2_formal_extension_runner.yaml",
    )
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("formal mechanism scientific/pilot fingerprint mismatch")
    orchestrator = formal_orchestrator_sha256(root)
    if approval.get("formal_orchestrator_sha256") != orchestrator:
        raise RuntimeError("formal mechanism orchestrator fingerprint mismatch")
    evidence = approval.get("pilot_evidence") or {}
    audit_path = (root / evidence.get("audit_path", "")).resolve()
    projection_path = (root / evidence.get("projection_path", "")).resolve()
    registry_path = (root / evidence.get("registry_path", "")).resolve()
    expected_audit = (root / PILOT_AUDIT_PATH).resolve()
    expected_projection = (root / OUTPUT_ROOT / "pilot/pilot_projection.json").resolve()
    expected_registry = (root / OUTPUT_ROOT / "pilot/pilot_run_registry.csv").resolve()
    if (audit_path, projection_path, registry_path) != (expected_audit, expected_projection, expected_registry):
        raise RuntimeError("pilot evidence path leaves approved namespace")
    for path, key in ((audit_path, "audit_sha256"), (projection_path, "projection_sha256"), (registry_path, "registry_sha256")):
        if not path.is_file() or sha256_file(path) != evidence.get(key):
            raise RuntimeError(f"pilot evidence hash mismatch: {key}")
    audit = _load_json(audit_path); projection = _load_json(projection_path)
    _validate_reviewed_pilot_evidence(
        evidence=evidence,
        audit=audit,
        projection=projection,
        actual_fingerprints=actual,
    )
    if (
        audit.get("stop_boundary", {}).get("pilot_compute_gate_passed") is not True
        or audit.get("stop_boundary", {}).get("formal_extension_authorized") is not False
        or projection.get("pilot_compute_gate_passed") is not True
        or projection.get("formal_extension_authorized") is not False
        or projection.get("next_decision") != evidence.get("required_decision")
        or projection.get("fingerprints") != actual
    ):
        raise RuntimeError("pilot evidence does not authorize a separate formal freeze")
    build_formal_mechanism_cases(config)
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [root / path for path in FORMAL_ORCHESTRATOR_FILES]
    required += [config_path, runner_path, approval_path, audit_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    return {
        "config": config, "runner": runner, "approval": approval,
        "fingerprints": actual, "formal_orchestrator_sha256": orchestrator,
        "pilot_audit": audit, "pilot_projection": projection,
        "locked_environment": validate_locked_environment(root), "source": source,
    }


def _write_terminal_diagnostic(directory: Path, *, run_id: str, case_id: str, stage: str, status: str, error: BaseException) -> None:
    failure = {"stage": stage, "status": status, "message": f"{type(error).__name__}: {error}"[:1000], "exception_type": type(error).__name__}
    payload = {"run_id": run_id, "case_id": case_id, "status": status, "current_stage": stage, "completed_stage_count": 0, "failure": failure, "updated_at_utc": utc_now()}
    for name in ("runner_exception.json", "status_summary.json", "heartbeat.json"):
        try:
            atomic_write_json(directory / name, payload)
        except Exception:
            pass


def _validate_diagnostic_parent(output_root: Path, *, case_id: str, parent_run_id: str) -> None:
    validate_run_id(parent_run_id)
    rows = _read_registry(_formal_base(output_root) / "formal_mechanism_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1:
        raise ValueError("diagnostic parent_run_id must identify one existing formal run")
    parent = matches[0]
    if parent.get("parent_run_id", "").strip() or parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must be a primary run of the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must have a failure terminal state")


def _finalization_failure_ids(base: Path) -> list[str]:
    if not (base / "runs").is_dir():
        return []
    return sorted({path.parent.name for name in ("runner_exception.json", "registry_failure.json", "progress_failure.json") for path in (base / "runs").glob(f"*/{name}")})


def update_formal_progress(
    *, output_root: Path, config: Mapping[str, Any], fingerprints: Mapping[str, str],
    orchestrator_sha256: str,
) -> dict[str, Any]:
    base = _formal_base(output_root)
    with exclusive_file_lock(base / ".progress.lock"):
        rows = _read_registry(base / "formal_mechanism_run_registry.csv")
        matching = [row for row in rows if all(row.get(key) == value for key, value in fingerprints.items()) and row.get("formal_orchestrator_sha256") == orchestrator_sha256]
        primary: dict[str, dict[str, Any]] = {}; invalid=[]; failed=[]; diagnostics=[]; duplicates=[]
        for row in matching:
            try:
                result = _validate_artifact(output_root, row, fingerprints=fingerprints, orchestrator_sha256=orchestrator_sha256)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"]); continue
                if result["case_id"] in primary:
                    duplicates.append(result["case_id"]); continue
                if result["status"] != "optimal":
                    failed.append(result["run_id"]); primary[result["case_id"]] = result; continue
                for identity in (result["science"].get("first_stage_plan_artifacts") or {}).values():
                    _validate_formal_plan_artifact(output_root=output_root, source_run_id=result["run_id"], identity=identity)
                _derive_mechanism(result["science"], result["case"])
                primary[result["case_id"]] = result
            except Exception:
                invalid.append(row.get("run_id", ""))
        cases = build_formal_mechanism_cases(config)
        missing = [case.case_id for case in cases if case.case_id not in primary]
        crn=[]
        for seed in config["seed_protocol"]["formal_training_seeds"]:
            group=[primary.get(case.case_id) for case in cases if case.seed == seed]
            fields=("latent_draw_sha256","demand_sha256","emergency_price_sha256","emergency_supply_sha256","scenario_order_sha256")
            anchor=(group[0] or {}).get("science",{}).get("scenario_component_set_sha256",{}) if group else {}
            verified=len(group)==5 and all(
                row is not None
                and row.get("status") == "optimal"
                and all(
                    (row.get("science") or {}).get("scenario_component_set_sha256", {}).get(field)
                    == anchor.get(field)
                    and anchor.get(field) is not None
                    for field in fields
                )
                for row in group
            )
            crn.append({"seed":seed,"verified":verified})
        finalization=_finalization_failure_ids(base)
        complete=bool(len(primary)==50 and not missing and not invalid and not failed and not diagnostics and not duplicates and not finalization and all(row["verified"] for row in crn))
        payload={
            "status":"complete" if complete else "incomplete",
            "fingerprints":dict(fingerprints), "formal_orchestrator_sha256":orchestrator_sha256,
            "required_primary_run_count":50, "completed_primary_run_count":len(primary),
            "missing_case_ids":missing, "invalid_primary_run_ids":sorted(invalid),
            "failed_primary_run_ids":sorted(failed), "duplicate_case_ids":sorted(set(duplicates)),
            "diagnostic_run_ids":sorted(diagnostics), "finalization_failure_run_ids":finalization,
            "common_random_number_checks":crn, "common_random_numbers_verified":all(row["verified"] for row in crn),
            "formal_mechanism_gate_passed":complete,
            "next_decision":"permit_mechanism_results_review_only" if complete else "formal_mechanism_incomplete_or_failed",
            "formal_OOS_authorized":False, "formal_extension_complete":False,
            "updated_at_utc":utc_now(),
        }
        atomic_write_json(base / "formal_mechanism_progress.json", payload)
        return payload


def run_formal_case(
    *, root: Path, output_root: Path, matrix_path: Path, config: Mapping[str, Any],
    fingerprints: Mapping[str, str], orchestrator_sha256: str,
    locked_environment: Mapping[str, str], source: Mapping[str, Any],
    case: FormalMechanismCase, run_id: str, parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    directory=_run_directory(output_root,run_id); directory.mkdir(parents=True,exist_ok=True)
    with exclusive_file_lock(directory/".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("formal mechanism run_id is immutable")
        started=perf_counter(); stages=[]; failure=None; science=None; status="running"
        sampler=PeakRSSSampler(); sampler.start(); checkpoint=directory/"checkpoint.json"; status_path=directory/"status_summary.json"; heartbeat=directory/"heartbeat.json"
        def progress(stage: str, details: Mapping[str, Any]) -> None:
            stages.append({"stage":stage,**details,"updated_at_utc":utc_now()})
            atomic_write_json(checkpoint,{"run_id":run_id,"case":case.as_dict(),"status":"running","completed_stages":stages[:-1],"current_stage":stage,"updated_at_utc":utc_now()})
            compact={"run_id":run_id,"case_id":case.case_id,"status":"running","current_stage":stage,"completed_stage_count":max(0,len(stages)-1),"failure":None}
            atomic_write_json(status_path,compact); atomic_write_json(heartbeat,compact)
        try:
            matrix=load_phase6_matrix(matrix_path)
            science=(science_executor or execute_mechanism_science)(project_root=root,output_root=output_root,fingerprints=fingerprints,matrix=matrix,matrix_path=matrix_path,config=config,case=case,progress=progress)
            status="optimal"
        except KeyboardInterrupt:
            status="interrupted"; failure={"stage":stages[-1]["stage"] if stages else "initialization","status":status,"message":"KeyboardInterrupt","exception_type":"KeyboardInterrupt"}
        except Exception as exc:
            status="timeout" if isinstance(exc,TimeoutError) or "time_limit" in str(exc) else "stage_failure"
            failure={"stage":stages[-1]["stage"] if stages else "initialization","status":status,"message":f"{type(exc).__name__}: {exc}"[:1000],"exception_type":type(exc).__name__}
        finalization_stage="memory_sampling"
        try:
            peak=sampler.stop(); wall=perf_counter()-started
            finalization_stage="plan_artifact_finalization"
            if science is not None and "_plan_payloads" in science:
                science["first_stage_plan_artifacts"]=_write_plan_artifacts(directory=directory,run_id=run_id,case_id=case.case_id,payloads=science.pop("_plan_payloads"))
            finalization_stage="runtime_context"; runtime=capture_runtime_context(solver_preference=("gurobi",),project_root=root,solver_threads=1)
            result={"run_id":run_id,"parent_run_id":parent_run_id,"case_id":case.case_id,"case":case.as_dict(),"status":status,"finalized":True,"science":science,"stages":stages,"failure":failure,"wall_seconds":wall,"peak_memory_mb":peak,"fingerprints":dict(fingerprints),"formal_orchestrator_sha256":orchestrator_sha256,"git_sha":source["commit_sha"],"git_tree_sha":source["tree_sha"],"finished_at_utc":utc_now()}
            result_path=directory/"result.json"; manifest_path=directory/"manifest.json"
            compact={"run_id":run_id,"case_id":case.case_id,"status":status,"current_stage":failure.get("stage") if failure else None,"completed_stage_count":len(stages),"failure":compact_failure(failure),"updated_at_utc":utc_now()}
            finalization_stage="artifact_finalization"
            atomic_write_json(checkpoint,{"run_id":run_id,"case":case.as_dict(),"status":status,"completed_stages":stages,"failure":compact_failure(failure),"updated_at_utc":utc_now()})
            atomic_write_json(status_path,compact); atomic_write_json(heartbeat,compact); atomic_write_json(result_path,result)
            atomic_write_json(manifest_path,{"artifact_state":"finalized","run_id":run_id,"case_id":case.case_id,"result_sha256":sha256_file(result_path),"checkpoint_sha256":sha256_file(checkpoint),"status_summary_sha256":sha256_file(status_path),"heartbeat_sha256":sha256_file(heartbeat),"fingerprints":dict(fingerprints),"formal_orchestrator_sha256":orchestrator_sha256,"source":dict(source),"locked_environment":dict(locked_environment),"runtime_context":runtime})
            row={"run_id":run_id,"parent_run_id":parent_run_id or "","case_id":case.case_id,"run_kind":"mechanism","tier_id":case.tier_id,"seed":case.seed,"beta":case.beta,"profile_id":case.profile_id,"status":status,"wall_seconds":wall,"peak_memory_mb":peak,**dict(fingerprints),"formal_orchestrator_sha256":orchestrator_sha256,"result_path":str(result_path.resolve()),"manifest_path":str(manifest_path.resolve()),"manifest_sha256":sha256_file(manifest_path),"failure_stage":failure.get("stage") if failure else "","updated_at_utc":result["finished_at_utc"]}
            finalization_stage="registry_finalization"; _write_registry(output_root,row)
            finalization_stage="progress_finalization"; formal_progress=update_formal_progress(output_root=output_root,config=config,fingerprints=fingerprints,orchestrator_sha256=orchestrator_sha256)
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(directory,run_id=run_id,case_id=case.case_id,stage=finalization_stage,status="interrupted",error=exc); raise
        except Exception as exc:
            _write_terminal_diagnostic(directory,run_id=run_id,case_id=case.case_id,stage=finalization_stage,status="runner_exception",error=exc); raise
        if status=="interrupted": raise KeyboardInterrupt
        return {**result,"formal_progress":formal_progress}


def run_formal_mechanism(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight=validate_formal_preflight(root=root,config_path=config_path,runner_path=runner_path,approval_path=approval_path,authorize=authorize)
    cases=build_formal_mechanism_cases(preflight["config"]); all_ids={case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary formal execution must run the complete frozen 50-case batch")
    if parent_run_id is not None and (case_ids is None or len(case_ids)!=1):
        raise ValueError("formal diagnostic execution requires one case_id and parent_run_id")
    requested=set(case_ids or all_ids)
    if requested-all_ids: raise ValueError("unknown formal mechanism case")
    selected=[case for case in cases if case.case_id in requested]
    output_root=root/OUTPUT_ROOT; results=[]; base=_formal_base(output_root)
    with exclusive_file_lock(base/".serial-execution.lock",timeout_seconds=1.0):
        if parent_run_id is None and base.exists() and any(path.name!=".serial-execution.lock" for path in base.iterdir()):
            raise RuntimeError("primary formal mechanism batch requires an empty formal namespace")
        if parent_run_id is not None:
            _validate_diagnostic_parent(output_root,case_id=selected[0].case_id,parent_run_id=parent_run_id)
        for case in selected:
            result=run_formal_case(root=root,output_root=output_root,matrix_path=root/"configs/phase6_experiment_matrix.yaml",config=preflight["config"],fingerprints=preflight["fingerprints"],orchestrator_sha256=preflight["formal_orchestrator_sha256"],locked_environment=preflight["locked_environment"],source=preflight["source"],case=case,run_id=f"{run_id_prefix}_{case.case_id}",parent_run_id=parent_run_id,science_executor=science_executor)
            results.append(result)
            if result["status"]!="optimal": break
    return results

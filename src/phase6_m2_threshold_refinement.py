"""Safe executor and projection for the frozen M2 threshold refinement."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import yaml

from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes, sha256_lf_text_file
from .phase6_locking import exclusive_file_lock
from .phase6_m2 import M2_E3_COMPONENT_FILES, M2_FAMILY_COMPONENT_FILES
from .phase6_m2_development import (
    DevelopmentCase,
    PeakRSSSampler,
    compact_failure,
    execute_development_case_science,
    validate_run_id,
)
from .phase6_protocol import load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_threshold_refinement_v1_0"
RUNNER_NAMESPACE = PROTOCOL_ID
OUTPUT_ROOT = "outputs/phase6_m2_threshold_refinement_v1_0"
READY_STATUS = "frozen_for_development_execution"
APPROVAL_PATH = "configs/phase6_m2_threshold_refinement_approval.yaml"
PARENT_AUDIT_PATH = "docs/handoffs/2026-08-13_phase6_m2_development_grid_audit.json"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256", "e3_component_sha256",
    "family_component_sha256", "runner_config_sha256", "environment_sha256",
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "tier_id", "seed", "beta",
    "profile_id", "status", "wall_seconds", "peak_memory_mb",
    *FINGERPRINT_FIELDS, "result_path", "manifest_path", "manifest_sha256",
    "failure_stage", "updated_at_utc",
)
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2_threshold_refinement.py",
    "src/run_phase6_m2_threshold_refinement.py",
    "src/phase6_m2_threshold_refinement_status.py",
    "configs/phase6_m2_threshold_refinement.yaml",
    "configs/phase6_m2_threshold_refinement_runner.yaml",
    PARENT_AUDIT_PATH,
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


@dataclass(frozen=True)
class RefinementCase:
    case_id: str
    tier_id: str
    seed: int
    beta: float
    profile_id: str

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_refinement_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("unsupported M2 threshold-refinement protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE or payload.get("output_root") != OUTPUT_ROOT:
        raise ValueError("threshold-refinement identity mismatch")
    raw = payload.get("refinement_preregistration") or {}
    if tuple(raw.get("seeds", ())) != (2026081201, 2026081202, 2026081203):
        raise ValueError("unexpected threshold-refinement seeds")
    if tuple(float(v) for v in raw.get("beta", ())) != (0.9, 1.1, 1.3):
        raise ValueError("unexpected threshold-refinement beta values")
    profiles = raw.get("profiles") or {}
    if tuple(profiles) != ("T03", "T04", "T05"):
        raise ValueError("threshold-refinement profiles must be T03/T04/T05")
    expected_scales = {"T03": 0.3, "T04": 0.4, "T05": 0.5}
    for profile, scale in expected_scales.items():
        item = profiles[profile]
        if item != {"enabled": True, "loss_scale": scale, "recovery_fraction": 0.0}:
            raise ValueError(f"unexpected frozen profile: {profile}")
    if int(raw.get("configuration_count", -1)) != 27:
        raise ValueError("threshold-refinement matrix must contain 27 cases")
    return payload


def build_refinement_cases(config: Mapping[str, Any]) -> tuple[RefinementCase, ...]:
    raw = config["refinement_preregistration"]
    cases = tuple(
        RefinementCase(
            case_id=f"V1_seed{seed}_beta{float(beta):.2f}_profile{profile}".replace(".", "p"),
            tier_id="V1", seed=int(seed), beta=float(beta), profile_id=str(profile),
        )
        for seed in raw["seeds"] for beta in raw["beta"] for profile in raw["profiles"]
    )
    if len(cases) != 27 or len({case.case_id for case in cases}) != 27:
        raise ValueError("threshold-refinement cases are not a unique 27-case Cartesian product")
    return cases


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def refinement_fingerprints(root: Path, config_path: Path, runner_path: Path) -> dict[str, str]:
    config = load_refinement_config(config_path)
    scientific = {k: v for k, v in config.items() if k not in LIFECYCLE_FIELDS}
    scientific_hash = hashlib.sha256(json.dumps(
        scientific, sort_keys=True, ensure_ascii=False, separators=(",", ":")
    ).encode()).hexdigest()
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": scientific_hash,
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def load_parent_anchors(root: Path, expected_sha256: str) -> dict[tuple[int, float, str], dict[str, Any]]:
    path = root / PARENT_AUDIT_PATH
    if sha256_file(path) != expected_sha256:
        raise ValueError("approved parent M2 audit hash mismatch")
    audit = json.loads(path.read_text(encoding="utf-8"))
    if audit.get("status") != "development_grid_complete_pending_review":
        raise ValueError("parent M2 audit status is not approved evidence")
    anchors: dict[tuple[int, float, str], dict[str, Any]] = {}
    for row in audit.get("runs", []):
        profile = str(row.get("profile_id"))
        if profile not in {"C1", "C2"}:
            continue
        identity = (int(row["seed"]), float(row["beta"]), profile)
        if identity in anchors or row.get("status") != "optimal":
            raise ValueError("parent anchor evidence is duplicate or non-optimal")
        anchors[identity] = row
    if len(anchors) != 18:
        raise ValueError("parent anchor evidence must contain C1/C2 x 3 seeds x 3 betas")
    for beta in (0.9, 1.1, 1.3):
        c1 = [anchors[(seed, beta, "C1")] for seed in (2026081201, 2026081202, 2026081203)]
        c2 = [anchors[(seed, beta, "C2")] for seed in (2026081201, 2026081202, 2026081203)]
        if sum(bool(row["substantive_activation"]) for row in c1) != 0:
            raise ValueError("C1 parent activation must be 0/3 for every beta")
        if sum(bool(row["substantive_activation"]) for row in c2) != 3:
            raise ValueError("C2 parent activation must be 3/3 for every beta")
    return anchors


def _science_config(root: Path, refinement: Mapping[str, Any]) -> dict[str, Any]:
    parent_path = root / "configs/phase6_m2_supply_disruption.yaml"
    parent = yaml.safe_load(parent_path.read_text(encoding="utf-8"))
    combined = deepcopy(parent)
    combined["disruption_profiles"] = {
        key: dict(value)
        for key, value in refinement["refinement_preregistration"]["profiles"].items()
    }
    return combined


def execute_refinement_science(**kwargs: Any) -> dict[str, Any]:
    root = kwargs["project_root"]
    refinement = kwargs["config"]
    case: RefinementCase = kwargs["case"]
    return execute_development_case_science(
        project_root=root, matrix=kwargs["matrix"], matrix_path=kwargs["matrix_path"],
        config=_science_config(root, refinement),
        case=DevelopmentCase(**case.as_dict()), progress=kwargs["progress"],
    )


def validate_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_refinement_config(config_path)
    if config.get("status") != READY_STATUS:
        raise RuntimeError("threshold-refinement matrix is not frozen")
    if not authorize:
        raise PermissionError("--authorize-development-execution is required")
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("threshold-refinement runner identity mismatch")
    execution = runner.get("execution") or {}
    if execution.get("development_execution_requires_explicit_authorization") is not True:
        raise RuntimeError("explicit authorization guard is disabled")
    if execution.get("parent_anchors_read_only") is not True:
        raise RuntimeError("parent anchors must be read-only")
    if execution.get("parent_registry_or_projection_import_forbidden") is not True:
        raise RuntimeError("parent registry/projection import must be forbidden")
    if execution.get("adaptive_profile_insertion_forbidden") is not True:
        raise RuntimeError("adaptive profile insertion must be forbidden")
    if execution.get("formal_extension_authorized") is not False:
        raise RuntimeError("threshold-refinement isolation guard mismatch")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    expected_metadata = {
        "approval_id": "phase6_m2_threshold_refinement_development_execution_v1_0",
        "status": READY_STATUS, "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": RUNNER_NAMESPACE, "matrix_case_count": 27,
        "explicit_cli_authorization_required": True,
        "formal_extension_authorized": False, "parent_anchors_are_read_only": True,
    }
    if any(approval.get(k) != v for k, v in expected_metadata.items()):
        raise RuntimeError("threshold-refinement approval metadata mismatch")
    actual = refinement_fingerprints(root, config_path, runner_path)
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("threshold-refinement fingerprint mismatch")
    anchors = load_parent_anchors(root, config["parent_protocol"]["results_audit_sha256"])
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [config_path, runner_path, approval_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    return {
        "config": config, "runner": runner, "approval": approval,
        "fingerprints": actual, "anchors": anchors,
        "locked_environment": validate_locked_environment(root), "source": source,
    }


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_registry(root: Path, row: Mapping[str, Any]) -> None:
    path = root / "development/refinement_run_registry.csv"
    with exclusive_file_lock(root / "development/.registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("threshold-refinement run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _validate_artifact(row: Mapping[str, str]) -> dict[str, Any]:
    result_path, manifest_path = Path(row["result_path"]), Path(row["manifest_path"])
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if sha256_file(result_path) != manifest["result_sha256"]:
        raise ValueError("result hash mismatch")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if result.get("finalized") is not True or result.get("run_id") != row["run_id"]:
        raise ValueError("result is not finalized or identity mismatches")
    if result.get("fingerprints") != {key: row[key] for key in FINGERPRINT_FIELDS}:
        raise ValueError("result fingerprints mismatch registry")
    return result


def _derive_science(science: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    budget = float(science["budget"])
    ratio = max(0.0, float(science["R_min_opt"]) - float(science["R_min_feas"])) / budget
    tolerance = float(science["objective_tolerance"])
    optimum = float(science["complete_extensive_objective"])
    for endpoint in ("minimum", "maximum"):
        if science[f"{endpoint}_endpoint_status"] != "optimal":
            raise ValueError("reserve-face endpoint is not optimal")
        if abs(float(science[f"{endpoint}_endpoint_exact_objective"]) - optimum) > tolerance + 1e-8:
            raise ValueError("reserve-face endpoint exceeds tolerance")
    counts = science["endpoint_failure_counts"]
    if any(int(value) for endpoint in counts.values() for value in endpoint.values()):
        raise ValueError("endpoint exact recourse is incomplete")
    policies = science["fixed_reserve_policies"]
    if [float(item["rho"]) for item in policies] != [0.0, 0.1, 0.3, 0.5]:
        raise ValueError("fixed reserve policies are incomplete")
    if any(item["status"] != "optimal" or item["regular_purchase_reoptimized"] is not True for item in policies):
        raise ValueError("fixed reserve policy evidence is incomplete")
    interval = config["reserve_identification"]["moderate_autonomous_reserve_ratio_interval"]
    return {
        "ratio": ratio,
        "numerical": ratio > float(config["reserve_identification"]["numerical_activation_ratio_strictly_greater_than"]),
        "substantive": ratio >= float(config["reserve_identification"]["substantive_activation_ratio_greater_than_or_equal_to"]),
        "moderate": float(interval[0]) <= ratio <= float(interval[1]),
        "components": dict(science["scenario_component_set_sha256"]),
    }


def update_projection(
    *, output_root: Path, config: Mapping[str, Any], fingerprints: Mapping[str, str],
    anchors: Mapping[tuple[int, float, str], Mapping[str, Any]],
) -> dict[str, Any]:
    base = output_root / "development"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [row for row in _read_registry(base / "refinement_run_registry.csv")
                if all(row.get(key) == value for key, value in fingerprints.items())]
        verified: dict[tuple[int, float, str], tuple[dict[str, Any], dict[str, Any]]] = {}
        invalid, invalid_diagnostics, diagnostics, duplicates = [], [], [], []
        failed_primary_run_ids: list[str] = []
        for row in rows:
            try:
                result = _validate_artifact(row)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"])
                    continue
                case = result["case"]
                identity = (int(case["seed"]), float(case["beta"]), str(case["profile_id"]))
                if identity in verified:
                    duplicates.append(result["case_id"])
                    continue
                if result["status"] == "optimal":
                    verified[identity] = (result, _derive_science(result["science"], config))
                else:
                    failed_primary_run_ids.append(row["run_id"])
            except Exception:
                (invalid_diagnostics if row.get("parent_run_id") else invalid).append(row["run_id"])

        combinations, new_by_beta_profile = [], {}
        for beta in (0.9, 1.1, 1.3):
            for profile in ("T03", "T04", "T05"):
                entries = [verified.get((seed, beta, profile)) for seed in (2026081201, 2026081202, 2026081203)]
                derived = [entry[1] for entry in entries if entry]
                complete = len(derived) == 3
                substantive = sum(item["substantive"] for item in derived)
                moderate = sum(item["moderate"] for item in derived)
                activation = complete and substantive >= 2
                item = {
                    "beta": beta, "profile_id": profile,
                    "completed_seed_count": len(derived),
                    "substantive_activation_seed_count": substantive,
                    "moderate_seed_count": moderate,
                    "raw_combination_activation_gate_passed": activation,
                    "combination_activation_gate_passed": activation,
                    "moderate_gate_passed": activation and moderate >= 2,
                    "run_ids": [entry[0]["run_id"] for entry in entries if entry],
                }
                combinations.append(item); new_by_beta_profile[(beta, profile)] = item

        beta_assessments = []
        profile_order = ("C1", "T03", "T04", "T05", "C2")
        scale = {"C1": 0.2, "T03": 0.3, "T04": 0.4, "T05": 0.5, "C2": 0.6}
        for beta in (0.9, 1.1, 1.3):
            activation = []
            crn_checks = []
            for profile in profile_order:
                if profile in {"C1", "C2"}:
                    rows_for_profile = [anchors[(seed, beta, profile)] for seed in (2026081201, 2026081202, 2026081203)]
                    active = sum(bool(row["substantive_activation"]) for row in rows_for_profile) >= 2
                else:
                    active = new_by_beta_profile[(beta, profile)]["combination_activation_gate_passed"]
                activation.append(active)
            for seed in (2026081201, 2026081202, 2026081203):
                anchor = anchors[(seed, beta, "C1")]["scenario_component_set_sha256"]
                for profile in ("T03", "T04", "T05"):
                    entry = verified.get((seed, beta, profile))
                    fields = ("latent_draw_sha256", "demand_sha256", "emergency_price_sha256", "emergency_supply_sha256")
                    match = bool(entry) and all(entry[1]["components"][field] == anchor[field] for field in fields)
                    crn_checks.append({"seed": seed, "profile_id": profile, "verified": match})
            crn_verified = all(item["verified"] for item in crn_checks)
            first = next((i for i, value in enumerate(activation) if value), None)
            nonmonotone = first is not None and any(not value for value in activation[first:])
            bracket = None if first in (None, 0) or nonmonotone or not crn_verified else {
                "lower_profile": profile_order[first - 1], "upper_profile": profile_order[first],
                "lower_loss_scale": scale[profile_order[first - 1]], "upper_loss_scale": scale[profile_order[first]],
            }
            status = (
                "common_random_number_mismatch" if not crn_verified else
                "nonmonotone_activation_pattern" if nonmonotone else
                "monotone_activation" if first is not None else "no_activation"
            )
            eligible = []
            for profile in ("T03", "T04", "T05"):
                item = new_by_beta_profile[(beta, profile)]
                item["beta_common_random_numbers_verified"] = crn_verified
                item["beta_activation_monotone"] = not nonmonotone
                item["combination_activation_gate_passed"] = bool(
                    item["raw_combination_activation_gate_passed"] and crn_verified
                )
                item["moderate_gate_passed"] = bool(
                    item["combination_activation_gate_passed"]
                    and item["moderate_seed_count"] >= 2
                )
                item["eligible_moderate_combination"] = bool(
                    item["moderate_gate_passed"] and not nonmonotone
                )
                if item["eligible_moderate_combination"]:
                    eligible.append({"beta": beta, "profile_id": profile})
            beta_assessments.append({
                "beta": beta, "profile_order": list(profile_order), "activation_sequence": activation,
                "status": status,
                "threshold_bracket": bracket, "common_random_number_checks": crn_checks,
                "common_random_numbers_verified": crn_verified,
                "eligible_moderate_combinations": eligible,
                "multi_item_candidate_allowed": bool(eligible),
            })

        finalization_failure_run_ids = sorted(
            path.parent.name
            for name in ("runner_exception.json", "registry_failure.json", "projection_failure.json")
            for path in (base / "runs").glob(f"*/{name}")
        ) if (base / "runs").is_dir() else []
        crn_verified = all(item["common_random_numbers_verified"] for item in beta_assessments)
        complete = (
            len(verified) == 27 and not invalid and not duplicates and not diagnostics
            and not invalid_diagnostics and not failed_primary_run_ids
            and not finalization_failure_run_ids and crn_verified
        )
        any_activation = any(item["combination_activation_gate_passed"] for item in combinations)
        eligible_moderate = [
            {"beta": item["beta"], "profile_id": item["profile_id"]}
            for item in combinations if item["eligible_moderate_combination"]
        ]
        any_moderate = bool(eligible_moderate)
        any_nonmonotone = any(item["status"] == "nonmonotone_activation_pattern" for item in beta_assessments)
        if not crn_verified:
            decision = "common_random_number_mismatch"
        elif complete and not any_activation:
            decision = "no_intermediate_activation_and_stop"
        elif complete and any_activation and not any_moderate:
            decision = "boundary_jump_and_stop"
        elif complete and any_moderate:
            decision = "permit_separate_multi_item_design_PR_only"
        else:
            decision = "incomplete_or_invalid"
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints), "required_primary_run_count": 27,
            "verified_primary_run_count": len(verified), "invalid_primary_run_ids": sorted(invalid),
            "invalid_diagnostic_run_ids": sorted(invalid_diagnostics),
            "diagnostic_run_ids": sorted(diagnostics), "duplicate_case_ids": sorted(set(duplicates)),
            "failed_primary_run_ids": sorted(failed_primary_run_ids),
            "finalization_failure_run_ids": finalization_failure_run_ids,
            "combinations": combinations,
            "beta_assessments": beta_assessments, "any_nonmonotone_beta": any_nonmonotone,
            "common_random_numbers_verified": crn_verified,
            "eligible_moderate_combinations": eligible_moderate,
            "overall_decision": decision,
            "development_activation_gate_passed": complete and any_activation,
            "moderate_activation_gate_passed": complete and any_moderate,
            "formal_extension_authorized": False, "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "threshold_refinement_projection.json", payload)
        return payload


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (output_root / "development/runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("run path escapes controlled root")
    return path


def _write_terminal_diagnostic(
    directory: Path, *, run_id: str, case_id: str, stage: str,
    status: str, error: BaseException,
) -> None:
    """Best-effort bounded evidence for failures outside the scientific solve."""
    failure = {
        "stage": stage, "status": status,
        "message": f"{type(error).__name__}: {error}"[:1000],
        "exception_type": type(error).__name__,
    }
    payload = {
        "run_id": run_id, "case_id": case_id, "status": status,
        "current_stage": stage, "completed_stage_count": 0,
        "failure": failure, "updated_at_utc": utc_now(),
    }
    for path, value in (
        (directory / "runner_exception.json", payload),
        (directory / "status_summary.json", payload),
        (directory / "heartbeat.json", payload),
    ):
        try:
            atomic_write_json(path, value)
        except Exception:
            pass


def _validate_diagnostic_parent(
    output_root: Path, *, case_id: str, parent_run_id: str,
) -> None:
    validate_run_id(parent_run_id)
    rows = _read_registry(output_root / "development/refinement_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1:
        raise ValueError("diagnostic parent_run_id must identify one existing run")
    parent = matches[0]
    if parent.get("parent_run_id", "").strip():
        raise ValueError("diagnostic parent must be a primary run")
    if parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must belong to the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must be a failed, timed-out, or interrupted run")


def run_case(
    *, root: Path, output_root: Path, matrix_path: Path, config: Mapping[str, Any],
    fingerprints: Mapping[str, str], anchors: Mapping[tuple[int, float, str], Mapping[str, Any]],
    locked_environment: Mapping[str, str], source: Mapping[str, Any], case: RefinementCase,
    run_id: str, parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_refinement_science,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    if parent_run_id is not None:
        validate_run_id(parent_run_id)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("threshold-refinement run_id is immutable")
        started = perf_counter(); stages = []; failure = None; science = None; status = "running"
        sampler = PeakRSSSampler(); sampler.start()
        checkpoint = directory / "checkpoint.json"
        status_path, heartbeat = directory / "status_summary.json", directory / "heartbeat.json"
        def progress(stage: str, details: Mapping[str, Any]) -> None:
            stages.append({"stage": stage, **details, "updated_at_utc": utc_now()})
            atomic_write_json(checkpoint, {"run_id":run_id,"case":case.as_dict(),"status":"running","completed_stages":stages[:-1],"current_stage":stage,"updated_at_utc":utc_now()})
            compact = {"run_id": run_id, "case_id": case.case_id, "status": "running", "current_stage": stage, "completed_stage_count": max(0, len(stages)-1), "failure": None}
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
        try:
            matrix = load_phase6_matrix(matrix_path)
            science = science_executor(project_root=root, matrix=matrix, matrix_path=matrix_path, config=config, case=case, progress=progress)
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"; failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": "KeyboardInterrupt", "exception_type": "KeyboardInterrupt"}
        except Exception as exc:
            status = "timeout" if isinstance(exc, TimeoutError) or "time_limit" in str(exc) else "stage_failure"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": f"{type(exc).__name__}: {exc}"[:1000], "exception_type": type(exc).__name__}
        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(solver_preference=("gurobi",), project_root=root, solver_threads=1)
            result = {"run_id": run_id, "parent_run_id": parent_run_id, "case_id": case.case_id, "case": case.as_dict(), "status": status, "finalized": True, "science": science, "stages": stages, "failure": failure, "wall_seconds": wall, "peak_memory_mb": peak, "fingerprints": dict(fingerprints), "git_sha": source["commit_sha"], "git_tree_sha": source["tree_sha"], "finished_at_utc": utc_now()}
            result_path, manifest_path = directory / "result.json", directory / "manifest.json"
            compact = {"run_id": run_id, "case_id": case.case_id, "status": status, "current_stage": failure.get("stage") if failure else None, "completed_stage_count": len(stages), "failure": compact_failure(failure), "updated_at_utc": utc_now()}
            finalization_stage = "artifact_finalization"
            atomic_write_json(checkpoint, {"run_id":run_id,"case":case.as_dict(),"status":status,"completed_stages":stages,"failure":compact_failure(failure),"updated_at_utc":utc_now()})
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)
            atomic_write_json(result_path, result)
            atomic_write_json(manifest_path, {"artifact_state": "finalized", "run_id": run_id, "case_id": case.case_id, "result_sha256": sha256_file(result_path), "checkpoint_sha256":sha256_file(checkpoint), "status_summary_sha256": sha256_file(status_path), "heartbeat_sha256": sha256_file(heartbeat), "fingerprints": dict(fingerprints), "source": dict(source), "locked_environment": dict(locked_environment), "runtime_context": runtime})
            row = {"run_id": run_id, "parent_run_id": parent_run_id or "", "case_id": case.case_id, "tier_id": case.tier_id, "seed": case.seed, "beta": case.beta, "profile_id": case.profile_id, "status": status, "wall_seconds": wall, "peak_memory_mb": peak, **dict(fingerprints), "result_path": str(result_path.resolve()), "manifest_path": str(manifest_path.resolve()), "manifest_sha256": sha256_file(manifest_path), "failure_stage": failure.get("stage") if failure else "", "updated_at_utc": result["finished_at_utc"]}
            finalization_stage = "registry_finalization"
            _write_registry(output_root, row)
            finalization_stage = "projection_finalization"
            projection = update_projection(output_root=output_root, config=config, fingerprints=fingerprints, anchors=anchors)
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="interrupted", error=exc)
            raise
        except Exception as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="runner_exception", error=exc)
            raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "projection": projection}


def run_matrix(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] = execute_refinement_science,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_preflight(root=root, config_path=config_path, runner_path=runner_path, approval_path=approval_path, authorize=authorize)
    cases = build_refinement_cases(preflight["config"])
    all_case_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary execution must run the complete frozen 27-case matrix")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("diagnostic execution requires exactly one case_id and parent_run_id")
    requested = set(case_ids or all_case_ids)
    if requested - all_case_ids:
        raise ValueError("unknown threshold-refinement case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OUTPUT_ROOT; results = []
    with exclusive_file_lock(output_root / "development/.serial-execution.lock", timeout_seconds=1.0):
        existing = output_root / "development"
        if parent_run_id is None and existing.exists() and any(path.name != ".serial-execution.lock" for path in existing.iterdir()):
            raise RuntimeError("primary refinement matrix requires an empty controlled output root")
        if parent_run_id is not None:
            _validate_diagnostic_parent(output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id)
        for case in selected:
            result = run_case(root=root, output_root=output_root, matrix_path=root / "configs/phase6_experiment_matrix.yaml", config=preflight["config"], fingerprints=preflight["fingerprints"], anchors=preflight["anchors"], locked_environment=preflight["locked_environment"], source=preflight["source"], case=case, run_id=f"{run_id_prefix}_{case.case_id}", parent_run_id=parent_run_id, science_executor=science_executor)
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

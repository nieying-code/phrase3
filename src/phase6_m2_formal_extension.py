"""Safe pilot executor for the preregistered M2 formal-extension design."""

from __future__ import annotations

import csv
from copy import deepcopy
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
from time import perf_counter
from typing import Any, Callable, Mapping, Sequence

import yaml

from .evaluation import evaluate_first_stage
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_families import aggregate_oos_evaluation, generate_oos_data
from .phase6_io import atomic_write_csv, atomic_write_json, read_lf_bytes, sha256_lf_text_file
from .phase6_locking import exclusive_file_lock
from .phase6_m1 import objective_tolerance, solve_minimum_feasible_reserve, solve_reserve_face_point
from .phase6_m2 import (
    M2_E3_COMPONENT_FILES,
    M2_FAMILY_COMPONENT_FILES,
    _sha256_payload,
    m2_model_context,
    reconstruct_frozen_demand_latent,
    resolve_supply_disruption_profile,
    solve_m2_endogenous_extensive,
    solve_m2_fixed_reserve,
)
from .phase6_m2_development import (
    DevelopmentStageError,
    PeakRSSSampler,
    _decision_sha256,
    _failure_counts,
    _native_failure_status,
    _require_optimal,
    compact_failure,
    validate_run_id,
)
from .phase6_m2c2_confirmation import (
    _confirmation_component_hashes,
    _cross_item_metrics,
    _evaluate_c0_equivalence,
    _m2c2_matrix,
    recompute_m2c2_deterministic_baseline,
    _science_config,
    _validate_m2c2_baseline,
    apply_m2c2_supply_disruption,
)
from .phase6_protocol import generate_phase6_data, load_phase6_matrix
from .reproducibility import capture_runtime_context, sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_formal_extension_design_v1_0"
RUNNER_NAMESPACE = "phase6_m2_formal_extension_v1_0"
OUTPUT_ROOT = "outputs/phase6_m2_formal_extension_v1_0"
READY_STATUS = "frozen_for_pilot_execution"
APPROVAL_PATH = "configs/phase6_m2_formal_extension_pilot_approval.yaml"
ENDPOINT_OBJECTIVE_COMPARISON_SLACK = 1.0e-8
PARENT_AUDIT_PATH = "docs/handoffs/2026-08-14_phase6_m2c2_confirmation_grid_audit.json"
CONFIRMATION_CONFIG_PATH = "configs/phase6_m2_two_item_confirmation.yaml"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256", "e3_component_sha256",
    "family_component_sha256", "runner_config_sha256", "environment_sha256",
)
REGISTRY_FIELDS = (
    "run_id", "parent_run_id", "case_id", "run_kind", "tier_id", "seed",
    "test_seed", "beta", "profile_id", "status", "wall_seconds",
    "peak_memory_mb", *FINGERPRINT_FIELDS, "result_path", "manifest_path",
    "manifest_sha256", "failure_stage", "updated_at_utc",
)
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2c2_confirmation.py",
    "src/phase6_m2_formal_extension.py",
    "src/run_phase6_m2_formal_extension.py",
    "src/phase6_m2_formal_extension_status.py",
    "configs/phase6_m2_formal_extension.yaml",
    "configs/phase6_m2_formal_extension_runner.yaml",
    CONFIRMATION_CONFIG_PATH,
    PARENT_AUDIT_PATH,
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


@dataclass(frozen=True)
class PilotCase:
    case_id: str
    run_kind: str
    tier_id: str
    seed: int
    beta: float
    profile_id: str
    test_seed: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_formal_extension_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise ValueError("unsupported M2 formal-extension protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE or payload.get("output_root") != OUTPUT_ROOT:
        raise ValueError("M2 formal-extension identity mismatch")
    seeds = payload.get("seed_protocol") or {}
    if tuple(seeds.get("pilot_seeds", ())) != (2026081601, 2026081602, 2026081603):
        raise ValueError("unexpected mechanism pilot seeds")
    if tuple(seeds.get("pilot_test_seeds", ())) != (2026081701,):
        raise ValueError("unexpected OOS pilot test seed")
    if set(seeds["pilot_seeds"]) & set(seeds["pilot_test_seeds"]):
        raise ValueError("pilot training and test seeds overlap")
    if payload.get("execution_boundaries", {}).get("runner_implemented") is not True:
        raise ValueError("formal-extension pilot runner is not enabled")
    if payload.get("execution_boundaries", {}).get("formal_extension_authorized") is not False:
        raise ValueError("formal execution must remain unauthorized")
    return payload


def build_pilot_cases(config: Mapping[str, Any]) -> tuple[PilotCase, ...]:
    seeds = tuple(int(value) for value in config["seed_protocol"]["pilot_seeds"])
    mechanism = tuple(
        PilotCase(
            case_id=(f"M2F2_seed{seed}_beta{beta:.2f}_profile{profile}").replace(".", "p"),
            run_kind="mechanism", tier_id="M2F2", seed=seed,
            beta=beta, profile_id=profile,
        )
        for seed in seeds
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    )
    probe = PilotCase(
        case_id="M2F2_OOS_probe_train2026081601_test2026081701_beta1p10_profileT03",
        run_kind="OOS_probe", tier_id="M2F2", seed=2026081601,
        test_seed=2026081701, beta=1.1, profile_id="T03",
    )
    cases = (*mechanism, probe)
    if len(mechanism) != 15 or len({case.case_id for case in cases}) != 16:
        raise ValueError("formal-extension pilot matrix identity failure")
    return cases


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative)); digest.update(b"\0")
    return digest.hexdigest()


def formal_extension_fingerprints(
    root: Path, config_path: Path, runner_path: Path,
) -> dict[str, str]:
    config = load_formal_extension_config(config_path)
    scientific = {key: value for key, value in config.items() if key not in LIFECYCLE_FIELDS}
    scientific_hash = hashlib.sha256(json.dumps(
        scientific, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": scientific_hash,
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def _confirmation_config(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / CONFIRMATION_CONFIG_PATH).read_text(encoding="utf-8"))


def _formal_matrix(
    matrix: Mapping[str, Any], formal: Mapping[str, Any], confirmation: Mapping[str, Any],
    *, scenario_count: int,
) -> dict[str, Any]:
    result = _m2c2_matrix(matrix, confirmation)
    source = next(row for row in result["scale_tiers"] if row["id"] == "M2C2")
    tier = deepcopy(source)
    tier.update(id="M2F2", label="two_item_formal_extension", training_scenarios=int(scenario_count))
    result["scale_tiers"] = [row for row in result["scale_tiers"] if row["id"] != "M2F2"] + [tier]
    result["budget_plan"]["reference_budget_by_tier"]["M2F2"] = float(
        formal["scientific_model"]["reference_budget"]
    )
    return result


def _science_config_for_formal(root: Path, formal: Mapping[str, Any]) -> dict[str, Any]:
    confirmation = _confirmation_config(root)
    combined = _science_config(root, confirmation)
    combined["disruption_profiles"] = {
        name: {key: value[key] for key in ("enabled", "loss_scale", "recovery_fraction")}
        for name, value in formal["profiles"].items()
    }
    return combined


def _validate_formal_baseline_before_generation(
    matrix: Mapping[str, Any], formal: Mapping[str, Any],
    confirmation: Mapping[str, Any], *, beta: float, scenario_count: int,
) -> tuple[dict[str, Any], float, float, tuple[float, ...]]:
    """Recompute and close every deterministic M2F2 input before RNG is touched."""
    baseline_matrix = _m2c2_matrix(matrix, confirmation)
    approved = _validate_m2c2_baseline(baseline_matrix, confirmation)
    independently_recomputed = recompute_m2c2_deterministic_baseline(
        baseline_matrix, confirmation,
    )
    reference = float(formal["scientific_model"]["reference_budget"])
    expected_capacity = tuple(
        float(value) for value in formal["scientific_model"]["storage_capacity"]
    )
    if not math.isclose(
        float(independently_recomputed["reference_budget"]), reference,
        rel_tol=0.0, abs_tol=1.0e-9,
    ) or not math.isclose(
        float(approved["reference_budget"]), reference,
        rel_tol=0.0, abs_tol=1.0e-9,
    ):
        raise ValueError("M2F2 reference budget fails independent pre-generation recomputation")
    if len(expected_capacity) != 6 or len(approved["storage_capacity"]) != 6 or any(
        not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1.0e-9)
        for actual, expected in zip(
            independently_recomputed["storage_capacity"], expected_capacity, strict=True,
        )
    ) or any(
        not math.isclose(float(actual), expected, rel_tol=0.0, abs_tol=1.0e-9)
        for actual, expected in zip(approved["storage_capacity"], expected_capacity, strict=True)
    ):
        raise ValueError("M2F2 storage capacity fails independent pre-generation recomputation")
    tracks = (
        formal["mechanism_experiment"]["primary_track"],
        formal["mechanism_experiment"]["secondary_track"],
    )
    track_betas = tuple(float(row["beta"]) for row in tracks)
    if track_betas != (1.1, 1.3):
        raise ValueError("M2F2 frozen budget tracks must be beta 1.1 and 1.3")
    for track in tracks:
        track_beta = float(track["beta"])
        track_budget = track_beta * reference
        if not math.isclose(
            float(track["budget"]), track_budget, rel_tol=0.0, abs_tol=1.0e-9,
        ) or not math.isclose(
            float(independently_recomputed["budgets"][str(track_beta)]), track_budget,
            rel_tol=0.0, abs_tol=1.0e-9,
        ):
            raise ValueError(
                f"M2F2 beta={track_beta} budget fails simultaneous pre-generation recomputation"
            )
    budget = float(beta) * reference
    matching = [row for row in tracks if math.isclose(float(row["beta"]), float(beta), abs_tol=1e-12)]
    if len(matching) != 1:
        raise ValueError("M2F2 requested beta is outside the frozen budget tracks")
    formal_matrix = _formal_matrix(
        matrix, formal, confirmation, scenario_count=scenario_count,
    )
    if not math.isclose(
        float(formal_matrix["budget_plan"]["reference_budget_by_tier"]["M2F2"]),
        reference, rel_tol=0.0, abs_tol=1.0e-9,
    ):
        raise ValueError("M2F2 generated matrix reference budget mismatch")
    return formal_matrix, reference, budget, expected_capacity


def _plan_payload(
    *, strategy_id: str, reserve: float, regular_purchase: Mapping[str, Sequence[float]],
    objective: float, joint_scenario_set_sha256: str,
) -> dict[str, Any]:
    purchase = {item: [float(value) for value in values] for item, values in regular_purchase.items()}
    return {
        "artifact_state": "pending_finalization",
        "strategy_id": strategy_id,
        "reserve_amount": float(reserve),
        "regular_purchase": purchase,
        "regular_purchase_sha256": _decision_sha256(purchase),
        "exact_training_objective": float(objective),
        "training_joint_scenario_set_sha256": joint_scenario_set_sha256,
    }


def execute_mechanism_science(**kwargs: Any) -> dict[str, Any]:
    root: Path = kwargs["project_root"]
    config = kwargs["config"]
    case: PilotCase = kwargs["case"]
    progress = kwargs["progress"]
    confirmation = _confirmation_config(root)
    matrix, reference, budget, expected_capacity = _validate_formal_baseline_before_generation(
        kwargs["matrix"], config, confirmation, beta=case.beta, scenario_count=100,
    )
    progress("scenario_generation", {"budget": budget, "reference_budget": reference})
    base_generated = generate_phase6_data(
        matrix, matrix_path=kwargs["matrix_path"], tier_id="M2F2", seed=case.seed, budget=budget,
    )
    if any(not math.isclose(a, b, abs_tol=1.0e-9) for a, b in zip(
        base_generated.data.storage_capacity, expected_capacity, strict=True,
    )):
        raise ValueError("generated M2F2 storage capacity mismatch")
    latent = reconstruct_frozen_demand_latent(matrix, base_generated)
    vulnerability = {"relief_food_1": 0.8, "relief_food_2": 1.2}
    generated = apply_m2c2_supply_disruption(
        base_generated,
        profile=resolve_supply_disruption_profile(_science_config_for_formal(root, config), case.profile_id),
        demand_latent=latent,
        item_vulnerability_multiplier=vulnerability,
    )
    data = generated.data
    seconds = float(config["compute_gate"]["per_solver_call_seconds"])
    absolute, relative = 1.0e-5, 1.0e-7
    progress("minimum_feasible_reserve", {})
    floor = solve_minimum_feasible_reserve(data, solver_threads=1, time_limit_seconds=seconds)
    _require_optimal("minimum_feasible_reserve", floor.status, f"minimum feasible reserve failed: {floor.status}")
    progress("complete_extensive_optimum", {})
    optimum = solve_m2_endogenous_extensive(
        data, solver_threads=1, time_limit_seconds=seconds, consistency_tolerance=absolute,
    )
    _require_optimal("complete_extensive_optimum", _native_failure_status(optimum), f"complete optimum failed: {optimum.status}")
    if optimum.objective is None or optimum.master.objective is None:
        raise RuntimeError("complete optimum returned no objective")
    tolerance = objective_tolerance(
        float(optimum.objective), absolute_tolerance=absolute, relative_tolerance=relative,
    )
    common = dict(
        data=data, master_optimum=float(optimum.master.objective),
        exact_optimum=float(optimum.objective), tolerance=tolerance,
        solver_preference=("gurobi",), time_limit_seconds=seconds,
        solver_threads=1, feasibility_tolerance=1.0e-7, optimality_tolerance=1.0e-7,
    )
    progress("minimum_tolerance_optimal_reserve", {})
    with m2_model_context():
        minimum = solve_reserve_face_point(direction="min", **common)
    _require_optimal("minimum_tolerance_optimal_reserve", _native_failure_status(minimum), f"minimum endpoint failed: {minimum.status}")
    progress("maximum_tolerance_optimal_reserve", {})
    with m2_model_context():
        maximum = solve_reserve_face_point(direction="max", **common)
    _require_optimal("maximum_tolerance_optimal_reserve", _native_failure_status(maximum), f"maximum endpoint failed: {maximum.status}")
    fixed, plan_payloads = [], {
        "endogenous_reserve": _plan_payload(
            strategy_id="endogenous_reserve", reserve=minimum.reserve,
            regular_purchase=minimum.regular_purchase, objective=minimum.exact_objective,
            joint_scenario_set_sha256=generated.joint_scenario_set_sha256,
        )
    }
    strategy_names = {
        0.0: "zero_autonomous_reserve", 0.1: "fixed_autonomous_reserve_0_10",
        0.3: "fixed_autonomous_reserve_0_30", 0.5: "fixed_autonomous_reserve_0_50",
    }
    for rho in (0.0, 0.1, 0.3, 0.5):
        progress(f"fixed_autonomous_reserve_{rho:.1f}", {"rho": rho})
        solution = solve_m2_fixed_reserve(
            data, reserve_ratio=rho, solver_threads=1,
            time_limit_seconds=seconds, consistency_tolerance=absolute,
        )
        _require_optimal(f"fixed_autonomous_reserve_{rho:.1f}", _native_failure_status(solution), f"fixed rho={rho} failed: {solution.status}")
        expected_reserve = float(floor.reserve) + rho * (budget - float(floor.reserve))
        if not math.isclose(float(solution.reserve), expected_reserve, abs_tol=1.0e-8):
            raise RuntimeError("fixed autonomous reserve formula mismatch")
        strategy = strategy_names[rho]
        payload = _plan_payload(
            strategy_id=strategy, reserve=solution.reserve,
            regular_purchase=solution.master.regular_purchase,
            objective=solution.objective,
            joint_scenario_set_sha256=generated.joint_scenario_set_sha256,
        )
        plan_payloads[strategy] = payload
        fixed.append({
            "rho": rho, "strategy_id": strategy, "reserve": solution.reserve,
            "objective": solution.objective,
            "regular_purchase_sha256": payload["regular_purchase_sha256"],
            "regular_purchase_reoptimized": True, "status": solution.status,
        })
    endpoint_counts = {
        "minimum": _failure_counts(minimum.evaluation),
        "maximum": _failure_counts(maximum.evaluation),
    }
    if any(sum(values.values()) for values in endpoint_counts.values()):
        raise RuntimeError("M2F2 endpoint exact recourse evaluation is incomplete")
    robust = max(0.0, float(minimum.reserve) - float(floor.reserve))
    ratio = robust / budget
    science: dict[str, Any] = {
        "tier_id": "M2F2", "seed": case.seed, "beta": case.beta,
        "profile_id": case.profile_id, "budget": budget,
        "reference_budget": reference, "storage_capacity": list(expected_capacity),
        "training_scenario_count": 100, "R_star": optimum.reserve,
        "R_min_feas": floor.reserve, "R_min_opt": minimum.reserve,
        "R_max_opt": maximum.reserve, "R_disc_robust": robust,
        "R_disc_robust_ratio": ratio, "numerical_activation": ratio > 1.0e-4,
        "substantive_activation": ratio >= 0.01,
        "moderate_activation": 0.05 <= ratio <= 0.50,
        "objective_tolerance": tolerance,
        "complete_extensive_objective": optimum.objective,
        "minimum_endpoint_status": minimum.status,
        "maximum_endpoint_status": maximum.status,
        "minimum_endpoint_exact_objective": minimum.exact_objective,
        "maximum_endpoint_exact_objective": maximum.exact_objective,
        "minimum_endpoint_consistency_difference": abs(float(minimum.exact_objective) - float(optimum.objective)),
        "maximum_endpoint_consistency_difference": abs(float(maximum.exact_objective) - float(optimum.objective)),
        "minimum_endpoint_regular_purchase_sha256": _decision_sha256(minimum.regular_purchase),
        "maximum_endpoint_regular_purchase_sha256": _decision_sha256(maximum.regular_purchase),
        "endpoint_failure_counts": endpoint_counts, "fixed_reserve_policies": fixed,
        "fulfillment_statistics": generated.statistics.as_dict(),
        "joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
        "scenario_component_set_sha256": _confirmation_component_hashes(generated),
        "scenario_identity_count": len(generated.scenario_identities),
        "cross_item_allocation": _cross_item_metrics(data, minimum, 1.0e-7),
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
        "_plan_payloads": plan_payloads,
    }
    if case.profile_id == "C0":
        progress("C0_no_disruption_equivalence", {})
        science["c0_equivalence"] = _evaluate_c0_equivalence(
            base_data=base_generated.data, c0_data=data, c0_optimum=optimum,
            c0_minimum=minimum, c0_maximum=maximum, absolute=absolute,
            relative=relative, seconds=seconds,
        )
        if science["c0_equivalence"]["status"] != "passed":
            raise RuntimeError("C0 failed no-disruption equivalence")
    else:
        science["c0_equivalence"] = {"required": False, "status": "not_applicable"}
    return science


def _read_registry(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _run_directory(output_root: Path, run_id: str) -> Path:
    validate_run_id(run_id)
    root = (output_root / "pilot/runs").resolve()
    path = (root / run_id).resolve()
    if path.parent != root:
        raise ValueError("run path escapes controlled output root")
    return path


def _write_registry(output_root: Path, row: Mapping[str, Any]) -> None:
    base = output_root / "pilot"
    path = base / "pilot_run_registry.csv"
    with exclusive_file_lock(base / ".registry.lock"):
        rows = _read_registry(path)
        if any(item["run_id"] == row["run_id"] for item in rows):
            raise ValueError("formal-extension pilot run_id is immutable")
        rows.append({field: row.get(field, "") for field in REGISTRY_FIELDS})
        atomic_write_csv(path, REGISTRY_FIELDS, rows)


def _controlled_artifact_paths(
    output_root: Path, row: Mapping[str, str],
) -> tuple[Path, Path]:
    run_id = str(row["run_id"]); validate_run_id(run_id)
    directory = (output_root / "pilot/runs" / run_id).resolve()
    result = Path(row["result_path"]).resolve()
    manifest = Path(row["manifest_path"]).resolve()
    if result != directory / "result.json" or manifest != directory / "manifest.json":
        raise ValueError("registry artifact path leaves the pilot namespace")
    return result, manifest


def _validate_artifact(output_root: Path, row: Mapping[str, str]) -> dict[str, Any]:
    result_path, manifest_path = _controlled_artifact_paths(output_root, row)
    if sha256_file(manifest_path) != row["manifest_sha256"]:
        raise ValueError("manifest hash mismatch")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("artifact_state") != "finalized" or sha256_file(result_path) != manifest.get("result_sha256"):
        raise ValueError("result is not finalized or hash mismatches")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if (
        result.get("finalized") is not True
        or result.get("run_id") != row["run_id"]
        or result.get("case_id") != row["case_id"]
        or result.get("status") != row["status"]
    ):
        raise ValueError("result identity mismatches registry")
    case = result.get("case") or {}
    expected = {
        "run_kind": row["run_kind"], "tier_id": row["tier_id"],
        "seed": int(row["seed"]), "beta": float(row["beta"]),
        "profile_id": row["profile_id"],
    }
    if any(case.get(key) != value for key, value in expected.items()):
        raise ValueError("result case identity mismatches registry")
    expected_test = int(row["test_seed"]) if str(row.get("test_seed", "")).strip() else None
    if case.get("test_seed") != expected_test:
        raise ValueError("result test seed mismatches registry")
    if str(result.get("parent_run_id") or "") != str(row.get("parent_run_id") or ""):
        raise ValueError("result parent identity mismatches registry")
    wall = float(row["wall_seconds"])
    if not math.isfinite(wall) or not math.isclose(wall, float(result["wall_seconds"]), rel_tol=1e-12, abs_tol=1e-9):
        raise ValueError("result wall time mismatches registry")
    expected_fingerprints = {key: row[key] for key in FINGERPRINT_FIELDS}
    if result.get("fingerprints") != expected_fingerprints or manifest.get("fingerprints") != expected_fingerprints:
        raise ValueError("artifact fingerprints mismatch registry")
    directory = result_path.parent
    for name, field in (
        ("checkpoint.json", "checkpoint_sha256"),
        ("status_summary.json", "status_summary_sha256"),
        ("heartbeat.json", "heartbeat_sha256"),
    ):
        path = directory / name
        if not path.is_file() or manifest.get(field) != sha256_file(path):
            raise ValueError(f"terminal artifact mismatch: {name}")
    return result


def _validate_plan_artifact(
    *, output_root: Path, source_run_id: str, identity: Mapping[str, Any],
) -> dict[str, Any]:
    strategy_id = str(identity["strategy_id"])
    validate_run_id(source_run_id)
    expected = (output_root / "pilot/runs" / source_run_id / "plans" / f"{strategy_id}.json").resolve()
    path = Path(identity["path"]).resolve()
    if path != expected or not path.is_file():
        raise ValueError("plan artifact path leaves its source run")
    if sha256_file(path) != identity["finalized_plan_artifact_sha256"]:
        raise ValueError("plan artifact hash mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        payload.get("artifact_state") != "finalized"
        or payload.get("source_run_id") != source_run_id
        or payload.get("strategy_id") != strategy_id
        or payload.get("regular_purchase_sha256") != identity["regular_purchase_sha256"]
        or not math.isclose(
            float(payload.get("reserve_amount", math.nan)),
            float(identity.get("reserve_amount", math.nan)), abs_tol=1e-9,
        )
        or not math.isclose(
            float(payload.get("exact_training_objective", math.nan)),
            float(identity.get("exact_training_objective", math.nan)), abs_tol=1e-8,
        )
        or payload.get("training_joint_scenario_set_sha256")
        != identity.get("training_joint_scenario_set_sha256")
    ):
        raise ValueError("plan artifact identity mismatch")
    payload["finalized_plan_artifact_sha256"] = identity["finalized_plan_artifact_sha256"]
    return payload


def _source_mechanism_result(
    output_root: Path, fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    rows = _read_registry(output_root / "pilot/pilot_run_registry.csv")
    matches = [
        row for row in rows
        if row.get("run_kind") == "mechanism"
        and int(row.get("seed", -1)) == 2026081601
        and math.isclose(float(row.get("beta", -1.0)), 1.1, abs_tol=1e-12)
        and row.get("profile_id") == "T03"
        and row.get("status") == "optimal"
        and all(row.get(key) == value for key, value in fingerprints.items())
        and not row.get("parent_run_id", "").strip()
    ]
    if len(matches) != 1:
        raise ValueError("OOS probe requires one finalized training mechanism run")
    return _validate_artifact(output_root, matches[0])


def _cross_item_from_evaluation(data: Any, evaluation: Any, tolerance: float) -> dict[str, Any]:
    spend_mapping: dict[str, dict[str, float]] = {}
    shares: list[float] = []
    item_positive = {item: False for item in data.items}
    for scenario in data.scenarios:
        recourse = evaluation.scenario_results[scenario]
        item_spend = {
            item: sum(
                float(data.emergency_price[scenario][item][t])
                * float(recourse.emergency_purchase[item][t])
                for t in range(data.periods)
            )
            for item in data.items
        }
        total = sum(item_spend.values())
        spend_mapping[scenario] = {**item_spend, "total": total}
        for item in data.items:
            item_positive[item] = item_positive[item] or item_spend[item] > tolerance
        if total > tolerance:
            shares.append(item_spend[data.items[0]] / total)
    share_range = max(shares) - min(shares) if len(shares) >= 2 else 0.0
    return {
        "scenario_item_emergency_spend_sha256": _sha256_payload(spend_mapping),
        "positive_total_emergency_spend_scenario_count": len(shares),
        "both_items_each_positive_in_at_least_one_scenario": all(item_positive.values()),
        "item1_emergency_spend_share_range": share_range,
    }


def execute_oos_probe_science(**kwargs: Any) -> dict[str, Any]:
    root: Path = kwargs["project_root"]
    output_root: Path = kwargs["output_root"]
    fingerprints = kwargs["fingerprints"]
    config = kwargs["config"]
    case: PilotCase = kwargs["case"]
    progress = kwargs["progress"]
    source = _source_mechanism_result(output_root, fingerprints)
    identities = source["science"]["first_stage_plan_artifacts"]
    required_strategies = (
        "endogenous_reserve", "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    )
    if tuple(identities) != required_strategies:
        raise ValueError("OOS source plan set is incomplete")
    plans = {
        strategy: _validate_plan_artifact(
            output_root=output_root, source_run_id=source["run_id"], identity=identities[strategy],
        )
        for strategy in required_strategies
    }
    confirmation = _confirmation_config(root)
    matrix, reference, budget, expected_capacity = _validate_formal_baseline_before_generation(
        kwargs["matrix"], config, confirmation, beta=case.beta, scenario_count=2000,
    )
    progress("OOS_scenario_generation", {"test_seed": case.test_seed, "scenario_count": 2000})
    base_generated = generate_oos_data(
        matrix, matrix_path=kwargs["matrix_path"], tier_id="M2F2",
        test_seed=int(case.test_seed), budget=budget,
    )
    if any(not math.isclose(a, b, abs_tol=1.0e-9) for a, b in zip(
        base_generated.data.storage_capacity, expected_capacity, strict=True,
    )):
        raise ValueError("generated OOS M2F2 storage capacity mismatch")
    latent = reconstruct_frozen_demand_latent(matrix, base_generated)
    generated = apply_m2c2_supply_disruption(
        base_generated,
        profile=resolve_supply_disruption_profile(_science_config_for_formal(root, config), "T03"),
        demand_latent=latent,
        item_vulnerability_multiplier={"relief_food_1": 0.8, "relief_food_2": 1.2},
    )
    seconds = float(config["compute_gate"]["per_solver_call_seconds"])
    results: dict[str, Any] = {}
    for strategy, plan in plans.items():
        progress(f"OOS_evaluate_{strategy}", {"strategy_id": strategy})
        started = perf_counter()
        with m2_model_context():
            evaluation = evaluate_first_stage(
                generated.data, plan["regular_purchase"], float(plan["reserve_amount"]),
                time_limit_seconds=seconds, solver_threads=1,
            )
        metrics = aggregate_oos_evaluation(
            generated.data, evaluation, reserve=float(plan["reserve_amount"]),
        )
        if metrics["plan_oos_status"] != "complete_feasible":
            raise DevelopmentStageError(
                f"OOS_evaluate_{strategy}", "unexpected_infeasible_recourse",
                f"OOS probe is incomplete: {metrics['plan_oos_status']}",
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
                generated.data, evaluation, 1.0e-7,
            ),
        }
    return {
        "tier_id": "M2F2", "seed": case.seed, "test_seed": case.test_seed,
        "beta": case.beta, "profile_id": case.profile_id,
        "budget": budget, "reference_budget": reference,
        "source_mechanism_run_id": source["run_id"],
        "source_training_joint_scenario_set_sha256": source["science"]["joint_scenario_set_sha256"],
        "test_joint_scenario_set_sha256": generated.joint_scenario_set_sha256,
        "test_scenario_component_set_sha256": _confirmation_component_hashes(generated),
        "test_scenario_identity_count": len(generated.scenario_identities),
        "strategy_results": results,
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def validate_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool,
) -> dict[str, Any]:
    config = load_formal_extension_config(config_path)
    if config.get("status") != READY_STATUS:
        raise RuntimeError("M2 formal-extension pilot protocol is not frozen")
    if not authorize:
        raise PermissionError("--authorize-pilot-execution is required")
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("output_root") != OUTPUT_ROOT:
        raise RuntimeError("formal-extension runner identity mismatch")
    execution = runner.get("execution") or {}
    required_execution = {
        "strictly_serial": True,
        "pilot_execution_requires_explicit_authorization": True,
        "immutable_run_ids": True,
        "full_primary_pilot_required": True,
        "prior_track_authorization_forbidden": True,
        "formal_extension_authorized": False,
        "mechanism_primary_run_count": 15,
        "OOS_probe_run_count": 1,
        "diagnostic_retry_requires_case_id_and_parent_run_id": True,
    }
    if any(execution.get(key) != value for key, value in required_execution.items()):
        raise RuntimeError("formal-extension runner safety metadata mismatch")
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    expected_approval = {
        "approval_id": "phase6_m2_formal_extension_pilot_v1_0",
        "status": READY_STATUS,
        "scientific_protocol": PROTOCOL_ID,
        "runner_namespace": RUNNER_NAMESPACE,
        "mechanism_case_count": 15,
        "OOS_probe_case_count": 1,
        "explicit_cli_authorization_required": True,
        "formal_extension_authorized": False,
        "accept_prior_track_authorization": False,
    }
    if any(approval.get(key) != value for key, value in expected_approval.items()):
        raise RuntimeError("formal-extension pilot approval metadata mismatch")
    actual = formal_extension_fingerprints(root, config_path, runner_path)
    if approval.get("approved_fingerprints") != actual:
        raise RuntimeError("formal-extension pilot fingerprint mismatch")
    parent_path = root / PARENT_AUDIT_PATH
    expected_parent = config["parent_evidence"]["confirmation_audit_sha256"]
    if sha256_file(parent_path) != expected_parent:
        raise RuntimeError("formal-extension parent evidence hash mismatch")
    parent = json.loads(parent_path.read_text(encoding="utf-8"))
    if (
        parent.get("projection", {}).get("overall_decision")
        != "permit_separate_formal_extension_design_PR_only"
        or parent.get("formal_extension_authorized") is not False
    ):
        raise RuntimeError("formal-extension parent evidence decision mismatch")
    required = [root / path for path in FAMILY_COMPONENT_FILES]
    required += [config_path, runner_path, approval_path, root / "requirements-gurobi-lock.txt"]
    source = validate_execution_source(root, required_tracked_paths=sorted(set(required)))
    return {
        "config": config, "runner": runner, "approval": approval,
        "fingerprints": actual, "parent_evidence": parent,
        "locked_environment": validate_locked_environment(root), "source": source,
    }


def _write_plan_artifacts(
    *, directory: Path, run_id: str, case_id: str,
    payloads: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    plan_root = directory / "plans"
    identities: dict[str, dict[str, Any]] = {}
    for strategy, raw in payloads.items():
        path = plan_root / f"{strategy}.json"
        payload = {
            **dict(raw), "artifact_state": "finalized",
            "source_run_id": run_id, "source_case_id": case_id,
            "finalized_at_utc": utc_now(),
        }
        atomic_write_json(path, payload)
        digest = sha256_file(path)
        payload["finalized_plan_artifact_sha256"] = digest
        # Hash is an external identity field; adding it to the file would be self-referential.
        identities[strategy] = {
            "strategy_id": strategy,
            "reserve_amount": payload["reserve_amount"],
            "regular_purchase_sha256": payload["regular_purchase_sha256"],
            "exact_training_objective": payload["exact_training_objective"],
            "training_joint_scenario_set_sha256": payload["training_joint_scenario_set_sha256"],
            "path": str(path.resolve()),
            "finalized_plan_artifact_sha256": digest,
        }
    return identities


def _write_terminal_diagnostic(
    directory: Path, *, run_id: str, case_id: str, stage: str,
    status: str, error: BaseException,
) -> None:
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
    for name in ("runner_exception.json", "status_summary.json", "heartbeat.json"):
        try:
            atomic_write_json(directory / name, payload)
        except Exception:
            pass


def _validate_diagnostic_parent(
    output_root: Path, *, case_id: str, parent_run_id: str,
) -> None:
    validate_run_id(parent_run_id)
    rows = _read_registry(output_root / "pilot/pilot_run_registry.csv")
    matches = [row for row in rows if row.get("run_id") == parent_run_id]
    if len(matches) != 1:
        raise ValueError("diagnostic parent_run_id must identify one existing run")
    parent = matches[0]
    if parent.get("parent_run_id", "").strip() or parent.get("case_id") != case_id:
        raise ValueError("diagnostic parent must be a primary run of the same case")
    if parent.get("status") not in {"stage_failure", "timeout", "runner_exception", "interrupted"}:
        raise ValueError("diagnostic parent must have a failure terminal state")


def _finalization_failure_ids(base: Path) -> list[str]:
    if not (base / "runs").is_dir():
        return []
    return sorted({
        path.parent.name
        for name in ("runner_exception.json", "registry_failure.json", "projection_failure.json")
        for path in (base / "runs").glob(f"*/{name}")
    })


def _derive_mechanism(science: Mapping[str, Any], case: Mapping[str, Any]) -> dict[str, Any]:
    reference = 2337.610924158743
    expected_budget = float(case["beta"]) * reference
    if (
        science.get("tier_id") != "M2F2"
        or int(science.get("seed", -1)) != int(case["seed"])
        or not math.isclose(float(science.get("beta", -1.0)), float(case["beta"]), abs_tol=1e-12)
        or science.get("profile_id") != case["profile_id"]
        or int(science.get("training_scenario_count", -1)) != 100
        or int(science.get("scenario_identity_count", -1)) != 100
        or not math.isclose(float(science.get("reference_budget", -1.0)), reference, abs_tol=1e-12)
        or not math.isclose(float(science.get("budget", -1.0)), expected_budget, abs_tol=1e-9)
    ):
        raise ValueError("mechanism science identity mismatch")
    if (
        science.get("solver") != "gurobi_direct"
        or science.get("gurobi_optimizer_version") != "13.0.2"
        or science.get("gurobipy_version") != "13.0.2"
        or int(science.get("threads", -1)) != 1
    ):
        raise ValueError("mechanism solver identity mismatch")
    budget = float(science["budget"])
    ratio = max(0.0, float(science["R_min_opt"]) - float(science["R_min_feas"])) / budget
    robust = max(0.0, float(science["R_min_opt"]) - float(science["R_min_feas"]))
    if (
        not math.isclose(robust, float(science.get("R_disc_robust", math.nan)), abs_tol=1e-9)
        or not math.isclose(ratio, float(science["R_disc_robust_ratio"]), abs_tol=1e-12)
        or bool(science.get("numerical_activation")) != (ratio > 1.0e-4)
        or bool(science.get("substantive_activation")) != (ratio >= 0.01)
        or bool(science.get("moderate_activation")) != (0.05 <= ratio <= 0.50)
    ):
        raise ValueError("mechanism autonomous reserve ratio mismatch")
    objective_tolerance_value = float(science.get("objective_tolerance", math.nan))
    minimum_endpoint_difference = float(
        science.get("minimum_endpoint_consistency_difference", math.nan)
    )
    maximum_endpoint_difference = float(
        science.get("maximum_endpoint_consistency_difference", math.nan)
    )
    endpoint_evidence = (
        objective_tolerance_value,
        minimum_endpoint_difference,
        maximum_endpoint_difference,
    )
    if not all(math.isfinite(value) and value >= 0.0 for value in endpoint_evidence):
        raise ValueError("mechanism endpoint tolerance evidence must be finite and nonnegative")
    if (
        science.get("minimum_endpoint_status") != "optimal"
        or science.get("maximum_endpoint_status") != "optimal"
        or minimum_endpoint_difference
        > objective_tolerance_value + ENDPOINT_OBJECTIVE_COMPARISON_SLACK
        or maximum_endpoint_difference
        > objective_tolerance_value + ENDPOINT_OBJECTIVE_COMPARISON_SLACK
    ):
        raise ValueError("mechanism tolerance-optimal reserve interval is invalid")
    if any(
        int(value)
        for endpoint in science["endpoint_failure_counts"].values()
        for value in endpoint.values()
    ):
        raise ValueError("mechanism endpoint evaluation is incomplete")
    identities = science.get("first_stage_plan_artifacts") or {}
    if tuple(identities) != (
        "endogenous_reserve", "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    ):
        raise ValueError("mechanism finalized plan identity set is incomplete")
    fixed = science.get("fixed_reserve_policies") or []
    if (
        [float(row.get("rho", -1.0)) for row in fixed] != [0.0, 0.1, 0.3, 0.5]
        or any(row.get("status") != "optimal" or row.get("regular_purchase_reoptimized") is not True for row in fixed)
        or any(
            not math.isclose(
                float(row.get("reserve", math.nan)),
                float(science["R_min_feas"]) + float(row["rho"]) * (budget - float(science["R_min_feas"])),
                abs_tol=1e-8,
            )
            for row in fixed
        )
    ):
        raise ValueError("mechanism fixed autonomous-reserve policies are invalid")
    components = dict(science.get("scenario_component_set_sha256") or {})
    required_components = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256", "fulfillment_sha256",
    )
    if any(not re_full_sha256(components.get(field)) for field in required_components):
        raise ValueError("mechanism scenario component identity is incomplete")
    c0 = science.get("c0_equivalence") or {}
    if (case["profile_id"] == "C0") != (c0.get("status") == "passed"):
        raise ValueError("mechanism C0 equivalence evidence mismatch")
    return {
        "components": components,
        "ratio": ratio, "substantive": ratio >= 0.01,
        "moderate": 0.05 <= ratio <= 0.50,
    }


def _derive_probe(
    science: Mapping[str, Any], case: Mapping[str, Any],
    source_mechanism: Mapping[str, Any],
) -> dict[str, Any]:
    if (
        science.get("tier_id") != "M2F2"
        or int(science.get("seed", -1)) != int(case["seed"])
        or int(science.get("test_seed", -1)) != int(case["test_seed"])
        or not math.isclose(float(science.get("beta", -1.0)), float(case["beta"]), abs_tol=1e-12)
        or science.get("profile_id") != case["profile_id"]
        or int(science.get("test_scenario_identity_count", -1)) != 2000
        or science.get("solver") != "gurobi_direct"
        or science.get("gurobi_optimizer_version") != "13.0.2"
        or science.get("gurobipy_version") != "13.0.2"
        or int(science.get("threads", -1)) != 1
    ):
        raise ValueError("OOS probe science identity mismatch")
    strategies = science.get("strategy_results") or {}
    if tuple(strategies) != (
        "endogenous_reserve", "zero_autonomous_reserve",
        "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30",
        "fixed_autonomous_reserve_0_50",
    ):
        raise ValueError("OOS probe strategy set is incomplete")
    source_case = source_mechanism.get("case") or {}
    source_science = source_mechanism.get("science") or {}
    if (
        source_mechanism.get("status") != "optimal"
        or source_case.get("run_kind") != "mechanism"
        or int(source_case.get("seed", -1)) != int(case["seed"])
        or not math.isclose(float(source_case.get("beta", -1.0)), float(case["beta"]), abs_tol=1e-12)
        or source_case.get("profile_id") != case["profile_id"]
        or science.get("source_mechanism_run_id") != source_mechanism.get("run_id")
        or science.get("source_training_joint_scenario_set_sha256")
        != source_science.get("joint_scenario_set_sha256")
    ):
        raise ValueError("OOS probe is not bound to its approved source mechanism run")
    source_plans = source_science.get("first_stage_plan_artifacts") or {}
    if tuple(source_plans) != tuple(strategies):
        raise ValueError("OOS source mechanism strategy mapping is incomplete")
    finite_metrics = (
        "mean_total_cost", "total_cost_p95", "total_cost_cvar95",
        "service_level", "shortage_probability", "mean_emergency_spend",
    )
    for strategy, result in strategies.items():
        metrics = result["metrics"]
        identity = source_plans[strategy]
        if (
            metrics["plan_oos_status"] != "complete_feasible"
            or int(metrics["optimal_scenario_count"]) != 2000
            or int(metrics["infeasible_scenario_count"]) != 0
            or int(metrics["solver_failure_count"]) != 0
            or result.get("test_joint_scenario_set_sha256")
            != science.get("test_joint_scenario_set_sha256")
        ):
            raise ValueError("OOS probe evaluation is incomplete")
        if (
            result.get("strategy_id") != strategy
            or result.get("source_plan_artifact_sha256")
            != identity.get("finalized_plan_artifact_sha256")
            or result.get("source_plan_training_joint_scenario_set_sha256")
            != identity.get("training_joint_scenario_set_sha256")
            or not math.isclose(
                float(result.get("source_plan_exact_training_objective", math.nan)),
                float(identity.get("exact_training_objective", math.nan)), abs_tol=1e-8,
            )
            or not math.isclose(
                float(result.get("reserve_amount", math.nan)),
                float(identity.get("reserve_amount", math.nan)), abs_tol=1e-9,
            )
            or result.get("regular_purchase_sha256")
            != identity.get("regular_purchase_sha256")
        ):
            raise ValueError("OOS strategy result is not bound to its finalized source plan")
        if any(
            not math.isfinite(float(metrics.get(name, math.nan)))
            for name in finite_metrics
        ):
            raise ValueError("OOS frozen metric is missing or non-finite")
        if (
            float(metrics["mean_total_cost"]) < 0.0
            or float(metrics["total_cost_p95"]) < 0.0
            or float(metrics["total_cost_cvar95"]) < 0.0
            or float(metrics["mean_emergency_spend"]) < 0.0
            or not 0.0 <= float(metrics["service_level"]) <= 1.0
            or not 0.0 <= float(metrics["shortage_probability"]) <= 1.0
            or not math.isfinite(float(result.get("wall_seconds", math.nan)))
            or float(result["wall_seconds"]) <= 0.0
        ):
            raise ValueError("OOS frozen metric or strategy runtime is outside its valid range")
        cross = result.get("cross_item_allocation") or {}
        if (
            not re_full_sha256(cross.get("scenario_item_emergency_spend_sha256"))
            or not 0 <= int(cross.get("positive_total_emergency_spend_scenario_count", -1)) <= 2000
            or not isinstance(cross.get("both_items_each_positive_in_at_least_one_scenario"), bool)
            or not math.isfinite(float(cross.get("item1_emergency_spend_share_range", math.nan)))
            or not 0.0 <= float(cross["item1_emergency_spend_share_range"]) <= 1.0
        ):
            raise ValueError("OOS cross-item fund-allocation metric is incomplete")
    components = science.get("test_scenario_component_set_sha256") or {}
    required_components = (
        "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
        "emergency_supply_sha256", "scenario_order_sha256", "fulfillment_sha256",
    )
    if (
        not re_full_sha256(science.get("test_joint_scenario_set_sha256"))
        or any(not re_full_sha256(components.get(field)) for field in required_components)
    ):
        raise ValueError("OOS test scenario identity is incomplete")
    return {
        "maximum_strategy_wall_seconds": max(float(row["wall_seconds"]) for row in strategies.values()),
    }


def re_full_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def update_projection(
    *, output_root: Path, config: Mapping[str, Any], fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    base = output_root / "pilot"
    with exclusive_file_lock(base / ".projection.lock"):
        rows = [
            row for row in _read_registry(base / "pilot_run_registry.csv")
            if all(row.get(key) == value for key, value in fingerprints.items())
        ]
        verified_results: dict[str, dict[str, Any]] = {}
        invalid, diagnostics, duplicates, failed = [], [], [], []
        for row in rows:
            try:
                result = _validate_artifact(output_root, row)
                if row.get("parent_run_id", "").strip():
                    diagnostics.append(row["run_id"]); continue
                if result["case_id"] in verified_results:
                    duplicates.append(result["case_id"]); continue
                if result["status"] != "optimal":
                    failed.append(result["run_id"]); continue
                if result["case"]["run_kind"] == "mechanism":
                    for identity in (result["science"].get("first_stage_plan_artifacts") or {}).values():
                        _validate_plan_artifact(
                            output_root=output_root,
                            source_run_id=result["run_id"],
                            identity=identity,
                        )
                verified_results[result["case_id"]] = result
            except Exception:
                invalid.append(row.get("run_id", ""))
        cases = build_pilot_cases(config)
        mechanism_cases = [case for case in cases if case.run_kind == "mechanism"]
        mechanism: list[tuple[dict[str, Any], dict[str, Any]] | None] = []
        for case in mechanism_cases:
            result = verified_results.get(case.case_id)
            try:
                mechanism.append(
                    (result, _derive_mechanism(result["science"], result["case"]))
                    if result is not None else None
                )
            except Exception:
                invalid.append(result.get("run_id", "") if result else "")
                mechanism.append(None)
        probe_case = next(case for case in cases if case.run_kind == "OOS_probe")
        probe_result = verified_results.get(probe_case.case_id)
        source_case = next(
            case for case in mechanism_cases
            if case.seed == probe_case.seed
            and math.isclose(case.beta, probe_case.beta, abs_tol=1e-12)
            and case.profile_id == probe_case.profile_id
        )
        source_result = verified_results.get(source_case.case_id)
        probe = None
        if probe_result is not None and source_result is not None:
            try:
                probe = (
                    probe_result,
                    _derive_probe(probe_result["science"], probe_result["case"], source_result),
                )
            except Exception:
                invalid.append(probe_result.get("run_id", ""))
        crn_checks = []
        for seed in config["seed_protocol"]["pilot_seeds"]:
            group = [entry for case, entry in zip(mechanism_cases, mechanism, strict=True) if case.seed == seed]
            anchor = group[0][1]["components"] if group and group[0] else {}
            fields = (
                "latent_draw_sha256", "demand_sha256", "emergency_price_sha256",
                "emergency_supply_sha256", "scenario_order_sha256",
            )
            match = len(group) == 5 and all(
                entry is not None and all(
                    entry[1]["components"].get(field) == anchor.get(field)
                    and anchor.get(field) is not None for field in fields
                ) for entry in group
            )
            crn_checks.append({"seed": seed, "verified": match})
        finalization_failures = _finalization_failure_ids(base)
        complete = bool(
            len(verified_results) == 16 and all(mechanism) and probe
            and not invalid and not diagnostics and not duplicates and not failed
            and not finalization_failures and all(item["verified"] for item in crn_checks)
        )
        max_mechanism_seconds = max(
            (float(entry[0]["wall_seconds"]) for entry in mechanism if entry), default=math.inf,
        )
        max_oos_seconds = float(probe[1]["maximum_strategy_wall_seconds"]) if probe else math.inf
        mechanism_hours = 50.0 * max_mechanism_seconds / 3600.0
        oos_hours = 50.0 * max_oos_seconds / 3600.0
        combined_hours = mechanism_hours + oos_hours
        gate = config["compute_gate"]
        compute_passed = bool(
            complete
            and mechanism_hours <= float(gate["mechanism_formal_projected_wall_hours_maximum"])
            and oos_hours <= float(gate["out_of_sample_formal_projected_wall_hours_maximum"])
            and combined_hours <= float(gate["combined_extension_projected_wall_hours_maximum"])
        )
        payload = {
            "status": "complete" if complete else "incomplete",
            "fingerprints": dict(fingerprints),
            "required_mechanism_run_count": 15,
            "verified_mechanism_run_count": sum(entry is not None for entry in mechanism),
            "required_OOS_probe_run_count": 1,
            "verified_OOS_probe_run_count": int(probe is not None),
            "invalid_primary_run_ids": sorted(invalid),
            "diagnostic_run_ids": sorted(diagnostics),
            "duplicate_case_ids": sorted(set(duplicates)),
            "failed_primary_run_ids": sorted(failed),
            "finalization_failure_run_ids": finalization_failures,
            "common_random_number_checks": crn_checks,
            "common_random_numbers_verified": all(item["verified"] for item in crn_checks),
            "projection_method": dict(gate["projection_method"]),
            "mechanism_seconds_per_formal_run": max_mechanism_seconds,
            "OOS_seconds_per_formal_plan": max_oos_seconds,
            "mechanism_projected_wall_hours": mechanism_hours,
            "OOS_projected_wall_hours": oos_hours,
            "combined_projected_wall_hours": combined_hours,
            "pilot_compute_gate_passed": compute_passed,
            "next_decision": (
                "permit_separate_formal_freeze_PR_only" if compute_passed
                else "pilot_incomplete_or_compute_gate_failed"
            ),
            "formal_extension_authorized": False,
            "updated_at_utc": utc_now(),
        }
        atomic_write_json(base / "pilot_projection.json", payload)
        return payload


def run_case(
    *, root: Path, output_root: Path, matrix_path: Path,
    config: Mapping[str, Any], fingerprints: Mapping[str, str],
    locked_environment: Mapping[str, str], source: Mapping[str, Any],
    case: PilotCase, run_id: str, parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    directory = _run_directory(output_root, run_id); directory.mkdir(parents=True, exist_ok=True)
    with exclusive_file_lock(directory / ".run.lock"):
        if any(path.name != ".run.lock" for path in directory.iterdir()):
            raise ValueError("formal-extension pilot run_id is immutable")
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
                "failure": None,
            }
            atomic_write_json(status_path, compact); atomic_write_json(heartbeat, compact)

        try:
            matrix = load_phase6_matrix(matrix_path)
            executor = science_executor or (
                execute_mechanism_science if case.run_kind == "mechanism"
                else execute_oos_probe_science
            )
            science = executor(
                project_root=root, output_root=output_root, fingerprints=fingerprints,
                matrix=matrix, matrix_path=matrix_path, config=config,
                case=case, progress=progress,
            )
            status = "optimal"
        except KeyboardInterrupt:
            status = "interrupted"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": "KeyboardInterrupt", "exception_type": "KeyboardInterrupt"}
        except Exception as exc:
            status = "timeout" if isinstance(exc, TimeoutError) or "time_limit" in str(exc) else "stage_failure"
            failure = {"stage": stages[-1]["stage"] if stages else "initialization", "status": status, "message": f"{type(exc).__name__}: {exc}"[:1000], "exception_type": type(exc).__name__}

        finalization_stage = "memory_sampling"
        try:
            peak = sampler.stop(); wall = perf_counter() - started
            finalization_stage = "plan_artifact_finalization"
            if science is not None and "_plan_payloads" in science:
                payloads = science.pop("_plan_payloads")
                science["first_stage_plan_artifacts"] = _write_plan_artifacts(
                    directory=directory, run_id=run_id, case_id=case.case_id, payloads=payloads,
                )
            finalization_stage = "runtime_context"
            runtime = capture_runtime_context(
                solver_preference=("gurobi",), project_root=root, solver_threads=1,
            )
            result = {
                "run_id": run_id, "parent_run_id": parent_run_id,
                "case_id": case.case_id, "case": case.as_dict(), "status": status,
                "finalized": True, "science": science, "stages": stages,
                "failure": failure, "wall_seconds": wall, "peak_memory_mb": peak,
                "fingerprints": dict(fingerprints), "git_sha": source["commit_sha"],
                "git_tree_sha": source["tree_sha"], "finished_at_utc": utc_now(),
            }
            result_path, manifest_path = directory / "result.json", directory / "manifest.json"
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
                "result_sha256": sha256_file(result_path),
                "checkpoint_sha256": sha256_file(checkpoint),
                "status_summary_sha256": sha256_file(status_path),
                "heartbeat_sha256": sha256_file(heartbeat),
                "fingerprints": dict(fingerprints), "source": dict(source),
                "locked_environment": dict(locked_environment), "runtime_context": runtime,
            })
            row = {
                "run_id": run_id, "parent_run_id": parent_run_id or "",
                "case_id": case.case_id, "run_kind": case.run_kind,
                "tier_id": case.tier_id, "seed": case.seed,
                "test_seed": case.test_seed or "", "beta": case.beta,
                "profile_id": case.profile_id, "status": status,
                "wall_seconds": wall, "peak_memory_mb": peak,
                **dict(fingerprints), "result_path": str(result_path.resolve()),
                "manifest_path": str(manifest_path.resolve()),
                "manifest_sha256": sha256_file(manifest_path),
                "failure_stage": failure.get("stage") if failure else "",
                "updated_at_utc": result["finished_at_utc"],
            }
            finalization_stage = "registry_finalization"
            _write_registry(output_root, row)
            finalization_stage = "projection_finalization"
            projection = update_projection(
                output_root=output_root, config=config, fingerprints=fingerprints,
            )
        except KeyboardInterrupt as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="interrupted", error=exc)
            raise
        except Exception as exc:
            _write_terminal_diagnostic(directory, run_id=run_id, case_id=case.case_id, stage=finalization_stage, status="runner_exception", error=exc)
            raise
        if status == "interrupted":
            raise KeyboardInterrupt
        return {**result, "projection": projection}


def run_pilot(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize: bool, run_id_prefix: str, case_ids: Sequence[str] | None = None,
    parent_run_id: str | None = None,
    science_executor: Callable[..., dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    validate_run_id(run_id_prefix)
    preflight = validate_preflight(
        root=root, config_path=config_path, runner_path=runner_path,
        approval_path=approval_path, authorize=authorize,
    )
    cases = build_pilot_cases(preflight["config"])
    all_ids = {case.case_id for case in cases}
    if parent_run_id is None and case_ids is not None:
        raise ValueError("primary execution must run the complete frozen pilot")
    if parent_run_id is not None and (case_ids is None or len(case_ids) != 1):
        raise ValueError("diagnostic execution requires one case_id and parent_run_id")
    requested = set(case_ids or all_ids)
    if requested - all_ids:
        raise ValueError("unknown formal-extension pilot case")
    selected = [case for case in cases if case.case_id in requested]
    output_root = root / OUTPUT_ROOT; results = []
    with exclusive_file_lock(output_root / "pilot/.serial-execution.lock", timeout_seconds=1.0):
        existing = output_root / "pilot"
        if parent_run_id is None and existing.exists() and any(
            path.name != ".serial-execution.lock" for path in existing.iterdir()
        ):
            raise RuntimeError("primary formal-extension pilot requires an empty output root")
        if parent_run_id is not None:
            _validate_diagnostic_parent(
                output_root, case_id=selected[0].case_id, parent_run_id=parent_run_id,
            )
        for case in selected:
            result = run_case(
                root=root, output_root=output_root,
                matrix_path=root / "configs/phase6_experiment_matrix.yaml",
                config=preflight["config"], fingerprints=preflight["fingerprints"],
                locked_environment=preflight["locked_environment"], source=preflight["source"],
                case=case, run_id=f"{run_id_prefix}_{case.case_id}",
                parent_run_id=parent_run_id, science_executor=science_executor,
            )
            results.append(result)
            if result["status"] != "optimal":
                break
    return results

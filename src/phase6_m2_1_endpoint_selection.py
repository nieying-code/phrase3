"""Frozen M2.1 endpoint-selection protocol and pre-execution safety guard.

This revision deliberately contains no scientific execution path.  It freezes
the design, identities and deterministic selection rule while keeping every
execution authorization false.  A separately reviewed runner revision must
reuse these validators before it may generate a scenario or invoke a solver.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
from typing import Any, Mapping, Sequence

import yaml

from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import read_lf_bytes, sha256_lf_text_file
from .phase6_m2 import M2_E3_COMPONENT_FILES, M2_FAMILY_COMPONENT_FILES
from .reproducibility import sha256_file, validate_execution_source


PROTOCOL_ID = "phase6_m2_1_endpoint_selection_design_v1_0"
RUNNER_NAMESPACE = "phase6_m2_1_endpoint_selection_v1_0"
OUTPUT_ROOT = "outputs/phase6_m2_1_endpoint_selection_v1_0"
CONFIG_PATH = "configs/phase6_m2_1_endpoint_selection.yaml"
RUNNER_PATH = "configs/phase6_m2_1_runner.yaml"
APPROVAL_PATH = "configs/phase6_m2_1_approval.yaml"
LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")
FINGERPRINT_FIELDS = (
    "scientific_config_sha256",
    "e3_component_sha256",
    "family_component_sha256",
    "runner_config_sha256",
    "environment_sha256",
)
CANDIDATE_IDS = ("minimum_endpoint", "interval_midpoint", "maximum_endpoint")
TEST_STRATEGIES = (
    "M2_minimum_endpoint",
    "M2_1_validation_selected_endpoint",
    "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10",
    "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)
SCENARIO_IDENTITY_FIELDS = (
    "scenario_set_sha256",
    "scenario_order_sha256",
    "latent_draw_sha256",
    "demand_sha256",
    "emergency_price_sha256",
    "emergency_supply_sha256",
    "fulfillment_sha256",
)
PLAN_IDENTITY_FIELDS = (
    "finalized_plan_artifact_sha256",
    "regular_purchase_sha256",
    "reserve_amount",
    "exact_training_objective",
    "training_joint_scenario_set_sha256",
)
PARENT_AUDITS = {
    "pr58_mechanism": (
        "docs/handoffs/2026-08-21_phase6_m2_formal_mechanism_results_v1_1_audit.json",
        "bce5b075d352a4679b4371a073f5cc0a931a6b309b401318e9f4c38a8a7489a5",
    ),
    "pr60_oos": (
        "docs/handoffs/2026-08-21_phase6_m2_formal_oos_results_v1_1_audit.json",
        "ee1a767df0962b0e625ef0dbe4acbe99b719c14f576b8464a9d338dffe976cd4",
    ),
    "pr61_diagnostic": (
        "docs/handoffs/2026-08-21_phase6_m2_oos_lightweight_diagnostics_v1_1_audit.json",
        "920db65ad09e2c0d46b662b84a80f19ae0ed495dbe75896754683d2a3336bce9",
    ),
}
E3_COMPONENT_FILES = tuple(dict.fromkeys(M2_E3_COMPONENT_FILES + (
    "src/phase6_m2_formal_extension.py",
    "src/phase6_m2_formal_oos.py",
    "src/phase6_m2_1_endpoint_selection.py",
    "src/run_phase6_m2_1_endpoint_selection.py",
    CONFIG_PATH,
    RUNNER_PATH,
    *(path for path, _ in PARENT_AUDITS.values()),
)))
FAMILY_COMPONENT_FILES = tuple(dict.fromkeys(M2_FAMILY_COMPONENT_FILES + E3_COMPONENT_FILES))


class M21ProtocolError(RuntimeError):
    """Raised before any scientific side effect when the protocol is invalid."""


class M21ExecutionNotAuthorized(M21ProtocolError):
    """The design is reviewed independently from any execution authorization."""


@dataclass(frozen=True)
class SeedTriplet:
    phase: str
    position: int
    training_seed: int
    validation_seed: int
    test_seed: int

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _component_sha256(root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(read_lf_bytes(root / relative))
        digest.update(b"\0")
    return digest.hexdigest()


def load_m2_1_config(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("protocol_id") != PROTOCOL_ID:
        raise M21ProtocolError("unsupported M2.1 protocol")
    if payload.get("runner_namespace") != RUNNER_NAMESPACE:
        raise M21ProtocolError("M2.1 runner namespace mismatch")
    if payload.get("output_root") != OUTPUT_ROOT:
        raise M21ProtocolError("M2.1 output namespace mismatch")
    science = payload.get("scientific_scope") or {}
    expected_science = {
        "model": "unchanged_M2_supply_disruption",
        "model_constraints_and_objective_unchanged": True,
        "tier_id": "M2F2",
        "item_count": 2,
        "periods": 6,
        "beta": 1.1,
        "budget": 2571.372016574617,
        "profile_id": "T03",
        "training_scenario_count": 100,
        "validation_scenario_count": 2000,
        "test_scenario_count": 2000,
    }
    for key, expected in expected_science.items():
        if science.get(key) != expected:
            raise M21ProtocolError(f"M2.1 scientific identity mismatch: {key}")
    candidate = payload.get("candidate_protocol") or {}
    if tuple(candidate.get("candidate_ids", ())) != CANDIDATE_IDS:
        raise M21ProtocolError("M2.1 candidate set must contain exactly three frozen points")
    if candidate.get("every_candidate_fixes_reserve_and_reoptimizes_regular_procurement") is not True:
        raise M21ProtocolError("every M2.1 candidate must reoptimize regular procurement")
    binding = candidate.get("minimum_endpoint_identity_binding") or {}
    if (
        binding.get("also_serves_as_M2_control") is not True
        or binding.get("generated_and_finalized_once") is not True
        or binding.get("second_reoptimization_for_M2_control_forbidden") is not True
        or tuple(binding.get("required_equal_fields", ())) != PLAN_IDENTITY_FIELDS
        or binding.get("if_selected_M2_1_and_M2_reference_same_artifact") is not True
        or binding.get("if_selected_test_difference_must_be_zero_within_frozen_tolerance") is not True
    ):
        raise M21ProtocolError("minimum endpoint is not bound to the unique M2 control plan")
    selection = payload.get("validation_selection") or {}
    if tuple(selection.get("criterion_order", ())) != (
        "minimum_cvar95", "minimum_mean_total_cost", "minimum_reserve",
    ):
        raise M21ProtocolError("M2.1 validation selection order changed")
    if selection.get("test_data_use_for_selection_forbidden") is not True:
        raise M21ProtocolError("M2.1 test data must not select a plan")
    validation_crn = selection.get("common_random_numbers") or {}
    if (
        validation_crn.get("generate_validation_scenario_set_once_per_seed_triplet") is not True
        or validation_crn.get("all_three_candidates_reference_same_finalized_scenario_artifact") is not True
        or tuple(validation_crn.get("required_equal_identity_fields", ())) != SCENARIO_IDENTITY_FIELDS
        or validation_crn.get("candidate_specific_random_draws_allowed") != 0
        or validation_crn.get("mismatch_status") != "validation_common_random_number_mismatch"
    ):
        raise M21ProtocolError("M2.1 validation common-random-number identity changed")
    if tuple((payload.get("formal_comparison") or {}).get("strategies", ())) != TEST_STRATEGIES:
        raise M21ProtocolError("M2.1 formal comparator set changed")
    if (payload.get("formal_comparison") or {}).get("primary_estimand") != "M2_1_minus_M2_oos_cvar95":
        raise M21ProtocolError("M2.1 must have exactly the frozen CVaR95 primary estimand")
    test_crn = (payload.get("formal_comparison") or {}).get("common_random_numbers") or {}
    if (
        test_crn.get("generate_test_scenario_set_once_per_seed_triplet") is not True
        or test_crn.get("all_six_strategies_reference_same_finalized_scenario_artifact") is not True
        or tuple(test_crn.get("required_equal_identity_fields", ())) != SCENARIO_IDENTITY_FIELDS
        or test_crn.get("strategy_specific_random_draws_allowed") != 0
        or test_crn.get("mismatch_status") != "test_common_random_number_mismatch"
    ):
        raise M21ProtocolError("M2.1 test common-random-number identity changed")
    _validate_seed_protocol(payload)
    boundaries = payload.get("execution_boundaries") or {}
    for field in (
        "scientific_runner_enabled", "pilot_authorized", "formal_training_authorized",
        "formal_validation_authorized", "selected_plan_freeze_authorized",
        "formal_test_authorized",
    ):
        if boundaries.get(field) is not False:
            raise M21ProtocolError(f"M2.1 design revision must keep {field}=false")
    return payload


def _seed_sets(config: Mapping[str, Any]) -> dict[str, tuple[int, ...]]:
    seeds = config.get("seed_protocol") or {}
    names = (
        "pilot_training_seeds", "pilot_validation_seeds", "pilot_test_seeds",
        "formal_training_seeds", "formal_validation_seeds", "formal_test_seeds",
    )
    return {name: tuple(int(value) for value in seeds.get(name, ())) for name in names}


def _validate_seed_protocol(config: Mapping[str, Any]) -> None:
    sets = _seed_sets(config)
    if any(len(sets[name]) != (3 if name.startswith("pilot_") else 10) for name in sets):
        raise M21ProtocolError("M2.1 seed-set length mismatch")
    if any(len(values) != len(set(values)) for values in sets.values()):
        raise M21ProtocolError("duplicate seed within an M2.1 seed set")
    names = tuple(sets)
    for index, name in enumerate(names):
        for other in names[index + 1:]:
            if set(sets[name]) & set(sets[other]):
                raise M21ProtocolError(f"M2.1 seed overlap: {name} and {other}")


def build_seed_triplets(config: Mapping[str, Any], phase: str) -> tuple[SeedTriplet, ...]:
    if phase not in {"pilot", "formal"}:
        raise M21ProtocolError("phase must be pilot or formal")
    seeds = _seed_sets(config)
    train = seeds[f"{phase}_training_seeds"]
    validation = seeds[f"{phase}_validation_seeds"]
    test = seeds[f"{phase}_test_seeds"]
    return tuple(
        SeedTriplet(phase, index + 1, training, validation_seed, test_seed)
        for index, (training, validation_seed, test_seed) in enumerate(
            zip(train, validation, test, strict=True)
        )
    )


def build_preregistered_plan(config: Mapping[str, Any], phase: str) -> dict[str, Any]:
    triplets = build_seed_triplets(config, phase)
    test_triplet_count = 1 if phase == "pilot" else len(triplets)
    return {
        "phase": phase,
        "seed_triplets": [row.as_dict() for row in triplets],
        "training_interval_runs": len(triplets),
        "validation_candidate_plans": len(triplets) * len(CANDIDATE_IDS),
        "test_strategy_plans": test_triplet_count * len(TEST_STRATEGIES),
        "validation_exact_recourse_evaluations": len(triplets) * len(CANDIDATE_IDS) * 2000,
        "test_exact_recourse_evaluations": test_triplet_count * len(TEST_STRATEGIES) * 2000,
    }


def reserve_candidates(r_min_opt: float, r_max_opt: float) -> dict[str, float]:
    values = (float(r_min_opt), float(r_max_opt))
    if not all(math.isfinite(value) and value >= 0.0 for value in values):
        raise M21ProtocolError("reserve interval endpoints must be finite and nonnegative")
    if values[0] > values[1] + 1.0e-9:
        raise M21ProtocolError("reserve interval endpoints are reversed")
    return {
        "minimum_endpoint": values[0],
        "interval_midpoint": 0.5 * (values[0] + values[1]),
        "maximum_endpoint": values[1],
    }


def _tie_tolerance(best: float, *, absolute: float, relative: float) -> float:
    if not all(math.isfinite(value) and value >= 0.0 for value in (absolute, relative)):
        raise M21ProtocolError("selection tolerances must be finite and nonnegative")
    return absolute + relative * max(1.0, abs(best))


def select_validation_candidate(
    metrics: Mapping[str, Mapping[str, float]], *, absolute: float = 1.0e-5,
    relative: float = 1.0e-7,
) -> dict[str, Any]:
    if tuple(metrics) != CANDIDATE_IDS:
        raise M21ProtocolError("validation metrics must preserve the frozen candidate identity")
    normalized: dict[str, dict[str, float]] = {}
    for candidate, row in metrics.items():
        values = {
            key: float(row[key]) for key in ("total_cost_cvar95", "mean_total_cost", "reserve")
        }
        if not all(math.isfinite(value) and value >= 0.0 for value in values.values()):
            raise M21ProtocolError("validation selection metrics must be finite and nonnegative")
        normalized[candidate] = values
    best_cvar = min(row["total_cost_cvar95"] for row in normalized.values())
    cvar_limit = best_cvar + _tie_tolerance(best_cvar, absolute=absolute, relative=relative)
    cvar_tied = [name for name in CANDIDATE_IDS if normalized[name]["total_cost_cvar95"] <= cvar_limit]
    best_mean = min(normalized[name]["mean_total_cost"] for name in cvar_tied)
    mean_limit = best_mean + _tie_tolerance(best_mean, absolute=absolute, relative=relative)
    finalists = [name for name in cvar_tied if normalized[name]["mean_total_cost"] <= mean_limit]
    selected = min(finalists, key=lambda name: (normalized[name]["reserve"], CANDIDATE_IDS.index(name)))
    return {
        "selected_candidate_id": selected,
        "selection_metrics_sha256": _canonical_sha256(normalized),
        "cvar95_best": best_cvar,
        "cvar95_tie_limit": cvar_limit,
        "mean_cost_best_within_cvar_tie": best_mean,
        "mean_cost_tie_limit": mean_limit,
        "cvar_tied_candidate_ids": cvar_tied,
        "finalist_candidate_ids": finalists,
        "test_metrics_used": False,
    }


def validate_shared_scenario_identity(
    records: Mapping[str, Mapping[str, Any]], *, expected_ids: Sequence[str], phase: str,
) -> dict[str, str]:
    """Require all paired alternatives to reference one finalized scenario identity."""

    if tuple(records) != tuple(expected_ids):
        raise M21ProtocolError(f"{phase} alternative identity set mismatch")
    baseline = {field: str(records[expected_ids[0]].get(field, "")) for field in SCENARIO_IDENTITY_FIELDS}
    if any(len(value) != 64 for value in baseline.values()):
        raise M21ProtocolError(f"{phase} scenario identity is incomplete")
    for value in baseline.values():
        try:
            int(value, 16)
        except ValueError as exc:
            raise M21ProtocolError(f"{phase} scenario identity is not SHA-256") from exc
    for identity in expected_ids[1:]:
        observed = {field: str(records[identity].get(field, "")) for field in SCENARIO_IDENTITY_FIELDS}
        if observed != baseline:
            raise M21ProtocolError(f"{phase}_common_random_number_mismatch")
    return baseline


def validate_minimum_endpoint_control_binding(
    minimum_candidate: Mapping[str, Any], m2_control: Mapping[str, Any],
    *, selected_candidate_id: str | None = None,
    selected_plan: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Bind M2 and the minimum endpoint to one immutable first-stage artifact."""

    candidate = {field: minimum_candidate.get(field) for field in PLAN_IDENTITY_FIELDS}
    control = {field: m2_control.get(field) for field in PLAN_IDENTITY_FIELDS}
    if candidate != control:
        raise M21ProtocolError("minimum endpoint and M2 control plan identity mismatch")
    for field in ("finalized_plan_artifact_sha256", "regular_purchase_sha256", "training_joint_scenario_set_sha256"):
        value = str(candidate.get(field, ""))
        if len(value) != 64:
            raise M21ProtocolError(f"minimum endpoint identity is incomplete: {field}")
        try:
            int(value, 16)
        except ValueError as exc:
            raise M21ProtocolError(f"minimum endpoint identity is not SHA-256: {field}") from exc
    for field in ("reserve_amount", "exact_training_objective"):
        value = float(candidate.get(field, math.nan))
        if not math.isfinite(value) or value < 0.0:
            raise M21ProtocolError(f"minimum endpoint identity has invalid {field}")
    if selected_candidate_id == "minimum_endpoint":
        if selected_plan is None or {
            field: selected_plan.get(field) for field in PLAN_IDENTITY_FIELDS
        } != candidate:
            raise M21ProtocolError("selected minimum endpoint must reuse the M2 control artifact")
    return candidate


def validate_selected_minimum_test_difference(
    *, selected_candidate_id: str, paired_difference: float, tolerance: float,
) -> None:
    values = (float(paired_difference), float(tolerance))
    if not all(math.isfinite(value) for value in values) or values[1] < 0.0:
        raise M21ProtocolError("selected-plan test difference evidence is invalid")
    if selected_candidate_id == "minimum_endpoint" and abs(values[0]) > values[1]:
        raise M21ProtocolError("selected minimum endpoint differs from its M2 control")


def validate_parent_evidence(root: Path) -> dict[str, str]:
    observed: dict[str, str] = {}
    for identity, (relative, expected) in PARENT_AUDITS.items():
        actual = sha256_file(root / relative)
        if actual != expected:
            raise M21ProtocolError(f"reviewed parent evidence mismatch: {identity}")
        observed[identity] = actual
    diagnostic = json.loads((root / PARENT_AUDITS["pr61_diagnostic"][0]).read_text(encoding="utf-8"))
    if diagnostic.get("final_status") != "M2_1_candidate_requires_new_freeze_validation_and_test_sets":
        raise M21ProtocolError("PR #61 does not support an M2.1 design candidate")
    if any(diagnostic.get("stop_boundary", {}).get(field) is not False for field in (
        "M2_1_development_authorized", "M2_1_execution_authorized",
        "algorithm_performance_authorized", "M0_E3_authorized",
    )):
        raise M21ProtocolError("PR #61 stop boundary changed")
    return observed


def m2_1_fingerprints(root: Path, config_path: Path, runner_path: Path) -> dict[str, str]:
    config = load_m2_1_config(config_path)
    scientific = {key: value for key, value in config.items() if key not in LIFECYCLE_FIELDS}
    locked = validate_locked_environment(root)
    return {
        "scientific_config_sha256": _canonical_sha256(scientific),
        "e3_component_sha256": _component_sha256(root, E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(root, FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_path),
        "environment_sha256": environment_sha256(locked),
    }


def validate_design_only_preflight(
    *, root: Path, config_path: Path, runner_path: Path, approval_path: Path,
    authorize_pilot: bool = False, authorize_formal: bool = False,
) -> dict[str, Any]:
    config = load_m2_1_config(config_path)
    validate_parent_evidence(root)
    runner = yaml.safe_load(runner_path.read_text(encoding="utf-8"))
    approval = yaml.safe_load(approval_path.read_text(encoding="utf-8"))
    if runner.get("namespace") != RUNNER_NAMESPACE or runner.get("protocol") != PROTOCOL_ID:
        raise M21ProtocolError("M2.1 runner configuration identity mismatch")
    if runner.get("output_root") != OUTPUT_ROOT:
        raise M21ProtocolError("M2.1 runner output root mismatch")
    limits = runner.get("limits") or {}
    if limits != {
        "solver_call_seconds": 120,
        "training_case_wall_seconds": 900,
        "validation_candidate_wall_seconds": 7200,
        "test_plan_wall_seconds": 7200,
        "threads": 1,
    }:
        raise M21ProtocolError("M2.1 runner limits changed")
    if approval.get("approval_id") != "phase6_m2_1_endpoint_selection_execution_v1_0":
        raise M21ProtocolError("M2.1 approval identity mismatch")
    if approval.get("scientific_protocol") != PROTOCOL_ID or approval.get("runner_namespace") != RUNNER_NAMESPACE:
        raise M21ProtocolError("M2.1 approval targets a different protocol")
    if approval.get("accept_M2_authorization") is not False:
        raise M21ProtocolError("M2 authorization cannot authorize M2.1")
    actual = m2_1_fingerprints(root, config_path, runner_path)
    if approval.get("approved_fingerprints") != actual:
        raise M21ProtocolError("M2.1 approval fingerprint mismatch")
    validate_execution_source(
        root,
        required_tracked_paths=(
            config_path,
            runner_path,
            approval_path,
            root / "src/phase6_m2_1_endpoint_selection.py",
            root / "src/run_phase6_m2_1_endpoint_selection.py",
        ),
    )
    boundaries = config["execution_boundaries"]
    if (
        boundaries["scientific_runner_enabled"] is not True
        or approval.get("status") not in {"frozen_for_pilot_execution", "frozen_for_formal_execution"}
    ):
        raise M21ExecutionNotAuthorized("M2.1 scientific runner is intentionally disabled in this design PR")
    if authorize_pilot and approval.get("pilot_authorized") is not True:
        raise M21ExecutionNotAuthorized("M2.1 pilot is not authorized")
    if authorize_formal and not all(approval.get(field) is True for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
    )):
        raise M21ExecutionNotAuthorized("M2.1 formal execution is not authorized")
    raise M21ExecutionNotAuthorized("no M2.1 execution mode was authorized")

"""Phase 6 M2 disaster-correlated regular-supply disruption extension.

M2 changes only the scenario-dependent delivery of already-paid regular
contracts.  Demand and fulfillment share the frozen M0 demand latent, so a
more severe disaster raises demand and lowers regular fulfillment.  The C0
profile forces fulfillment to one and is an exact M0 control.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, fields, replace
import hashlib
import json
import math
from pathlib import Path
from statistics import fmean
from threading import RLock
from typing import Any, Mapping, Sequence

import yaml
import numpy as np
import pyomo.environ as pyo

from .model_common import build_inventory_model as _build_m0_inventory_model
from .model_data import ProcurementData, ScenarioSeries
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import read_lf_bytes, sha256_lf_text_file
from .phase6_m1 import ReserveIntervalAnalysis, analyze_reserve_interval
from .phase6_protocol import GeneratedPhase6Data, generate_phase6_data
from .recourse_model import RecourseResult


M2_PROTOCOL_ID = "phase6_m2_supply_disruption_v1_0"
M2_RUNNER_NAMESPACE = "phase6_m2_supply_disruption"
M2_OUTPUT_ROOT = "outputs/phase6_m2_supply_disruption_v1"
M2_EXECUTION_READY_STATUS = "frozen_for_development_execution"
M2_LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")

M2_E3_COMPONENT_FILES = (
    ".gitattributes",
    ".gitignore",
    "src/model_data.py",
    "src/model_common.py",
    "src/inventory_model.py",
    "src/recourse_model.py",
    "src/evaluation.py",
    "src/extensive_model.py",
    "src/ccg.py",
    "src/spw_ccg.py",
    "src/phase6_protocol.py",
    "src/phase6_environment.py",
    "src/phase6_io.py",
    "src/phase6_m1.py",
    "src/phase6_m2.py",
    "src/phase6_m2_development.py",
    "src/run_phase6_m2_development.py",
    "src/phase6_m2_status.py",
    "configs/phase6_m2_supply_disruption.yaml",
    "configs/phase6_m2_runner.yaml",
)
M2_FAMILY_COMPONENT_FILES = M2_E3_COMPONENT_FILES + (
    "src/phase6_families.py",
    "src/phase6_family_runner.py",
    "src/phase6_family_worker.py",
)


class M2ProtocolError(ValueError):
    """Raised before scenario generation for an ambiguous M2 protocol."""


@dataclass(frozen=True)
class SupplyDisruptionProfile:
    id: str
    enabled: bool
    loss_scale: float
    recovery_fraction: float


@dataclass(frozen=True)
class DisruptedProcurementData(ProcurementData):
    regular_fulfillment_rate: ScenarioSeries
    m2_demand_latent: ScenarioSeries

    def validate(self) -> None:
        super().validate()
        for scenario in self.scenarios:
            for item in self.items:
                values = self.regular_fulfillment_rate[scenario][item]
                if len(values) != self.periods:
                    raise ValueError("regular fulfillment length must equal periods")
                if any(not 0.0 <= float(v) <= 1.0 for v in values):
                    raise ValueError("regular fulfillment rates must lie in [0, 1]")

    def subset(self, scenarios: tuple[str, ...]) -> "DisruptedProcurementData":
        base = super().subset(scenarios)
        values = {field.name: getattr(base, field.name) for field in fields(ProcurementData)}
        result = DisruptedProcurementData(
            **values,
            regular_fulfillment_rate={s: self.regular_fulfillment_rate[s] for s in scenarios},
            m2_demand_latent={s: self.m2_demand_latent[s] for s in scenarios},
        )
        result.validate()
        return result


@dataclass(frozen=True)
class FulfillmentStatistics:
    arithmetic_mean: float
    demand_weighted_mean: float | None
    minimum: float
    p05: float
    full_interruption_rate: float
    severe_interruption_rate: float
    period_means: tuple[float, ...]
    total_demand_weighted_fulfillment_correlation: float | None
    correlation_status: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "arithmetic_mean": self.arithmetic_mean,
            "demand_weighted_mean": self.demand_weighted_mean,
            "minimum": self.minimum,
            "p05": self.p05,
            "full_interruption_rate": self.full_interruption_rate,
            "severe_interruption_rate": self.severe_interruption_rate,
            "period_means": list(self.period_means),
            "total_demand_weighted_fulfillment_correlation": (
                self.total_demand_weighted_fulfillment_correlation
            ),
            "correlation_status": self.correlation_status,
        }


@dataclass(frozen=True)
class GeneratedM2Data:
    generated: GeneratedPhase6Data
    profile: SupplyDisruptionProfile
    statistics: FulfillmentStatistics
    scenario_identities: Mapping[str, "JointScenarioIdentity"]
    joint_scenario_set_sha256: str

    @property
    def component_set_sha256(self) -> dict[str, str]:
        """Canonical ordered hashes used to audit common random numbers."""
        ordered = [self.scenario_identities[s] for s in self.data.scenarios]
        return {
            field: _sha256_payload([getattr(identity, field) for identity in ordered])
            for field in (
                "latent_draw_sha256",
                "demand_sha256",
                "fulfillment_sha256",
                "emergency_price_sha256",
                "emergency_supply_sha256",
            )
        }

    @property
    def data(self) -> ProcurementData:
        return self.generated.data


@dataclass(frozen=True)
class M2RecourseResult:
    recourse: RecourseResult
    delivered_regular_purchase: dict[str, list[float]]
    undelivered_contract_quantity: dict[str, list[float]]
    joint_scenario_sha256: str

    def as_dict(self) -> dict[str, Any]:
        payload = self.recourse.as_dict()
        payload.update(
            delivered_regular_purchase=self.delivered_regular_purchase,
            undelivered_contract_quantity=self.undelivered_contract_quantity,
            joint_scenario_sha256=self.joint_scenario_sha256,
        )
        return payload


@dataclass(frozen=True)
class JointScenarioIdentity:
    scenario_id: str
    latent_draw_sha256: str
    demand_sha256: str
    fulfillment_sha256: str
    emergency_price_sha256: str
    emergency_supply_sha256: str
    joint_scenario_sha256: str

    def as_dict(self) -> dict[str, str]:
        return {
            "scenario_id": self.scenario_id,
            "latent_draw_sha256": self.latent_draw_sha256,
            "demand_sha256": self.demand_sha256,
            "fulfillment_sha256": self.fulfillment_sha256,
            "emergency_price_sha256": self.emergency_price_sha256,
            "emergency_supply_sha256": self.emergency_supply_sha256,
            "joint_scenario_sha256": self.joint_scenario_sha256,
        }


@dataclass(frozen=True)
class M2AlgorithmEvidence:
    result: Any
    joint_scenario_set_sha256: str
    scenario_identities: Mapping[str, JointScenarioIdentity]

    def __getattr__(self, name: str) -> Any:
        return getattr(self.result, name)

    def as_dict(self) -> dict[str, Any]:
        payload = self.result.as_dict()
        payload["joint_scenario_set_sha256"] = self.joint_scenario_set_sha256
        payload["scenario_identities"] = {
            key: value.as_dict() for key, value in self.scenario_identities.items()
        }
        return payload


def load_m2_config(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise M2ProtocolError("M2 configuration root must be a mapping")
    if payload.get("protocol_id") != M2_PROTOCOL_ID:
        raise M2ProtocolError("unsupported M2 protocol_id")
    if payload.get("runner_namespace") != M2_RUNNER_NAMESPACE:
        raise M2ProtocolError("unexpected M2 runner namespace")
    if payload.get("output_root") != M2_OUTPUT_ROOT:
        raise M2ProtocolError("unexpected M2 output root")
    profiles = payload.get("disruption_profiles")
    if not isinstance(profiles, Mapping) or tuple(profiles) != ("C0", "C1", "C2"):
        raise M2ProtocolError("M2 profiles must be ordered C0, C1, C2")
    for profile_id in profiles:
        resolve_supply_disruption_profile(payload, profile_id)
    development = payload.get("development_preregistration")
    if not isinstance(development, Mapping):
        raise M2ProtocolError("development_preregistration must be a mapping")
    if tuple(development.get("seeds", ())) != (2026081201, 2026081202, 2026081203):
        raise M2ProtocolError("unexpected M2 development seeds")
    if tuple(float(v) for v in development.get("beta", ())) != (0.9, 1.1, 1.3):
        raise M2ProtocolError("unexpected M2 budget factors")
    if tuple(development.get("profiles", ())) != ("C0", "C1", "C2"):
        raise M2ProtocolError("unexpected M2 disruption profiles")
    if int(development.get("configuration_count", -1)) != 27:
        raise M2ProtocolError("M2 development grid must contain 27 cases")
    if development.get("execution_allowed_in_this_revision") is not True:
        raise M2ProtocolError("M2 development execution is not enabled by this revision")
    return payload


def resolve_supply_disruption_profile(
    config: Mapping[str, Any], profile_id: str
) -> SupplyDisruptionProfile:
    profiles = config.get("disruption_profiles")
    if not isinstance(profiles, Mapping) or profile_id not in profiles:
        raise M2ProtocolError(f"unknown disruption profile: {profile_id}")
    raw = profiles[profile_id]
    if not isinstance(raw, Mapping):
        raise M2ProtocolError("disruption profile must be a mapping")
    expected = {"enabled", "loss_scale", "recovery_fraction"}
    if set(raw) != expected:
        raise M2ProtocolError(f"{profile_id} accepts only {sorted(expected)}")
    enabled = raw["enabled"]
    if not isinstance(enabled, bool):
        raise M2ProtocolError("enabled must be boolean")
    loss_scale = float(raw["loss_scale"])
    recovery_fraction = float(raw["recovery_fraction"])
    if not math.isfinite(loss_scale) or loss_scale < 0.0:
        raise M2ProtocolError("loss_scale must be finite and nonnegative")
    if not math.isfinite(recovery_fraction) or not 0.0 <= recovery_fraction <= 1.0:
        raise M2ProtocolError("recovery_fraction must lie in [0, 1]")
    if not enabled and (loss_scale != 0.0 or recovery_fraction != 0.0):
        raise M2ProtocolError("disabled profile must have zero loss and recovery")
    if enabled and loss_scale <= 0.0:
        raise M2ProtocolError("enabled profile requires positive loss_scale")
    return SupplyDisruptionProfile(
        id=profile_id,
        enabled=enabled,
        loss_scale=loss_scale,
        recovery_fraction=recovery_fraction,
    )


def _normal_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(value / math.sqrt(2.0)))


def _fulfillment_rates(
    generated: GeneratedPhase6Data,
    profile: SupplyDisruptionProfile,
    demand_latent: ScenarioSeries,
) -> dict[str, dict[str, tuple[float, ...]]]:
    data = generated.data
    if not profile.enabled:
        return {
            scenario: {
                item: tuple(1.0 for _ in range(data.periods))
                for item in data.items
            }
            for scenario in data.scenarios
        }
    denominator = max(1, data.periods - 1)
    result: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario in data.scenarios:
        result[scenario] = {}
        for item in data.items:
            values = []
            for t in range(data.periods):
                # The same latent that increases demand also increases contract loss.
                severity = _normal_cdf(
                    float(demand_latent[scenario][item][t])
                )
                recovery = 1.0 - profile.recovery_fraction * t / denominator
                alpha = 1.0 - profile.loss_scale * severity * recovery
                values.append(min(1.0, max(0.0, alpha)))
            result[scenario][item] = tuple(values)
    return result


def fulfillment_statistics(data: DisruptedProcurementData) -> FulfillmentStatistics:
    rates = data.regular_fulfillment_rate
    flat = [
        float(rates[s][i][t])
        for s in data.scenarios for i in data.items for t in range(data.periods)
    ]
    demand_weights = [
        float(data.demand[s][i][t])
        for s in data.scenarios for i in data.items for t in range(data.periods)
    ]
    weight_sum = sum(demand_weights)
    weighted = (
        sum(a * w for a, w in zip(flat, demand_weights)) / weight_sum
        if weight_sum > 0.0 else None
    )
    ordered = sorted(flat)
    position = 0.05 * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    p05 = ordered[lower] + (position - lower) * (ordered[upper] - ordered[lower])
    period_means = tuple(
        fmean(float(rates[s][i][t]) for s in data.scenarios for i in data.items)
        for t in range(data.periods)
    )
    totals: list[float] = []
    scenario_alpha: list[float] = []
    zero_total_demand = False
    for s in data.scenarios:
        weights = [data.demand[s][i][t] for i in data.items for t in range(data.periods)]
        values = [rates[s][i][t] for i in data.items for t in range(data.periods)]
        total = float(sum(weights))
        if total <= 0.0:
            zero_total_demand = True
            continue
        totals.append(total)
        scenario_alpha.append(sum(w * a for w, a in zip(weights, values)) / total)
    if zero_total_demand:
        correlation = None
        correlation_status = "zero_total_demand"
    elif len(totals) < 2:
        correlation = None
        correlation_status = "insufficient_variation"
    elif max(totals) - min(totals) <= 1.0e-15:
        correlation = None
        correlation_status = "constant_demand"
    elif max(scenario_alpha) - min(scenario_alpha) <= 1.0e-15:
        correlation = None
        correlation_status = "constant_fulfillment"
    else:
        mean_x, mean_y = fmean(totals), fmean(scenario_alpha)
        covariance = sum((x - mean_x) * (y - mean_y) for x, y in zip(totals, scenario_alpha))
        scale = math.sqrt(sum((x - mean_x) ** 2 for x in totals) * sum((y - mean_y) ** 2 for y in scenario_alpha))
        correlation = covariance / scale if scale > 0.0 else None
        correlation_status = "defined" if correlation is not None else "insufficient_variation"
    return FulfillmentStatistics(
        arithmetic_mean=fmean(flat), demand_weighted_mean=weighted,
        minimum=min(flat), p05=p05,
        full_interruption_rate=sum(v <= 0.0 for v in flat) / len(flat),
        severe_interruption_rate=sum(v < 0.5 for v in flat) / len(flat),
        period_means=period_means,
        total_demand_weighted_fulfillment_correlation=correlation,
        correlation_status=correlation_status,
    )


def apply_regular_supply_disruption(
    generated: GeneratedPhase6Data,
    profile: SupplyDisruptionProfile,
    *,
    demand_latent: ScenarioSeries,
) -> GeneratedM2Data:
    rates = _fulfillment_rates(generated, profile, demand_latent)
    base_fields = {
        field.name: getattr(generated.data, field.name)
        for field in fields(ProcurementData)
    }
    data = DisruptedProcurementData(
        **base_fields, regular_fulfillment_rate=rates, m2_demand_latent=demand_latent
    )
    data.validate()
    replaced = replace(generated, data=data)
    identities = joint_scenario_identities(data, demand_latent)
    set_hash = _sha256_payload(
        [identities[scenario].as_dict() for scenario in data.scenarios]
    )
    return GeneratedM2Data(
        replaced, profile, fulfillment_statistics(data), identities, set_hash
    )


def _sha256_payload(payload: Any) -> str:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def joint_scenario_identities(
    data: DisruptedProcurementData, demand_latent: ScenarioSeries
) -> dict[str, JointScenarioIdentity]:
    result: dict[str, JointScenarioIdentity] = {}
    for scenario in data.scenarios:
        latent_hash = _sha256_payload(demand_latent[scenario])
        demand_hash = _sha256_payload(data.demand[scenario])
        fulfillment_hash = _sha256_payload(data.regular_fulfillment_rate[scenario])
        emergency_price_hash = _sha256_payload(data.emergency_price[scenario])
        emergency_supply_hash = _sha256_payload(data.emergency_supply[scenario])
        components = {
            "scenario_id": scenario,
            "latent_draw_sha256": latent_hash,
            "demand_sha256": demand_hash,
            "fulfillment_sha256": fulfillment_hash,
            "emergency_price_sha256": emergency_price_hash,
            "emergency_supply_sha256": emergency_supply_hash,
        }
        result[scenario] = JointScenarioIdentity(
            **components, joint_scenario_sha256=_sha256_payload(components)
        )
    return result


def generate_m2_data(
    matrix: Mapping[str, Any], *, matrix_path: str | Path, tier_id: str,
    seed: int, budget: float, m2_config: Mapping[str, Any], profile_id: str,
) -> GeneratedM2Data:
    profile = resolve_supply_disruption_profile(m2_config, profile_id)
    generated = generate_phase6_data(
        matrix, matrix_path=matrix_path, tier_id=tier_id, seed=seed, budget=budget
    )
    latent = reconstruct_frozen_demand_latent(matrix, generated)
    return apply_regular_supply_disruption(
        generated, profile, demand_latent=latent
    )


def reconstruct_frozen_demand_latent(
    matrix: Mapping[str, Any], generated: GeneratedPhase6Data
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Replay only the frozen RNG schedule to recover the exact demand latent."""
    data = generated.data
    if generated.tier.id == "D0":
        raise M2ProtocolError("M2 controlled disruption does not support legacy D0")
    loadings = matrix["generator_protocol"]["latent_factor_model"][
        "demand_variance_loadings"
    ]
    cc = math.sqrt(float(loadings["common_disaster"])); ci = math.sqrt(float(loadings["item"]))
    ct = math.sqrt(float(loadings["period"])); ce = math.sqrt(float(loadings["idiosyncratic"]))
    rng = np.random.Generator(np.random.PCG64DXSM(generated.seed))
    result: dict[str, dict[str, tuple[float, ...]]] = {}
    for scenario in data.scenarios:
        common = float(rng.standard_normal(dtype=np.float64))
        item_factors = {item: float(rng.standard_normal(dtype=np.float64)) for item in data.items}
        period_factors = tuple(float(rng.standard_normal(dtype=np.float64)) for _ in range(data.periods))
        result[scenario] = {}
        for item in data.items:
            values = []
            for t in range(data.periods):
                demand_residual = float(rng.standard_normal(dtype=np.float64))
                # Keep the two subsequent draws in the M0 schedule.
                rng.standard_normal(dtype=np.float64)
                rng.standard_normal(dtype=np.float64)
                values.append(cc * common + ci * item_factors[item] + ct * period_factors[t] + ce * demand_residual)
            result[scenario][item] = tuple(values)
    return result


def reconstruct_demand_from_latent(
    matrix: Mapping[str, Any], generated: GeneratedPhase6Data,
    demand_latent: ScenarioSeries,
) -> dict[str, dict[str, tuple[float, ...]]]:
    """Reapply the frozen lognormal demand transform for replay auditing."""
    demand_cv = float(matrix["controlled_synthetic_baseline"]["demand_cv"])
    log_sigma = math.sqrt(math.log1p(demand_cv**2))
    return {
        scenario: {
            item: tuple(
                float(generated.theoretical_mean_demand[item][t])
                * math.exp(
                    log_sigma * float(demand_latent[scenario][item][t])
                    - 0.5 * log_sigma**2
                )
                for t in range(generated.data.periods)
            )
            for item in generated.data.items
        }
        for scenario in generated.data.scenarios
    }


def build_m2_inventory_model(data: ProcurementData, **kwargs: Any) -> pyo.ConcreteModel:
    if not isinstance(data, DisruptedProcurementData):
        raise TypeError("M2 builder requires DisruptedProcurementData")
    model = _build_m0_inventory_model(data, **kwargs)
    model.del_component(model.available_balance)
    model.delivered_regular_purchase = pyo.Expression(
        model.S, model.K, model.T,
        rule=lambda m, s, i, t: data.regular_fulfillment_rate[str(s)][str(i)][int(t)] * m.y[i, t],
    )
    model.undelivered_contract_quantity = pyo.Expression(
        model.S, model.K, model.T,
        rule=lambda m, s, i, t: (1.0 - data.regular_fulfillment_rate[str(s)][str(i)][int(t)]) * m.y[i, t],
    )
    def available_rule(m, scenario, item, t, age):
        if age == 0:
            initial = data.initial_inventory[item][0] if t == 0 else 0.0
            return m.available[scenario, item, t, age] == m.delivered_regular_purchase[scenario, item, t] + m.q[scenario, item, t] + initial
        if t == 0:
            return m.available[scenario, item, t, age] == data.initial_inventory[item][age]
        return m.available[scenario, item, t, age] == m.inventory[scenario, item, t - 1, age - 1]
    model.available_balance = pyo.Constraint(model.S, model.KTA, rule=available_rule)
    return model


@contextmanager
def m2_model_context():
    """Route all shared solvers through the isolated M2 builder."""
    from . import ccg, extensive_model, phase6_m1, recourse_model
    with _M2_MODEL_CONTEXT_LOCK:
        old = {
            "extensive_inventory": extensive_model.build_inventory_model,
            "recourse_inventory": recourse_model.build_inventory_model,
            "ccg_restricted": ccg.build_restricted_master,
            "m1_restricted": phase6_m1.build_restricted_master,
            "m1_evaluate": phase6_m1.evaluate_first_stage,
        }

        def m2_restricted(data: ProcurementData, scenario_names: Sequence[str]):
            return build_m2_inventory_model(
                data, scenario_names=tuple(scenario_names),
                model_name="M2RestrictedMaster", reserve_policy="endogenous",
                objective_kind="robust",
            )

        def m2_evaluate(*args: Any, **kwargs: Any):
            from .evaluation import evaluate_first_stage
            return evaluate_first_stage(*args, **kwargs)

        extensive_model.build_inventory_model = build_m2_inventory_model
        recourse_model.build_inventory_model = build_m2_inventory_model
        ccg.build_restricted_master = m2_restricted
        phase6_m1.build_restricted_master = m2_restricted
        phase6_m1.evaluate_first_stage = m2_evaluate
        try:
            yield
        finally:
            extensive_model.build_inventory_model = old["extensive_inventory"]
            recourse_model.build_inventory_model = old["recourse_inventory"]
            ccg.build_restricted_master = old["ccg_restricted"]
            phase6_m1.build_restricted_master = old["m1_restricted"]
            phase6_m1.evaluate_first_stage = old["m1_evaluate"]


def _algorithm_evidence(data: DisruptedProcurementData, result: Any) -> M2AlgorithmEvidence:
    identities = joint_scenario_identities(data, data.m2_demand_latent)
    set_hash = _sha256_payload([identities[s].as_dict() for s in data.scenarios])
    return M2AlgorithmEvidence(result, set_hash, identities)


def analyze_m2_reserve_interval(
    data: ProcurementData, **kwargs: Any
) -> ReserveIntervalAnalysis:
    """Identify the complete-extensive tolerance-optimal reserve face."""
    with m2_model_context():
        return analyze_reserve_interval(data, **kwargs)


def solve_m2_endogenous_extensive(data: DisruptedProcurementData, **kwargs: Any):
    from .extensive_model import solve_endogenous_extensive
    with m2_model_context():
        result = solve_endogenous_extensive(data, **kwargs)
    return _algorithm_evidence(data, result)


def solve_m2_fixed_reserve(
    data: DisruptedProcurementData,
    reserve_ratio: float,
    **kwargs: Any,
):
    """Re-optimize regular contracts for one fixed total-reserve ratio."""
    from .evaluation import evaluate_first_stage
    from .extensive_model import ExtensiveSolution, solve_master

    consistency_tolerance = float(kwargs.pop("consistency_tolerance", 1.0e-6))
    with m2_model_context():
        model = build_m2_inventory_model(
            data,
            scenario_names=data.scenarios,
            model_name=f"M2FixedReserve[rho={reserve_ratio:.4f}]",
            reserve_policy="fixed_ratio",
            fixed_reserve_ratio=reserve_ratio,
            objective_kind="robust",
        )
        master = solve_master(model, **kwargs)
        if master.status != "optimal":
            result = ExtensiveSolution(
                status=f"master_{master.status}", master=master,
                evaluation=None, consistency_difference=None,
                tolerance=consistency_tolerance,
            )
        else:
            evaluation = evaluate_first_stage(
                data, master.regular_purchase, float(master.reserve), **kwargs
            )
            if evaluation.status != "optimal" or evaluation.robust_objective is None:
                result = ExtensiveSolution(
                    status=evaluation.status, master=master,
                    evaluation=evaluation, consistency_difference=None,
                    tolerance=consistency_tolerance,
                )
            else:
                difference = abs(float(master.objective) - evaluation.robust_objective)
                result = ExtensiveSolution(
                    status=("optimal" if difference <= consistency_tolerance
                            else "inconsistent_exact_recourse"),
                    master=master, evaluation=evaluation,
                    consistency_difference=difference,
                    tolerance=consistency_tolerance,
                )
    return _algorithm_evidence(data, result)


def run_m2_standard_ccg(data: DisruptedProcurementData, **kwargs: Any):
    from .ccg import run_standard_ccg
    with m2_model_context():
        result = run_standard_ccg(data, **kwargs)
    return _algorithm_evidence(data, result)


def run_m2_spw_ccg_budget_sequence(data: DisruptedProcurementData, budgets: Sequence[float], **kwargs: Any):
    from .spw_ccg import run_spw_ccg_budget_sequence
    with m2_model_context():
        result = run_spw_ccg_budget_sequence(data, budgets, **kwargs)
    return _algorithm_evidence(data, result)


def solve_m2_recourse(data: DisruptedProcurementData, scenario: str, regular_purchase: Mapping[str, Sequence[float]], reserve: float, **kwargs: Any) -> M2RecourseResult:
    from .recourse_model import solve_recourse_model
    with m2_model_context():
        model = build_m2_inventory_model(
            data, scenario_names=(scenario,), model_name=f"M2Recourse[{scenario}]",
            reserve_policy="fixed_first_stage", regular_purchase=regular_purchase,
            reserve=reserve, objective_kind="recourse",
        )
        result = solve_recourse_model(model, **kwargs)
    if result.status != "optimal":
        identity = joint_scenario_identities(data, data.m2_demand_latent)[scenario]
        return M2RecourseResult(result, {}, {}, identity.joint_scenario_sha256)
    delivered = {
        item: [float(pyo.value(model.delivered_regular_purchase[scenario, item, t])) for t in range(data.periods)]
        for item in data.items
    }
    undelivered = {
        item: [float(pyo.value(model.undelivered_contract_quantity[scenario, item, t])) for t in range(data.periods)]
        for item in data.items
    }
    identity = joint_scenario_identities(data, data.m2_demand_latent)[scenario]
    return M2RecourseResult(
        result, delivered, undelivered, identity.joint_scenario_sha256
    )


def contract_flow(
    data: ProcurementData, regular_purchase: Mapping[str, Sequence[float]],
    scenario: str, item: str, t: int,
) -> tuple[float, float]:
    alpha = float(getattr(data, "regular_fulfillment_rate")[scenario][item][t])
    contracted = float(regular_purchase[item][t])
    return alpha * contracted, (1.0 - alpha) * contracted


def m2_scientific_config_sha256(config: Mapping[str, Any]) -> str:
    scientific = {k: v for k, v in config.items() if k not in M2_LIFECYCLE_FIELDS}
    encoded = json.dumps(scientific, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _component_sha256(project_root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        path = project_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"M2 component file is missing: {path}")
        digest.update(relative.encode("utf-8")); digest.update(b"\0")
        digest.update(read_lf_bytes(path)); digest.update(b"\0")
    return digest.hexdigest()


def m2_fingerprints(*, project_root: Path, config_path: Path, runner_config_path: Path) -> dict[str, str]:
    config = load_m2_config(config_path)
    locked = validate_locked_environment(project_root)
    return {
        "scientific_config_sha256": m2_scientific_config_sha256(config),
        "e3_component_sha256": _component_sha256(project_root, M2_E3_COMPONENT_FILES),
        "family_component_sha256": _component_sha256(project_root, M2_FAMILY_COMPONENT_FILES),
        "runner_config_sha256": sha256_lf_text_file(runner_config_path),
        "environment_sha256": environment_sha256(locked),
    }


_M2_MODEL_CONTEXT_LOCK = RLock()

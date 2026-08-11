"""Phase 6 M1 regular-procurement-cap extension.

M1 preserves the M0 budget and recourse structure.  Its only scientific
change is an optional upper bound on pre-disaster regular procurement.  This
module also separates mechanically forced reserve from reserve required by
every tolerance-optimal solution.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields, replace
import hashlib
import json
import math
from math import inf, isfinite
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Mapping, Sequence

import pyomo.environ as pyo
import yaml

from .ccg import CCGIteration, CCGResult, select_initial_scenarios
from .evaluation import EvaluationResult, evaluate_first_stage
from .extensive_model import (
    ExtensiveSolution,
    build_restricted_master,
    solve_master,
)
from .model_common import extract_regular_purchase, solve_with_status
from .model_data import ProcurementData, SeriesByItem
from .phase6_environment import environment_sha256, validate_locked_environment
from .phase6_io import read_lf_bytes, sha256_lf_text_file
from .phase6_protocol import GeneratedPhase6Data, generate_phase6_data
from .spw_ccg import (
    BudgetComparison,
    BudgetFailure,
    SPWCCGResult,
    ScenarioPoolState,
    build_transferred_state,
    build_warm_initial_scenarios,
)


M1_PROTOCOL_ID = "phase6_m1_procurement_cap_v1_0"
M1_RUNNER_NAMESPACE = "phase6_m1_procurement_cap"
M1_OUTPUT_ROOT = "outputs/phase6_m1_procurement_cap_v1"
M1_EXECUTION_READY_STATUS = "frozen_for_development_execution"
M1_LIFECYCLE_FIELDS = ("status", "initial_draft_on", "revised_on")

M1_E3_COMPONENT_FILES = (
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
    "src/run_phase6_m1.py",
    "configs/phase6_m1_procurement_cap.yaml",
    "configs/phase6_m1_runner.yaml",
)
M1_FAMILY_COMPONENT_FILES = M1_E3_COMPONENT_FILES + (
    "src/phase6_families.py",
    "src/phase6_family_runner.py",
    "src/phase6_family_worker.py",
)


class M1ProtocolError(ValueError):
    """Raised when an M1 configuration is ambiguous or unsafe."""


@dataclass(frozen=True)
class RegularProcurementCap:
    """Resolved optional regular-procurement cap protocol."""

    enabled: bool
    kappa: float | None


@dataclass(frozen=True)
class CappedProcurementData(ProcurementData):
    """Procurement data carrying absolute regular-purchase capacities."""

    regular_procurement_capacity: SeriesByItem
    regular_procurement_cap_kappa: float

    def validate(self) -> None:
        super().validate()
        if not math.isfinite(self.regular_procurement_cap_kappa):
            raise ValueError("regular procurement kappa must be finite")
        if self.regular_procurement_cap_kappa <= 0.0:
            raise ValueError("regular procurement kappa must be positive")
        if set(self.regular_procurement_capacity) != set(self.items):
            raise ValueError("regular procurement capacity must cover every item")
        for item in self.items:
            values = self.regular_procurement_capacity[item]
            if len(values) != self.periods:
                raise ValueError(
                    "regular procurement capacity length must equal periods"
                )
            if any(
                not math.isfinite(float(value)) or float(value) < 0.0
                for value in values
            ):
                raise ValueError(
                    "regular procurement capacities must be finite and nonnegative"
                )


@dataclass(frozen=True)
class MinimumFeasibleReserve:
    status: str
    reserve: float | None
    reserve_ratio: float | None
    closed_form_reserve: float | None
    closed_form_difference: float | None
    regular_purchase: dict[str, list[float]]
    solver: str
    runtime_seconds: float
    termination_condition: str
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReserveFacePoint:
    direction: str
    status: str
    reserve: float | None
    reserve_ratio: float | None
    regular_purchase: dict[str, list[float]]
    exact_objective: float | None
    evaluation: EvaluationResult | None
    solver: str
    runtime_seconds: float
    termination_condition: str
    message: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "status": self.status,
            "reserve": self.reserve,
            "reserve_ratio": self.reserve_ratio,
            "regular_purchase": self.regular_purchase,
            "exact_objective": self.exact_objective,
            "evaluation": (
                self.evaluation.as_dict() if self.evaluation is not None else None
            ),
            "solver": self.solver,
            "runtime_seconds": self.runtime_seconds,
            "termination_condition": self.termination_condition,
            "message": self.message,
        }


@dataclass(frozen=True)
class ReserveIntervalAnalysis:
    status: str
    optimum: ExtensiveSolution
    minimum_feasible: MinimumFeasibleReserve
    objective_tolerance: float
    minimum_tolerance_optimal: ReserveFacePoint | None
    maximum_tolerance_optimal: ReserveFacePoint | None
    robust_discretionary_reserve: float | None
    robust_discretionary_reserve_ratio: float | None
    numerical_activation: bool | None
    substantive_activation: bool | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "optimum": self.optimum.as_dict(),
            "minimum_feasible": self.minimum_feasible.as_dict(),
            "objective_tolerance": self.objective_tolerance,
            "minimum_tolerance_optimal": (
                self.minimum_tolerance_optimal.as_dict()
                if self.minimum_tolerance_optimal is not None
                else None
            ),
            "maximum_tolerance_optimal": (
                self.maximum_tolerance_optimal.as_dict()
                if self.maximum_tolerance_optimal is not None
                else None
            ),
            "robust_discretionary_reserve": self.robust_discretionary_reserve,
            "robust_discretionary_reserve_ratio": (
                self.robust_discretionary_reserve_ratio
            ),
            "numerical_activation": self.numerical_activation,
            "substantive_activation": self.substantive_activation,
        }


def load_m1_config(path: str | Path) -> dict[str, Any]:
    """Load and validate the design-only M1 protocol."""

    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise M1ProtocolError("M1 configuration root must be a mapping")
    if payload.get("protocol_id") != M1_PROTOCOL_ID:
        raise M1ProtocolError("unsupported M1 protocol_id")
    if payload.get("runner_namespace") != M1_RUNNER_NAMESPACE:
        raise M1ProtocolError("unexpected M1 runner namespace")
    if payload.get("output_root") != M1_OUTPUT_ROOT:
        raise M1ProtocolError("unexpected M1 output root")
    resolve_regular_procurement_cap(payload.get("regular_procurement_cap"))
    development = payload.get("development_preregistration")
    if not isinstance(development, dict):
        raise M1ProtocolError("development_preregistration must be a mapping")
    seeds = tuple(int(value) for value in development.get("seeds", ()))
    betas = tuple(float(value) for value in development.get("beta", ()))
    kappas = tuple(development.get("kappa", ()))
    if seeds != (2026081101, 2026081102, 2026081103):
        raise M1ProtocolError("M1 development seeds do not match preregistration")
    if betas != (0.9, 1.1, 1.3):
        raise M1ProtocolError("M1 beta grid does not match preregistration")
    if kappas != (None, 1.5, 1.3, 1.2, 1.1, 1.0, 0.8):
        raise M1ProtocolError("M1 kappa grid does not match preregistration")
    if int(development.get("configuration_count", -1)) != 63:
        raise M1ProtocolError("M1 development grid must contain 63 configurations")
    return payload


def resolve_regular_procurement_cap(
    raw: Mapping[str, Any] | Any,
) -> RegularProcurementCap:
    """Resolve the cap before any data or scenario generation occurs."""

    if not isinstance(raw, Mapping):
        raise M1ProtocolError("regular_procurement_cap must be a mapping")
    if set(raw) != {"enabled", "kappa"}:
        raise M1ProtocolError(
            "regular_procurement_cap accepts only enabled and kappa"
        )
    enabled = raw["enabled"]
    if not isinstance(enabled, bool):
        raise M1ProtocolError("regular_procurement_cap.enabled must be boolean")
    kappa = raw["kappa"]
    if not enabled:
        if kappa is not None:
            raise M1ProtocolError("disabled cap requires kappa: null")
        return RegularProcurementCap(enabled=False, kappa=None)
    if isinstance(kappa, bool) or kappa is None:
        raise M1ProtocolError("enabled cap requires a finite positive kappa")
    value = float(kappa)
    if not math.isfinite(value) or value <= 0.0:
        raise M1ProtocolError("enabled cap requires a finite positive kappa")
    return RegularProcurementCap(enabled=True, kappa=value)


def apply_regular_procurement_cap(
    generated: GeneratedPhase6Data,
    cap: RegularProcurementCap,
) -> ProcurementData:
    """Return M0 data unchanged or attach theoretical-demand-based capacities."""

    if not cap.enabled:
        return generated.data
    if cap.kappa is None:
        raise AssertionError("enabled cap is missing kappa")
    base_fields = {
        field.name: getattr(generated.data, field.name)
        for field in fields(ProcurementData)
    }
    capacity = {
        item: tuple(
            cap.kappa * float(value)
            for value in generated.theoretical_mean_demand[item]
        )
        for item in generated.data.items
    }
    result = CappedProcurementData(
        **base_fields,
        regular_procurement_capacity=capacity,
        regular_procurement_cap_kappa=cap.kappa,
    )
    result.validate()
    return result


def generate_m1_data(
    matrix: Mapping[str, Any],
    *,
    matrix_path: str | Path,
    tier_id: str,
    seed: int,
    budget: float,
    cap_config: Mapping[str, Any],
) -> GeneratedPhase6Data:
    """Validate M1 inputs first, then call the existing deterministic generator."""

    cap = resolve_regular_procurement_cap(cap_config)
    generated = generate_phase6_data(
        matrix,
        matrix_path=matrix_path,
        tier_id=tier_id,
        seed=seed,
        budget=budget,
    )
    return replace(generated, data=apply_regular_procurement_cap(generated, cap))


def regular_procurement_capacity(
    data: ProcurementData,
) -> SeriesByItem | None:
    """Return absolute M1 capacities, or ``None`` for the M0 control."""

    capacity = getattr(data, "regular_procurement_capacity", None)
    return capacity


def add_regular_procurement_cap(
    model: pyo.ConcreteModel,
    data: ProcurementData,
) -> pyo.ConcreteModel:
    """Attach M1 bounds to a freshly built M0 master without mutating M0 code."""

    capacity = regular_procurement_capacity(data)
    if capacity is None:
        return model
    if hasattr(model, "regular_procurement_cap"):
        raise RuntimeError("regular procurement cap is already attached")
    model.regular_procurement_cap = pyo.Constraint(
        model.K,
        model.T,
        rule=lambda m, item, t: m.y[item, t] <= capacity[item][t],
    )
    return model


def build_m1_restricted_master(
    data: ProcurementData,
    scenario_names: Sequence[str],
) -> pyo.ConcreteModel:
    """Reuse M0 inventory equations and add only the optional M1 bound."""

    return add_regular_procurement_cap(
        build_restricted_master(data, scenario_names),
        data,
    )


def build_m1_endogenous_extensive_model(
    data: ProcurementData,
) -> pyo.ConcreteModel:
    model = build_m1_restricted_master(data, data.scenarios)
    model._model_name = "M1EndogenousReserveExtensiveModel"
    return model


def solve_m1_endogenous_extensive(
    data: ProcurementData,
    *,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
    consistency_tolerance: float = 1.0e-6,
    tee: bool = False,
) -> ExtensiveSolution:
    """Solve the complete M1 extensive model and independently re-evaluate it."""

    solver_preference = tuple(solver_preference)
    if not solver_preference:
        raise ValueError("solver_preference must not be empty")
    master = solve_master(
        build_m1_endogenous_extensive_model(data),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        tee=tee,
    )
    if master.status != "optimal":
        return ExtensiveSolution(
            status=f"master_{master.status}",
            master=master,
            evaluation=None,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    evaluation = evaluate_first_stage(
        data,
        master.regular_purchase,
        float(master.reserve),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        tee=tee,
    )
    if evaluation.status != "optimal" or evaluation.robust_objective is None:
        return ExtensiveSolution(
            status=evaluation.status,
            master=master,
            evaluation=evaluation,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    difference = abs(float(master.objective) - evaluation.robust_objective)
    return ExtensiveSolution(
        status=(
            "optimal"
            if difference <= consistency_tolerance
            else "inconsistent_exact_recourse"
        ),
        master=master,
        evaluation=evaluation,
        consistency_difference=difference,
        tolerance=consistency_tolerance,
    )


def closed_form_minimum_reserve(data: ProcurementData) -> float:
    """Return the mechanical reserve lower bound for this first-stage system."""

    capacity = regular_procurement_capacity(data)
    if capacity is None:
        can_spend = any(
            float(data.regular_price[item][t]) > 0.0
            for item in data.items
            for t in range(data.periods)
        )
        return 0.0 if can_spend else float(data.budget)
    maximum_regular_spend = sum(
        float(data.regular_price[item][t]) * float(capacity[item][t])
        for item in data.items
        for t in range(data.periods)
    )
    return max(0.0, float(data.budget) - maximum_regular_spend)


def build_minimum_feasible_reserve_model(
    data: ProcurementData,
) -> pyo.ConcreteModel:
    """Build the first-stage LP defining the exact mechanical reserve floor."""

    data.validate()
    model = pyo.ConcreteModel(name="M1MinimumFeasibleReserve")
    model.K = pyo.Set(initialize=data.items, ordered=True)
    model.T = pyo.RangeSet(0, data.periods - 1)
    model.y = pyo.Var(model.K, model.T, domain=pyo.NonNegativeReals)
    model.R = pyo.Var(domain=pyo.NonNegativeReals)
    model.regular_cost = pyo.Expression(
        expr=sum(
            data.regular_price[item][t] * model.y[item, t]
            for item in data.items
            for t in range(data.periods)
        )
    )
    model.budget_equality = pyo.Constraint(
        expr=model.regular_cost + model.R == data.budget
    )
    capacity = regular_procurement_capacity(data)
    if capacity is not None:
        model.regular_procurement_cap = pyo.Constraint(
            model.K,
            model.T,
            rule=lambda m, item, t: m.y[item, t] <= capacity[item][t],
        )
    model.objective = pyo.Objective(expr=model.R, sense=pyo.minimize)
    model._procurement_data = data
    return model


def solve_minimum_feasible_reserve(
    data: ProcurementData,
    *,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
) -> MinimumFeasibleReserve:
    """Solve the exact first-stage floor and check the applicable closed form."""

    model = build_minimum_feasible_reserve_model(data)
    record = solve_with_status(
        model,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    closed_form = closed_form_minimum_reserve(data)
    if record.status != "optimal":
        return MinimumFeasibleReserve(
            status=record.status,
            reserve=None,
            reserve_ratio=None,
            closed_form_reserve=closed_form,
            closed_form_difference=None,
            regular_purchase={},
            solver=record.solver,
            runtime_seconds=record.runtime_seconds,
            termination_condition=record.termination_condition,
            message=record.message,
        )
    reserve = float(pyo.value(model.R))
    return MinimumFeasibleReserve(
        status="optimal",
        reserve=reserve,
        reserve_ratio=reserve / data.budget if data.budget > 0.0 else 0.0,
        closed_form_reserve=closed_form,
        closed_form_difference=abs(reserve - closed_form),
        regular_purchase=extract_regular_purchase(model, data),
        solver=record.solver,
        runtime_seconds=record.runtime_seconds,
        termination_condition=record.termination_condition,
        message=record.message,
    )


def objective_tolerance(
    objective: float,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
) -> float:
    if absolute_tolerance < 0.0 or relative_tolerance < 0.0:
        raise ValueError("objective tolerances must be nonnegative")
    return float(absolute_tolerance) + float(relative_tolerance) * max(
        1.0, abs(float(objective))
    )


def _solve_reserve_face_point(
    data: ProcurementData,
    *,
    master_optimum: float,
    exact_optimum: float,
    tolerance: float,
    direction: str,
    solver_preference: Iterable[str],
    time_limit_seconds: float,
    solver_threads: int | None,
    feasibility_tolerance: float | None,
    optimality_tolerance: float | None,
) -> ReserveFacePoint:
    if direction not in {"min", "max"}:
        raise ValueError("direction must be min or max")
    model = build_m1_endogenous_extensive_model(data)
    original_objective = model.objective.expr
    model.objective.deactivate()
    model.tolerance_optimal_cap = pyo.Constraint(
        expr=original_objective <= master_optimum + tolerance
    )
    model.reserve_face_objective = pyo.Objective(
        expr=model.R,
        sense=pyo.minimize if direction == "min" else pyo.maximize,
    )
    record = solve_with_status(
        model,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    if record.status != "optimal":
        return ReserveFacePoint(
            direction=direction,
            status=record.status,
            reserve=None,
            reserve_ratio=None,
            regular_purchase={},
            exact_objective=None,
            evaluation=None,
            solver=record.solver,
            runtime_seconds=record.runtime_seconds,
            termination_condition=record.termination_condition,
            message=record.message,
        )
    reserve = float(pyo.value(model.R))
    purchase = extract_regular_purchase(model, data)
    evaluation = evaluate_first_stage(
        data,
        purchase,
        reserve,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    exact = evaluation.robust_objective
    status = evaluation.status
    if (
        status == "optimal"
        and exact is not None
        and float(exact) > exact_optimum + tolerance + 1.0e-7
    ):
        status = "outside_tolerance_optimal_set_after_exact_recourse"
    return ReserveFacePoint(
        direction=direction,
        status=status,
        reserve=reserve,
        reserve_ratio=reserve / data.budget if data.budget > 0.0 else 0.0,
        regular_purchase=purchase,
        exact_objective=float(exact) if exact is not None else None,
        evaluation=evaluation,
        solver=record.solver,
        runtime_seconds=record.runtime_seconds,
        termination_condition=record.termination_condition,
        message=record.message,
    )


def analyze_reserve_interval(
    data: ProcurementData,
    *,
    absolute_tolerance: float,
    relative_tolerance: float,
    numerical_activation_ratio: float = 1.0e-4,
    substantive_activation_ratio: float = 0.01,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
) -> ReserveIntervalAnalysis:
    """Identify the complete-extensive tolerance-optimal reserve interval."""

    solver_preference = tuple(solver_preference)
    floor = solve_minimum_feasible_reserve(
        data,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    optimum = solve_m1_endogenous_extensive(
        data,
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
        consistency_tolerance=absolute_tolerance,
    )
    if (
        floor.status != "optimal"
        or optimum.status != "optimal"
        or optimum.objective is None
        or optimum.master.objective is None
    ):
        return ReserveIntervalAnalysis(
            status="base_optimization_failure",
            optimum=optimum,
            minimum_feasible=floor,
            objective_tolerance=0.0,
            minimum_tolerance_optimal=None,
            maximum_tolerance_optimal=None,
            robust_discretionary_reserve=None,
            robust_discretionary_reserve_ratio=None,
            numerical_activation=None,
            substantive_activation=None,
        )
    tolerance = objective_tolerance(
        float(optimum.objective),
        absolute_tolerance=absolute_tolerance,
        relative_tolerance=relative_tolerance,
    )
    common = {
        "data": data,
        "master_optimum": float(optimum.master.objective),
        "exact_optimum": float(optimum.objective),
        "tolerance": tolerance,
        "solver_preference": solver_preference,
        "time_limit_seconds": time_limit_seconds,
        "solver_threads": solver_threads,
        "feasibility_tolerance": feasibility_tolerance,
        "optimality_tolerance": optimality_tolerance,
    }
    minimum = _solve_reserve_face_point(direction="min", **common)
    maximum = _solve_reserve_face_point(direction="max", **common)
    if minimum.status != "optimal" or maximum.status != "optimal":
        return ReserveIntervalAnalysis(
            status="reserve_interval_failure",
            optimum=optimum,
            minimum_feasible=floor,
            objective_tolerance=tolerance,
            minimum_tolerance_optimal=minimum,
            maximum_tolerance_optimal=maximum,
            robust_discretionary_reserve=None,
            robust_discretionary_reserve_ratio=None,
            numerical_activation=None,
            substantive_activation=None,
        )
    discretionary = max(0.0, float(minimum.reserve) - float(floor.reserve))
    ratio = discretionary / data.budget if data.budget > 0.0 else 0.0
    return ReserveIntervalAnalysis(
        status="optimal",
        optimum=optimum,
        minimum_feasible=floor,
        objective_tolerance=tolerance,
        minimum_tolerance_optimal=minimum,
        maximum_tolerance_optimal=maximum,
        robust_discretionary_reserve=discretionary,
        robust_discretionary_reserve_ratio=ratio,
        numerical_activation=ratio > numerical_activation_ratio,
        substantive_activation=ratio >= substantive_activation_ratio,
    )


def fixed_autonomous_reserve_amount(
    *,
    budget: float,
    minimum_feasible_reserve: float,
    rho: float,
) -> float:
    if not 0.0 <= rho <= 1.0:
        raise ValueError("rho must be in [0, 1]")
    if not 0.0 <= minimum_feasible_reserve <= budget:
        raise ValueError("minimum feasible reserve must be in [0, budget]")
    return minimum_feasible_reserve + rho * (
        budget - minimum_feasible_reserve
    )


def build_fixed_autonomous_reserve_model(
    data: ProcurementData,
    *,
    rho: float,
    minimum_feasible_reserve: float,
) -> pyo.ConcreteModel:
    """Build a fresh full model with equality-budget fixed autonomous reserve."""

    expected_floor = closed_form_minimum_reserve(data)
    if not math.isclose(
        float(minimum_feasible_reserve),
        expected_floor,
        rel_tol=0.0,
        abs_tol=1.0e-7,
    ):
        raise ValueError(
            "minimum_feasible_reserve does not match this data instance"
        )
    reserve = fixed_autonomous_reserve_amount(
        budget=float(data.budget),
        minimum_feasible_reserve=float(minimum_feasible_reserve),
        rho=float(rho),
    )
    model = build_m1_endogenous_extensive_model(data)
    model.R.fix(reserve)
    model._model_name = f"M1FixedAutonomousReserve[rho={rho:.4f}]"
    model._fixed_autonomous_reserve_ratio = float(rho)
    model._minimum_feasible_reserve = float(minimum_feasible_reserve)
    return model


def solve_fixed_autonomous_reserve(
    data: ProcurementData,
    *,
    rho: float,
    minimum_feasible_reserve: float,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
    consistency_tolerance: float = 1.0e-6,
) -> ExtensiveSolution:
    """Re-optimize regular procurement for one fixed autonomous reserve share."""

    solver_preference = tuple(solver_preference)
    master = solve_master(
        build_fixed_autonomous_reserve_model(
            data,
            rho=rho,
            minimum_feasible_reserve=minimum_feasible_reserve,
        ),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    if master.status != "optimal":
        return ExtensiveSolution(
            status=f"master_{master.status}",
            master=master,
            evaluation=None,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    evaluation = evaluate_first_stage(
        data,
        master.regular_purchase,
        float(master.reserve),
        solver_preference=solver_preference,
        time_limit_seconds=time_limit_seconds,
        solver_threads=solver_threads,
        feasibility_tolerance=feasibility_tolerance,
        optimality_tolerance=optimality_tolerance,
    )
    if evaluation.status != "optimal" or evaluation.robust_objective is None:
        return ExtensiveSolution(
            status=evaluation.status,
            master=master,
            evaluation=evaluation,
            consistency_difference=None,
            tolerance=consistency_tolerance,
        )
    difference = abs(float(master.objective) - evaluation.robust_objective)
    return ExtensiveSolution(
        status=(
            "optimal"
            if difference <= consistency_tolerance
            else "inconsistent_exact_recourse"
        ),
        master=master,
        evaluation=evaluation,
        consistency_difference=difference,
        tolerance=consistency_tolerance,
    )


def run_m1_standard_ccg(
    data: ProcurementData,
    *,
    initial_scenarios: Sequence[str] | None = None,
    absolute_tolerance: float = 1.0e-6,
    relative_tolerance: float = 1.0e-6,
    max_iterations: int = 200,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
    tee: bool = False,
) -> CCGResult:
    """Run standard C&CG with an M1-specific restricted-master builder."""

    if absolute_tolerance < 0.0 or relative_tolerance < 0.0:
        raise ValueError("C&CG tolerances must be nonnegative")
    if max_iterations <= 0:
        raise ValueError("max_iterations must be positive")
    solver_preference = tuple(solver_preference)
    if not solver_preference:
        raise ValueError("solver_preference must not be empty")
    initial = tuple(
        select_initial_scenarios(data)
        if initial_scenarios is None
        else dict.fromkeys(initial_scenarios)
    )
    if not initial:
        raise ValueError("initial_scenarios must not be empty")
    unknown = set(initial) - set(data.scenarios)
    if unknown:
        raise KeyError(f"unknown initial scenarios: {sorted(unknown)}")

    started = perf_counter()
    selected = list(initial)
    log: list[CCGIteration] = []
    global_lb = -inf
    global_ub = inf
    incumbent_master = None
    incumbent_evaluation: EvaluationResult | None = None
    total_master_time = 0.0
    total_oracle_time = 0.0
    solver_name = "unavailable"
    termination_status = "max_iterations"
    converged = False

    for iteration in range(1, min(max_iterations, len(data.scenarios) + 1) + 1):
        master = solve_master(
            build_m1_restricted_master(data, selected),
            solver_preference=solver_preference,
            time_limit_seconds=time_limit_seconds,
            solver_threads=solver_threads,
            feasibility_tolerance=feasibility_tolerance,
            optimality_tolerance=optimality_tolerance,
            tee=tee,
        )
        total_master_time += master.runtime_seconds
        solver_name = master.solver
        if master.status != "optimal":
            termination_status = f"master_{master.status}"
            break

        global_lb = max(global_lb, float(master.objective))
        evaluation = evaluate_first_stage(
            data,
            master.regular_purchase,
            float(master.reserve),
            solver_preference=solver_preference,
            time_limit_seconds=time_limit_seconds,
            solver_threads=solver_threads,
            feasibility_tolerance=feasibility_tolerance,
            optimality_tolerance=optimality_tolerance,
            tee=tee,
        )
        total_oracle_time += evaluation.runtime_seconds
        added = None
        added_type = None
        candidate_ub = None
        gap = None
        worst_cost = None
        worst_scenario = None

        if evaluation.failed_scenarios:
            termination_status = "oracle_failure"
        elif evaluation.infeasible_scenarios:
            unselected = [
                name
                for name in evaluation.infeasible_scenarios
                if name not in selected
            ]
            if unselected:
                added = unselected[0]
                added_type = "infeasible"
                selected.append(added)
            else:
                termination_status = "inconsistent_infeasible_recourse"
        else:
            candidate_ub = float(evaluation.robust_objective)
            worst_cost = float(evaluation.worst_recourse_cost)
            worst_scenario = str(evaluation.worst_scenario)
            if candidate_ub < global_ub:
                global_ub = candidate_ub
                incumbent_master = master
                incumbent_evaluation = evaluation
            gap = global_ub - global_lb
            tolerance = absolute_tolerance + relative_tolerance * max(
                1.0, abs(global_ub)
            )
            if gap <= tolerance:
                termination_status = "optimal"
                converged = True
            elif worst_scenario not in selected:
                added = worst_scenario
                added_type = "worst_cost"
                selected.append(added)
            else:
                termination_status = "inconsistent_repeated_worst_scenario"

        log.append(
            CCGIteration(
                iteration=iteration,
                scenario_count=len(selected) - (1 if added else 0),
                added_scenario=added,
                added_type=added_type,
                lower_bound=global_lb,
                candidate_upper_bound=candidate_ub,
                global_upper_bound=global_ub if isfinite(global_ub) else None,
                gap=gap,
                regular_cost=float(master.regular_cost),
                reserve=float(master.reserve),
                reserve_ratio=float(master.reserve_ratio),
                master_time=master.runtime_seconds,
                oracle_time=evaluation.runtime_seconds,
                infeasible_scenario_count=len(evaluation.infeasible_scenarios),
                worst_recourse_cost=worst_cost,
                worst_scenario=worst_scenario,
            )
        )
        if converged:
            break
        if termination_status != "max_iterations" and added is None:
            break

    if incumbent_master is None or incumbent_evaluation is None:
        objective = None
        upper_bound = None
        final_gap = None
        purchase: dict[str, list[float]] = {}
        reserve = None
        reserve_ratio = None
        worst_scenario = None
        exact_costs: dict[str, float] = {}
    else:
        objective = global_ub
        upper_bound = global_ub
        final_gap = global_ub - global_lb
        purchase = incumbent_master.regular_purchase
        reserve = incumbent_master.reserve
        reserve_ratio = incumbent_master.reserve_ratio
        worst_scenario = incumbent_evaluation.worst_scenario
        exact_costs = incumbent_evaluation.exact_scenario_costs

    return CCGResult(
        termination_status=termination_status,
        converged=converged,
        objective=objective,
        lower_bound=global_lb if isfinite(global_lb) else None,
        upper_bound=upper_bound,
        gap=final_gap,
        iterations=len(log),
        initial_scenario_set=initial,
        final_scenario_set=tuple(selected),
        regular_purchase=purchase,
        reserve=reserve,
        reserve_ratio=reserve_ratio,
        worst_scenario=worst_scenario,
        exact_scenario_costs=exact_costs,
        total_runtime_seconds=perf_counter() - started,
        master_runtime_seconds=total_master_time,
        oracle_runtime_seconds=total_oracle_time,
        solver=solver_name,
        iteration_log=tuple(log),
        incumbent_evaluation=incumbent_evaluation,
    )


def run_m1_spw_ccg_budget_sequence(
    data: ProcurementData,
    budgets: Sequence[float],
    *,
    active_scenario_tolerance: float = 1.0e-6,
    objective_absolute_tolerance: float = 1.0e-6,
    objective_relative_tolerance: float = 1.0e-6,
    ccg_absolute_tolerance: float = 1.0e-6,
    ccg_relative_tolerance: float = 1.0e-6,
    max_iterations: int = 200,
    solver_preference: Iterable[str] = ("gurobi",),
    time_limit_seconds: float = 600.0,
    solver_threads: int | None = 1,
    feasibility_tolerance: float | None = 1.0e-7,
    optimality_tolerance: float | None = 1.0e-7,
    alternate_execution_order: bool = True,
    tee: bool = False,
) -> SPWCCGResult:
    """Compare M1 cold and warm C&CG without touching M0 entry points."""

    ordered_budgets = tuple(float(value) for value in budgets)
    if not ordered_budgets or any(value <= 0.0 for value in ordered_budgets):
        raise ValueError("budgets must be a nonempty positive sequence")
    if any(
        current <= previous
        for previous, current in zip(ordered_budgets, ordered_budgets[1:])
    ):
        raise ValueError("budgets must be strictly increasing")
    solver_preference = tuple(solver_preference)
    comparisons: list[BudgetComparison] = []
    previous_state: ScenarioPoolState | None = None

    def fail(
        *,
        budget: float,
        status: str,
        stage: str,
        message: str,
        order: tuple[str, str],
        cold_initial: tuple[str, ...],
        warm_initial: tuple[str, ...],
        cold: CCGResult | None,
        warm: CCGResult | None,
    ) -> SPWCCGResult:
        failure = BudgetFailure(
            budget=budget,
            status=status,
            stage=stage,
            message=message,
            execution_order=order,
            cold_initial_scenarios=cold_initial,
            warm_initial_scenarios=warm_initial,
            cold_pool_build_seconds=0.0,
            warm_pool_build_seconds=0.0,
            cold_result=cold,
            warm_result=warm,
        )
        return SPWCCGResult(
            status=status,
            budgets=ordered_budgets,
            comparisons=tuple(comparisons),
            active_scenario_tolerance=active_scenario_tolerance,
            objective_absolute_tolerance=objective_absolute_tolerance,
            objective_relative_tolerance=objective_relative_tolerance,
            alternate_execution_order=alternate_execution_order,
            failure=failure,
        )

    for index, budget in enumerate(ordered_budgets):
        budget_data = replace(data, budget=budget)
        budget_data.validate()
        order = (
            ("cold", "warm")
            if not alternate_execution_order or index % 2 == 0
            else ("warm", "cold")
        )
        cold_initial = select_initial_scenarios(budget_data)
        warm_initial = build_warm_initial_scenarios(budget_data, previous_state)
        cold = None
        warm = None
        for mode in order:
            result = run_m1_standard_ccg(
                budget_data,
                initial_scenarios=(
                    cold_initial if mode == "cold" else warm_initial
                ),
                absolute_tolerance=ccg_absolute_tolerance,
                relative_tolerance=ccg_relative_tolerance,
                max_iterations=max_iterations,
                solver_preference=solver_preference,
                time_limit_seconds=time_limit_seconds,
                solver_threads=solver_threads,
                feasibility_tolerance=feasibility_tolerance,
                optimality_tolerance=optimality_tolerance,
                tee=tee,
            )
            if mode == "cold":
                cold = result
            else:
                warm = result
            if not result.converged or result.objective is None:
                return fail(
                    budget=budget,
                    status=f"{mode}_{result.termination_status}",
                    stage=mode,
                    message=f"{mode} M1 C&CG did not converge",
                    order=order,
                    cold_initial=cold_initial,
                    warm_initial=warm_initial,
                    cold=cold,
                    warm=warm,
                )
        if cold is None or warm is None:
            raise AssertionError("both M1 C&CG modes must execute")
        difference = abs(float(cold.objective) - float(warm.objective))
        limit = objective_absolute_tolerance + objective_relative_tolerance * max(
            1.0, abs(float(cold.objective)), abs(float(warm.objective))
        )
        if difference > limit:
            return fail(
                budget=budget,
                status="inconsistent_cold_warm_objectives",
                stage="comparison",
                message=f"objective difference {difference} exceeds {limit}",
                order=order,
                cold_initial=cold_initial,
                warm_initial=warm_initial,
                cold=cold,
                warm=warm,
            )
        state = build_transferred_state(
            budget_data,
            budget=budget,
            result=warm,
            previous_state=previous_state,
            active_scenario_tolerance=active_scenario_tolerance,
        )
        comparisons.append(
            BudgetComparison(
                budget=budget,
                execution_order=order,
                cold_initial_scenarios=cold_initial,
                warm_initial_scenarios=warm_initial,
                cold_pool_build_seconds=0.0,
                warm_pool_build_seconds=0.0,
                cold_result=cold,
                warm_result=warm,
                objective_difference=difference,
                objectives_consistent=True,
                transferred_state=state,
            )
        )
        previous_state = state

    return SPWCCGResult(
        status="optimal",
        budgets=ordered_budgets,
        comparisons=tuple(comparisons),
        active_scenario_tolerance=active_scenario_tolerance,
        objective_absolute_tolerance=objective_absolute_tolerance,
        objective_relative_tolerance=objective_relative_tolerance,
        alternate_execution_order=alternate_execution_order,
    )


def m1_scientific_config_sha256(config: Mapping[str, Any]) -> str:
    scientific = {
        key: value for key, value in config.items() if key not in M1_LIFECYCLE_FIELDS
    }
    encoded = json.dumps(
        scientific,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _component_sha256(project_root: Path, files: Sequence[str]) -> str:
    digest = hashlib.sha256()
    for relative in files:
        path = project_root / relative
        if not path.is_file():
            raise FileNotFoundError(f"M1 component file is missing: {path}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(read_lf_bytes(path))
        digest.update(b"\0")
    return digest.hexdigest()


def m1_fingerprints(
    *,
    project_root: Path,
    config_path: Path,
    runner_config_path: Path,
) -> dict[str, str]:
    config = load_m1_config(config_path)
    locked = validate_locked_environment(project_root)
    return {
        "scientific_config_sha256": m1_scientific_config_sha256(config),
        "e3_component_sha256": _component_sha256(
            project_root, M1_E3_COMPONENT_FILES
        ),
        "family_component_sha256": _component_sha256(
            project_root, M1_FAMILY_COMPONENT_FILES
        ),
        "runner_config_sha256": sha256_lf_text_file(runner_config_path),
        "environment_sha256": environment_sha256(locked),
    }

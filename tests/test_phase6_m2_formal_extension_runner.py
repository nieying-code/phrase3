from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from pathlib import Path

import pytest

import src.phase6_m2_formal_extension as runner


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs/phase6_m2_formal_extension.yaml"
RUNNER = ROOT / "configs/phase6_m2_formal_extension_runner.yaml"
APPROVAL = ROOT / "configs/phase6_m2_formal_extension_pilot_approval.yaml"
SHA = "a" * 64
STRATEGIES = (
    "endogenous_reserve",
    "zero_autonomous_reserve",
    "fixed_autonomous_reserve_0_10",
    "fixed_autonomous_reserve_0_30",
    "fixed_autonomous_reserve_0_50",
)


def _config() -> dict:
    return runner.load_formal_extension_config(CONFIG)


def _fingerprints() -> dict[str, str]:
    return {field: hashlib.sha256(field.encode()).hexdigest() for field in runner.FINGERPRINT_FIELDS}


def _mechanism_science(case: runner.PilotCase) -> dict:
    training_hash = "8" * 64
    components = {
        "latent_draw_sha256": "1" * 64,
        "demand_sha256": "2" * 64,
        "emergency_price_sha256": "3" * 64,
        "emergency_supply_sha256": "4" * 64,
        "scenario_order_sha256": "5" * 64,
        "fulfillment_sha256": hashlib.sha256(case.profile_id.encode()).hexdigest(),
    }
    return {
        "tier_id": "M2F2", "seed": case.seed, "beta": case.beta,
        "profile_id": case.profile_id, "training_scenario_count": 100,
        "scenario_identity_count": 100,
        "reference_budget": 2337.610924158743,
        "budget": case.beta * 2337.610924158743,
        "R_min_feas": 0.0, "R_min_opt": 100.0, "R_max_opt": 100.0,
        "R_disc_robust": 100.0,
        "R_disc_robust_ratio": 100.0 / (case.beta * 2337.610924158743),
        "numerical_activation": True, "substantive_activation": True,
        "moderate_activation": False, "objective_tolerance": 0.1,
        "minimum_endpoint_status": "optimal", "maximum_endpoint_status": "optimal",
        "minimum_endpoint_consistency_difference": 0.0,
        "maximum_endpoint_consistency_difference": 0.0,
        "endpoint_failure_counts": {
            "minimum": {"infeasible": 0, "solver_failure": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0},
        },
        "first_stage_plan_artifacts": {
            strategy: {
                "strategy_id": strategy, "path": f"plans/{strategy}.json",
                "finalized_plan_artifact_sha256": SHA,
                "reserve_amount": float(index),
                "regular_purchase_sha256": hashlib.sha256(strategy.encode()).hexdigest(),
                "exact_training_objective": 1000.0 + index,
                "training_joint_scenario_set_sha256": training_hash,
            }
            for index, strategy in enumerate(STRATEGIES)
        },
        "fixed_reserve_policies": [
            {
                "rho": rho, "status": "optimal", "regular_purchase_reoptimized": True,
                "reserve": rho * (case.beta * 2337.610924158743),
            }
            for rho in (0.0, 0.1, 0.3, 0.5)
        ],
        "scenario_component_set_sha256": components,
        "joint_scenario_set_sha256": training_hash,
        "c0_equivalence": (
            {"required": True, "status": "passed"}
            if case.profile_id == "C0"
            else {"required": False, "status": "not_applicable"}
        ),
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def _probe_science(case: runner.PilotCase) -> dict:
    test_hash = "6" * 64
    training_hash = "8" * 64
    source_case_id = "M2F2_seed2026081601_beta1p10_profileT03"
    return {
        "tier_id": "M2F2", "seed": case.seed, "test_seed": case.test_seed,
        "beta": case.beta, "profile_id": case.profile_id,
        "test_scenario_identity_count": 2000,
        "source_mechanism_run_id": f"pilot_{source_case_id}",
        "source_training_joint_scenario_set_sha256": training_hash,
        "test_joint_scenario_set_sha256": test_hash,
        "test_scenario_component_set_sha256": {
            "latent_draw_sha256": "1" * 64,
            "demand_sha256": "2" * 64,
            "emergency_price_sha256": "3" * 64,
            "emergency_supply_sha256": "4" * 64,
            "scenario_order_sha256": "5" * 64,
            "fulfillment_sha256": "7" * 64,
        },
        "strategy_results": {
            strategy: {
                "strategy_id": strategy,
                "source_plan_artifact_sha256": SHA,
                "source_plan_training_joint_scenario_set_sha256": training_hash,
                "source_plan_exact_training_objective": 1000.0 + index,
                "reserve_amount": float(index),
                "regular_purchase_sha256": hashlib.sha256(strategy.encode()).hexdigest(),
                "test_joint_scenario_set_sha256": test_hash,
                "wall_seconds": 10.0 + index,
                "metrics": {
                    "plan_oos_status": "complete_feasible",
                    "optimal_scenario_count": 2000,
                    "infeasible_scenario_count": 0,
                    "solver_failure_count": 0,
                    "mean_total_cost": 100.0,
                    "total_cost_p95": 120.0,
                    "total_cost_cvar95": 140.0,
                    "service_level": 0.9,
                    "shortage_probability": 0.1,
                    "mean_emergency_spend": 10.0,
                },
                "cross_item_allocation": {
                    "scenario_item_emergency_spend_sha256": "9" * 64,
                    "positive_total_emergency_spend_scenario_count": 100,
                    "both_items_each_positive_in_at_least_one_scenario": True,
                    "item1_emergency_spend_share_range": 0.2,
                },
            }
            for index, strategy in enumerate(STRATEGIES)
        },
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def _result(case: runner.PilotCase) -> dict:
    return {
        "run_id": f"pilot_{case.case_id}", "case_id": case.case_id,
        "case": case.as_dict(), "status": "optimal", "wall_seconds": 20.0,
        "science": _mechanism_science(case) if case.run_kind == "mechanism" else _probe_science(case),
    }


def test_frozen_pilot_matrix_is_exact_and_ordered() -> None:
    cases = runner.build_pilot_cases(_config())
    assert len(cases) == 16
    assert sum(case.run_kind == "mechanism" for case in cases) == 15
    assert sum(case.run_kind == "OOS_probe" for case in cases) == 1
    expected = [
        (seed, beta, profile)
        for seed in (2026081601, 2026081602, 2026081603)
        for beta, profiles in ((1.1, ("C0", "C1", "T03")), (1.3, ("C0", "T03")))
        for profile in profiles
    ]
    assert [(case.seed, case.beta, case.profile_id) for case in cases[:-1]] == expected
    assert cases[-1].as_dict() == {
        "case_id": "M2F2_OOS_probe_train2026081601_test2026081701_beta1p10_profileT03",
        "run_kind": "OOS_probe", "tier_id": "M2F2", "seed": 2026081601,
        "beta": 1.1, "profile_id": "T03", "test_seed": 2026081701,
    }


def test_missing_authorization_fails_before_fingerprints_or_scenarios(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "formal_extension_fingerprints", lambda *args, **kwargs: pytest.fail("fingerprints reached"))
    with pytest.raises(PermissionError, match="authorize-pilot"):
        runner.validate_preflight(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )


@pytest.mark.parametrize(
    "field", ["reference_budget", "storage_capacity", "budget", "secondary_budget"],
)
def test_deterministic_inputs_are_recomputed_before_scenario_generation(
    field: str, monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = deepcopy(_config())
    if field == "reference_budget":
        config["scientific_model"]["reference_budget"] += 1.0
    elif field == "storage_capacity":
        config["scientific_model"]["storage_capacity"][0] += 1.0
    elif field == "budget":
        config["mechanism_experiment"]["primary_track"]["budget"] += 1.0
    else:
        # The first case is beta=1.1; corrupt beta=1.3 to prove both tracks are
        # closed before the first scenario set is generated.
        config["mechanism_experiment"]["secondary_track"]["budget"] += 1.0
    matrix = runner.load_phase6_matrix(ROOT / "configs/phase6_experiment_matrix.yaml")
    case = runner.build_pilot_cases(config)[0]
    monkeypatch.setattr(
        runner, "generate_phase6_data",
        lambda *args, **kwargs: pytest.fail("scenario generation reached"),
    )
    with pytest.raises(ValueError, match="pre-generation"):
        runner.execute_mechanism_science(
            project_root=ROOT, matrix=matrix,
            matrix_path=ROOT / "configs/phase6_experiment_matrix.yaml",
            config=config, case=case, progress=lambda *args: None,
        )


def test_real_formal_generated_wrapper_reaches_first_solver_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exercise the real 100-scenario M2F2 wrapper, then stop before Gurobi."""
    config = _config()
    matrix_path = ROOT / "configs/phase6_experiment_matrix.yaml"
    matrix = runner.load_phase6_matrix(matrix_path)
    case = runner.build_pilot_cases(config)[0]
    reached: dict[str, float | int] = {}

    def stop_at_first_solver(data, **kwargs):
        reached["scenario_count"] = len(data.scenarios)
        reached["item_count"] = len(data.items)
        reached["periods"] = data.periods
        reached["time_limit_seconds"] = kwargs["time_limit_seconds"]
        raise RuntimeError("formal-first-solver-boundary-reached")

    monkeypatch.setattr(runner, "solve_minimum_feasible_reserve", stop_at_first_solver)
    with pytest.raises(RuntimeError, match="formal-first-solver-boundary-reached"):
        runner.execute_mechanism_science(
            project_root=ROOT, matrix=matrix, matrix_path=matrix_path,
            config=config, case=case, progress=lambda *args: None,
        )
    assert reached == {
        "scenario_count": 100, "item_count": 2, "periods": 6,
        "time_limit_seconds": 120.0,
    }


def test_primary_partial_execution_and_unbound_diagnostic_are_forbidden(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(runner, "validate_preflight", lambda **kwargs: {
        "config": _config(), "fingerprints": _fingerprints(),
        "locked_environment": {}, "source": {},
    })
    case_id = runner.build_pilot_cases(_config())[0].case_id
    with pytest.raises(ValueError, match="complete frozen pilot"):
        runner.run_pilot(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", case_ids=[case_id],
        )
    with pytest.raises(ValueError, match="one case_id"):
        runner.run_pilot(
            root=ROOT, config_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", parent_run_id="parent",
        )


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", "C:\\absolute"])
def test_run_id_path_escape_is_rejected(run_id: str, tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        runner._run_directory(tmp_path, run_id)


def test_plan_artifacts_are_finalized_and_immutable(tmp_path: Path) -> None:
    directory = tmp_path / "runs" / "r1"
    payloads = {
        strategy: {
            "strategy_id": strategy, "artifact_state": "pending_finalization",
            "reserve_amount": float(index), "regular_purchase": {"i": [1.0]},
            "regular_purchase_sha256": hashlib.sha256(strategy.encode()).hexdigest(),
            "exact_training_objective": 10.0, "training_joint_scenario_set_sha256": SHA,
        }
        for index, strategy in enumerate(STRATEGIES)
    }
    identities = runner._write_plan_artifacts(
        directory=directory, run_id="r1", case_id="c1", payloads=payloads,
    )
    assert tuple(identities) == STRATEGIES
    for strategy, identity in identities.items():
        path = Path(identity["path"])
        assert path.resolve().is_relative_to(directory.resolve())
        assert runner.sha256_file(path) == identity["finalized_plan_artifact_sha256"]
        assert json.loads(path.read_text(encoding="utf-8"))["artifact_state"] == "finalized"


def test_registry_artifacts_cannot_cross_the_controlled_namespace(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    row = {
        "run_id": "safe", "result_path": str(outside / "result.json"),
        "manifest_path": str(outside / "manifest.json"),
    }
    with pytest.raises(ValueError, match="leaves the pilot namespace"):
        runner._controlled_artifact_paths(tmp_path / "controlled", row)


def test_run_lifecycle_finalizes_failure_and_makes_run_id_immutable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case = runner.build_pilot_cases(_config())[0]
    monkeypatch.setattr(runner, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(runner, "capture_runtime_context", lambda **kwargs: {"solver": "gurobi_direct"})
    monkeypatch.setattr(runner, "update_projection", lambda **kwargs: {"formal_extension_authorized": False})
    monkeypatch.setattr(runner, "_write_registry", lambda *args, **kwargs: None)

    def fail(**kwargs):
        kwargs["progress"]("complete_extensive_optimum", {})
        raise RuntimeError("synthetic solver failure")

    output = tmp_path / "out"
    result = runner.run_case(
        root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
        config=_config(), fingerprints=_fingerprints(), locked_environment={},
        source={"commit_sha": "c" * 40, "tree_sha": "d" * 40}, case=case,
        run_id="immutable_failure", science_executor=fail,
    )
    assert result["status"] == "stage_failure"
    directory = output / "pilot/runs/immutable_failure"
    assert json.loads((directory / "result.json").read_text(encoding="utf-8"))["status"] == "stage_failure"
    assert json.loads((directory / "status_summary.json").read_text(encoding="utf-8"))["failure"]["message"]
    with pytest.raises(ValueError, match="immutable"):
        runner.run_case(
            root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
            config=_config(), fingerprints=_fingerprints(), locked_environment={},
            source={"commit_sha": "c" * 40, "tree_sha": "d" * 40}, case=case,
            run_id="immutable_failure", science_executor=fail,
        )


def _projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mutate=None) -> dict:
    config = _config()
    fingerprints = _fingerprints()
    cases = runner.build_pilot_cases(config)
    results = {case.case_id: _result(case) for case in cases}
    if mutate:
        mutate(results)
    rows = [
        {"run_id": value["run_id"], "parent_run_id": "", **fingerprints}
        for value in results.values()
    ]
    monkeypatch.setattr(runner, "_read_registry", lambda path: rows)
    monkeypatch.setattr(runner, "_validate_artifact", lambda output_root, row: next(
        value for value in results.values() if value["run_id"] == row["run_id"]
    ))
    monkeypatch.setattr(runner, "_validate_plan_artifact", lambda **kwargs: {})
    monkeypatch.setattr(runner, "_finalization_failure_ids", lambda base: [])
    monkeypatch.setattr(runner, "atomic_write_json", lambda path, payload: None)
    return runner.update_projection(output_root=tmp_path, config=config, fingerprints=fingerprints)


def test_projection_independently_closes_pilot_and_never_authorizes_formal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    projection = _projection(monkeypatch, tmp_path)
    assert projection["status"] == "complete"
    assert projection["verified_mechanism_run_count"] == 15
    assert projection["verified_OOS_probe_run_count"] == 1
    assert projection["common_random_numbers_verified"] is True
    assert math.isclose(projection["mechanism_projected_wall_hours"], 50 * 20 / 3600)
    assert math.isclose(projection["OOS_projected_wall_hours"], 50 * 14 / 3600)
    assert projection["pilot_compute_gate_passed"] is True
    assert projection["next_decision"] == "permit_separate_formal_freeze_PR_only"
    assert projection["formal_extension_authorized"] is False


def test_endpoint_consistency_accepts_only_the_existing_numerical_slack() -> None:
    case = runner.build_pilot_cases(_config())[0]
    science = _mechanism_science(case)
    tolerance = float(science["objective_tolerance"])
    science["minimum_endpoint_consistency_difference"] = (
        tolerance + runner.ENDPOINT_OBJECTIVE_COMPARISON_SLACK
    )
    science["maximum_endpoint_consistency_difference"] = (
        tolerance + runner.ENDPOINT_OBJECTIVE_COMPARISON_SLACK
    )
    runner._derive_mechanism(science, case.as_dict())

    science["maximum_endpoint_consistency_difference"] += 1.0e-9
    with pytest.raises(ValueError, match="tolerance-optimal reserve interval"):
        runner._derive_mechanism(science, case.as_dict())


@pytest.mark.parametrize(
    ("field", "value"),
    [
        (field, value)
        for field in (
            "objective_tolerance",
            "minimum_endpoint_consistency_difference",
            "maximum_endpoint_consistency_difference",
        )
        for value in (math.nan, math.inf, -math.inf, -1.0e-12)
    ],
)
def test_endpoint_tolerance_evidence_must_be_finite_and_nonnegative(
    field: str, value: float,
) -> None:
    case = runner.build_pilot_cases(_config())[0]
    science = _mechanism_science(case)
    science[field] = value
    with pytest.raises(ValueError, match="finite and nonnegative"):
        runner._derive_mechanism(science, case.as_dict())


def test_crn_mismatch_blocks_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def mutate(results: dict) -> None:
        target = next(value for value in results.values() if value["case"]["profile_id"] == "C1")
        target["science"]["scenario_component_set_sha256"]["demand_sha256"] = "9" * 64

    projection = _projection(monkeypatch, tmp_path, mutate)
    assert projection["status"] == "incomplete"
    assert projection["common_random_numbers_verified"] is False
    assert projection["pilot_compute_gate_passed"] is False
    assert projection["formal_extension_authorized"] is False


def test_incomplete_oos_probe_blocks_projection(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def mutate(results: dict) -> None:
        target = next(value for value in results.values() if value["case"]["run_kind"] == "OOS_probe")
        target["science"]["strategy_results"][STRATEGIES[0]]["metrics"]["solver_failure_count"] = 1

    projection = _projection(monkeypatch, tmp_path, mutate)
    assert projection["status"] == "incomplete"
    assert projection["invalid_primary_run_ids"]
    assert projection["formal_extension_authorized"] is False


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_source_run",
        "wrong_source_plan_hash",
        "wrong_source_training_hash",
        "wrong_reserve",
        "wrong_purchase_hash",
        "missing_metric",
        "nan_metric",
        "zero_runtime",
        "missing_cross_item_hash",
    ],
)
def test_oos_source_binding_and_frozen_metrics_are_hard_projection_gates(
    mutation: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    def mutate(results: dict) -> None:
        probe = next(value for value in results.values() if value["case"]["run_kind"] == "OOS_probe")
        row = probe["science"]["strategy_results"][STRATEGIES[0]]
        if mutation == "wrong_source_run":
            probe["science"]["source_mechanism_run_id"] = "wrong_run"
        elif mutation == "wrong_source_plan_hash":
            row["source_plan_artifact_sha256"] = "b" * 64
        elif mutation == "wrong_source_training_hash":
            row["source_plan_training_joint_scenario_set_sha256"] = "b" * 64
        elif mutation == "wrong_reserve":
            row["reserve_amount"] += 1.0
        elif mutation == "wrong_purchase_hash":
            row["regular_purchase_sha256"] = "b" * 64
        elif mutation == "missing_metric":
            row["metrics"].pop("total_cost_p95")
        elif mutation == "nan_metric":
            row["metrics"]["total_cost_cvar95"] = float("nan")
        elif mutation == "zero_runtime":
            row["wall_seconds"] = 0.0
        else:
            row["cross_item_allocation"].pop("scenario_item_emergency_spend_sha256")

    projection = _projection(monkeypatch, tmp_path, mutate)
    assert projection["status"] == "incomplete"
    assert projection["verified_OOS_probe_run_count"] == 0
    assert projection["invalid_primary_run_ids"]
    assert projection["pilot_compute_gate_passed"] is False
    assert projection["formal_extension_authorized"] is False


def test_bounded_status_never_reads_large_results(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import src.phase6_m2_formal_extension_status as status

    output = tmp_path / "pilot"
    run = output / "runs" / "safe_run"
    run.mkdir(parents=True)
    (run / "result.json").write_text("{" + "x" * 100_000, encoding="utf-8")
    (run / "status_summary.json").write_text(json.dumps({
        "run_id": "safe_run", "case_id": "c", "status": "stage_failure",
        "current_stage": "solve", "completed_stage_count": 1,
        "failure": {"stage": "solve", "status": "stage_failure", "message": "x" * 50_000},
    }), encoding="utf-8")
    payload = status.build_status(output, run_id="safe_run")
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    assert len(encoded) <= 16 * 1024
    assert "result" not in payload

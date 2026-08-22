from __future__ import annotations

from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path

import pytest
import yaml

import src.phase6_m2_1_pilot as pilot
import src.run_phase6_m2_1_pilot as cli
from src.phase6_m2_1_pilot_status import MAX_BYTES, read_status


ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / pilot.PILOT_CONFIG_PATH
RUNNER = ROOT / pilot.RUNNER_CONFIG_PATH
APPROVAL = ROOT / pilot.APPROVAL_PATH
DESIGN = ROOT / pilot.DESIGN_CONFIG_PATH
AUDIT = ROOT / "docs/handoffs/2026-08-22_phase6_m2_1_pilot_runner_v1_0_audit.json"
SHA = "a" * 64
EXPECTED_RUNNER_FINGERPRINTS = {
    "scientific_config_sha256": "91e20926b71287e61ea0adcd95c4f6c2f67c452c678c2a7bd380c02c27515c71",
    "e3_component_sha256": "398415ae6fd87228247eb44f65729ea191db35840e094e13dad44912e40c2d04",
    "family_component_sha256": "9dd020fe5b48eb02937b1a086cb3ad75ceb7127766b0c998aacf17bcbb31cf05",
    "runner_config_sha256": "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}
HISTORICAL_AUTHORIZED_FINGERPRINTS = {
    "scientific_config_sha256": "1cb170cda4ea880482208419be5fe61218b4bc113eb38a756164ac9ca0a62a60",
    "e3_component_sha256": "987755f9df12339008f057fa5323406dfa41a0331bdc14b790df9a6d2220b1a1",
    "family_component_sha256": "c32e61061da0fea90ea195546a9b7550d919a4ba96c1d3b528cbf2040905e531",
    "runner_config_sha256": "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2",
    "environment_sha256": "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af",
}


def _configs():
    return pilot.load_pilot_config(CONFIG), pilot.load_m2_1_config(DESIGN)


def _fingerprints() -> dict[str, str]:
    return {field: hashlib.sha256(field.encode()).hexdigest() for field in pilot.FINGERPRINT_FIELDS}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_runner_artifacts_parent_evidence_and_fingerprints_are_locked() -> None:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert audit["base"] == {
        "pr62_merge_commit": "770c863d69ba37ba858b00931310f94a9fb84e77",
        "pr62_merge_tree": "043de6a433376928e9544c6e2d7784811a37a7d2",
        "branch": "agent/phase6-m2-1-pilot-runner",
    }
    artifacts = {
        "pilot_config": (CONFIG, "f593c2469ee88ba49098e96c2e42354af74ae7f0d8cea59d15a3d1f8b4aa8fbf"),
        "runner_config": (RUNNER, "b0f975506ac5de4262987f40bbee50af60b9343730fff9a37139dc7068ed8bc2"),
        "approval": (APPROVAL, "e96f62f58cdca24e372b0bbf6bcefd3b2c9ae9250250bc2c98cd117add3855d8"),
        "runner_module": (ROOT / "src/phase6_m2_1_pilot.py", "1cc65ea38f4c51e145501eca1b80ae3a42346db1dc83310a0623d07400941c67"),
        "cli": (ROOT / "src/run_phase6_m2_1_pilot.py", "415759c084400c256440a9634ac10b54b98d829ec01a0ba32140831cce7609c7"),
        "status_module": (ROOT / "src/phase6_m2_1_pilot_status.py", "e913f26a12890ea192bfd6ce292f948b990c53464d6005a4c87da35a167b20a3"),
    }
    assert audit["artifact_sha256"] == {name: expected for name, (_, expected) in artifacts.items()}
    # Authorization legitimately changes only the pilot protocol and approval.
    # Every execution artifact must remain byte-identical to reviewed PR #63.
    for name in ("runner_config", "cli", "status_module"):
        path, expected = artifacts[name]
        assert _sha256(path) == expected, name
    assert _sha256(artifacts["runner_module"][0]) != artifacts["runner_module"][1]
    for name in ("pilot_config", "approval"):
        assert len(artifacts[name][1]) == 64
    assert audit["parent_evidence"] == {
        "design_config_sha256": _sha256(DESIGN),
        "pr62_audit_sha256": _sha256(ROOT / "docs/handoffs/2026-08-21_phase6_m2_1_endpoint_selection_design_v1_0_audit.json"),
        "formal_extension_config_sha256": _sha256(ROOT / pilot.FORMAL_BASE_CONFIG_PATH),
        "confirmation_config_sha256": _sha256(ROOT / "configs/phase6_m2_two_item_confirmation.yaml"),
    }
    actual = pilot.pilot_fingerprints(ROOT, CONFIG, RUNNER)
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        if field in {"e3_component_sha256", "family_component_sha256"}:
            assert actual[field] != HISTORICAL_AUTHORIZED_FINGERPRINTS[field]
        else:
            assert actual[field] == HISTORICAL_AUTHORIZED_FINGERPRINTS[field]
    # CI hardware is intentionally different from the approved experiment
    # machine.  Actual pilot preflight still compares all five fields against
    # approval and therefore cannot run on CI or a different workstation.
    assert len(actual["environment_sha256"]) == 64
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    for field in (
        "scientific_config_sha256", "e3_component_sha256",
        "family_component_sha256", "runner_config_sha256",
    ):
        assert approval["approved_fingerprints"][field] == actual[field]
    assert approval["approved_fingerprints"]["environment_sha256"] == (
        "b46fb4921101d1002af2b7c5873b6df45ea7c83040cc904d3becc5ab3b66a6af"
    )
    assert audit["fingerprints"] == EXPECTED_RUNNER_FINGERPRINTS


def _scenario_identity(fill: str = "a") -> dict[str, str]:
    return {field: fill * 64 for field in pilot.SCENARIO_IDENTITY_FIELDS}


def _plan_identity(strategy: str, index: int) -> dict:
    return {
        "strategy_id": strategy,
        "path": f"plans/{strategy}.json",
        "finalized_plan_artifact_sha256": hashlib.sha256(f"artifact-{strategy}".encode()).hexdigest(),
        "regular_purchase_sha256": hashlib.sha256(f"purchase-{strategy}".encode()).hexdigest(),
        "reserve_amount": float(index * 10),
        "exact_training_objective": 1000.0 + index,
        "training_joint_scenario_set_sha256": "b" * 64,
    }


def _science(case: pilot.M21PilotCase) -> dict:
    plan_ids = (*pilot.CANDIDATE_IDS, "zero_autonomous_reserve", "fixed_autonomous_reserve_0_10", "fixed_autonomous_reserve_0_30", "fixed_autonomous_reserve_0_50")
    plans = {name: _plan_identity(name, index) for index, name in enumerate(plan_ids)}
    validation_identity = _scenario_identity("c")
    validation = {
        name: {
            "candidate_id": name,
            "reserve": plans[name]["reserve_amount"],
            "regular_purchase_sha256": plans[name]["regular_purchase_sha256"],
            "exact_training_objective": plans[name]["exact_training_objective"],
            "source_plan_identity": {
                field: plans[name][field] for field in pilot.PLAN_IDENTITY_FIELDS
            },
            "metrics": {
                "plan_oos_status": "complete_feasible", "optimal_scenario_count": 2000,
                "infeasible_scenario_count": 0, "solver_failure_count": 0,
                "mean_total_cost": 100.0 + index,
                "total_cost_cvar95": 110.0 + index, "service_level": 0.9,
            },
            **validation_identity,
        }
        for index, name in enumerate(pilot.CANDIDATE_IDS)
    }
    selection = pilot.select_validation_candidate({
        name: {
            "total_cost_cvar95": row["metrics"]["total_cost_cvar95"],
            "mean_total_cost": row["metrics"]["mean_total_cost"], "reserve": row["reserve"],
        }
        for name, row in validation.items()
    })
    test = {}
    test_identity = _scenario_identity("d") if case.includes_test_probe else None
    if case.includes_test_probe:
        strategy_sources = {
            "M2_minimum_endpoint": "minimum_endpoint",
            "M2_1_validation_selected_endpoint": selection["selected_candidate_id"],
            "zero_autonomous_reserve": "zero_autonomous_reserve",
            "fixed_autonomous_reserve_0_10": "fixed_autonomous_reserve_0_10",
            "fixed_autonomous_reserve_0_30": "fixed_autonomous_reserve_0_30",
            "fixed_autonomous_reserve_0_50": "fixed_autonomous_reserve_0_50",
        }
        for strategy, source in strategy_sources.items():
            plan = plans[source]
            test[strategy] = {
                "strategy_id": strategy, "source_candidate_id": source,
                "reserve": plan["reserve_amount"],
                "regular_purchase_sha256": plan["regular_purchase_sha256"],
                "exact_training_objective": plan["exact_training_objective"],
                "source_plan_identity": {
                    field: plan[field] for field in pilot.PLAN_IDENTITY_FIELDS
                },
                "metrics": {
                    "plan_oos_status": "complete_feasible", "optimal_scenario_count": 2000,
                    "infeasible_scenario_count": 0, "solver_failure_count": 0,
                    "mean_total_cost": 100.0, "total_cost_cvar95": 110.0,
                    "service_level": 0.9,
                },
                **test_identity,
            }
    return {
        "tier_id": "M2F2", "beta": 1.1, "profile_id": "T03",
        "training_seed": case.training_seed, "validation_seed": case.validation_seed,
        "test_seed": case.test_seed, "includes_test_probe": case.includes_test_probe,
        "budget": 2571.372016574617, "training_scenario_count": 100,
        "validation_scenario_count": 2000,
        "test_scenario_count": 2000 if case.includes_test_probe else 0,
        "training_scenario_identity": _scenario_identity("b"),
        "R_min_feas": 0.0, "R_min_opt": 10.0, "R_max_opt": 30.0,
        "complete_extensive_objective": 1000.0, "objective_tolerance": 0.1,
        "endpoint_failure_counts": {
            "minimum": {"infeasible": 0, "solver_failure": 0},
            "maximum": {"infeasible": 0, "solver_failure": 0},
        },
        "candidate_training": {}, "validation_results": validation,
        "validation_selection": selection, "validation_scenario_identity": validation_identity,
        "test_results": test, "test_scenario_identity": test_identity,
        "minimum_endpoint_control_candidate_id": "minimum_endpoint",
        "minimum_endpoint_generated_once": True,
        "first_stage_plan_artifacts": plans,
        "minimum_endpoint_M2_control_identity": {
            field: plans["minimum_endpoint"][field] for field in pilot.PLAN_IDENTITY_FIELDS
        },
        "solver": "gurobi_direct", "gurobi_optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "threads": 1,
    }


def test_frozen_pilot_is_exactly_three_indivisible_triplets() -> None:
    config, design = _configs()
    cases = pilot.build_pilot_cases(config, design)
    assert len(cases) == 3
    assert [case.triplet_position for case in cases] == [1, 2, 3]
    assert [(case.training_seed, case.validation_seed, case.test_seed) for case in cases] == [
        (2026090401, 2026090501, 2026090701),
        (2026090402, 2026090502, 2026090702),
        (2026090403, 2026090503, 2026090703),
    ]
    assert [case.includes_test_probe for case in cases] == [True, False, False]
    assert config["pilot_matrix"]["validation_exact_recourse_evaluation_count"] == 18000
    assert config["pilot_matrix"]["test_probe_exact_recourse_evaluation_count"] == 12000
    runner = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    assert runner["solver"] == {
        "interface": "gurobi_direct", "optimizer_version": "13.0.2",
        "gurobipy_version": "13.0.2", "fallback_allowed": False,
    }
    assert runner["limits"]["threads"] == 1


def test_authorized_revision_still_requires_cli_and_strict_preflight(monkeypatch) -> None:
    with pytest.raises(PermissionError, match="authorize-pilot"):
        pilot.validate_preflight(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )
    current_approved = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))["approved_fingerprints"]
    monkeypatch.setattr(
        pilot, "pilot_fingerprints", lambda *args, **kwargs: current_approved,
    )
    monkeypatch.setattr(pilot, "validate_execution_source", lambda *args, **kwargs: {
        "commit_sha": "a" * 40, "tree_sha": "b" * 40,
    })
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {
        "solver": {"selected": "gurobi_direct", "version": "13.0.2", "threads": 1},
    })
    monkeypatch.setattr(pilot, "validate_locked_environment", lambda root: {})
    preflight = pilot.validate_preflight(
        root=ROOT, pilot_path=CONFIG, runner_path=RUNNER,
        approval_path=APPROVAL, authorize=True,
    )
    assert preflight["fingerprints"] == current_approved


@pytest.mark.parametrize("target", ["parent", "base", "seed", "count", "identity", "gate", "formal"])
def test_pilot_config_tampering_is_rejected(target, tmp_path) -> None:
    payload = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    if target == "parent":
        payload["frozen_design"]["pr62_merge_tree"] = "0" * 40
    elif target == "base":
        payload["scientific_base"]["budget"] = 1.0
    elif target == "seed":
        payload["pilot_matrix"]["training_seeds"][0] += 1
    elif target == "count":
        payload["pilot_matrix"]["validation_exact_recourse_evaluation_count"] = 17999
    elif target == "identity":
        payload["identity_gates"]["validation_scenario_generated_once_per_triplet"] = False
    elif target == "gate":
        payload["compute_gate"]["projected_formal_wall_hours_maximum"] = 73.0
    else:
        payload["execution_boundaries"]["formal_test_authorized"] = True
    path = tmp_path / f"{target}.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    with pytest.raises(ValueError):
        pilot.load_pilot_config(path)


def test_future_frozen_revision_still_requires_explicit_cli_authorization(monkeypatch) -> None:
    config = pilot.load_pilot_config(CONFIG)
    monkeypatch.setattr(pilot, "load_pilot_config", lambda path: config)
    monkeypatch.setattr(pilot, "pilot_fingerprints", lambda *args, **kwargs: pytest.fail("fingerprints reached"))
    with pytest.raises(PermissionError, match="authorize-pilot"):
        pilot.validate_preflight(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER,
            approval_path=APPROVAL, authorize=False,
        )


@pytest.mark.parametrize("version", ["13.0.2", "13.0.2.0"])
def test_gurobi_runtime_release_normalizes_supported_pyomo_spellings(version) -> None:
    assert pilot._gurobi_release_triplet(version) == (13, 0, 2)


@pytest.mark.parametrize(
    "version", ["13.0.2.1", "13.0", "13.0.2.dev", None],
)
def test_gurobi_runtime_release_rejects_other_versions(version) -> None:
    with pytest.raises(ValueError):
        pilot._gurobi_release_triplet(version)


def test_other_valid_gurobi_release_does_not_match_approved_release() -> None:
    assert pilot._gurobi_release_triplet("13.0.3") != (13, 0, 2)


@pytest.mark.parametrize("phase,identity", [("validation", "validation_results"), ("test", "test_results")])
@pytest.mark.parametrize("field", pilot.SCENARIO_IDENTITY_FIELDS)
def test_projection_rejects_any_shared_scenario_identity_tamper(phase, identity, field) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    target = "interval_midpoint" if phase == "validation" else "fixed_autonomous_reserve_0_50"
    science[identity][target][field] = "e" * 64
    with pytest.raises(Exception, match="common_random_number_mismatch"):
        pilot._derive_triplet(science, case.as_dict())


@pytest.mark.parametrize("field", pilot.PLAN_IDENTITY_FIELDS)
def test_minimum_endpoint_control_identity_tamper_is_rejected(field) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    science["minimum_endpoint_M2_control_identity"][field] = (
        999.0 if field in {"reserve_amount", "exact_training_objective"} else "e" * 64
    )
    # The projection must bind the saved control record, not merely compare the plan to itself.
    with pytest.raises(ValueError, match="control identity"):
        pilot._derive_triplet(science, case.as_dict())


def test_validation_selection_is_independently_recomputed_and_test_is_not_used() -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    assert pilot._derive_triplet(science, case.as_dict())["selected_candidate_id"] == "minimum_endpoint"
    science["validation_selection"]["selected_candidate_id"] = "maximum_endpoint"
    with pytest.raises(ValueError, match="independently reproduced"):
        pilot._derive_triplet(science, case.as_dict())


def test_projection_independently_closes_three_triplets_and_never_authorizes_formal(
    monkeypatch, tmp_path,
) -> None:
    config, design = _configs(); fingerprints = _fingerprints()
    cases = pilot.build_pilot_cases(config, design)
    results = {
        case.case_id: {
            "run_id": f"pilot_{case.case_id}", "case_id": case.case_id,
            "case": case.as_dict(), "status": "optimal", "wall_seconds": 30.0,
            "science": _science(case),
        }
        for case in cases
    }
    rows = [
        {
            "run_id": result["run_id"], "case_id": case_id, "status": "optimal",
            "parent_run_id": "", **fingerprints,
        }
        for case_id, result in results.items()
    ]
    monkeypatch.setattr(pilot, "_read_registry", lambda path: rows)
    monkeypatch.setattr(pilot, "_validate_artifact", lambda output, row: results[row["case_id"]])
    monkeypatch.setattr(pilot, "_validate_plan_artifact", lambda **kwargs: {})
    projection = pilot.update_projection(
        output_root=tmp_path, pilot=config, design=design, fingerprints=fingerprints,
    )
    assert projection["status"] == "complete"
    assert projection["verified_primary_run_count"] == 3
    assert projection["validation_candidate_plan_count"] == 9
    assert projection["validation_exact_recourse_evaluation_count"] == 18000
    assert projection["test_probe_plan_count"] == 6
    assert projection["test_probe_exact_recourse_evaluation_count"] == 12000
    assert projection["pilot_compute_gate_passed"] is True
    assert projection["formal_extension_authorized"] is False


def test_selected_minimum_reuses_control_and_has_zero_probe_difference() -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    science = _science(case)
    control = science["test_results"]["M2_minimum_endpoint"]
    treatment = science["test_results"]["M2_1_validation_selected_endpoint"]
    assert control["regular_purchase_sha256"] == treatment["regular_purchase_sha256"]
    treatment["metrics"]["total_cost_cvar95"] += 1.0
    with pytest.raises(Exception, match="differs"):
        pilot._derive_triplet(science, case.as_dict())


def test_selected_minimum_still_executes_six_independent_test_evaluations(monkeypatch) -> None:
    shared_minimum = {
        "reserve_amount": 10.0,
        "regular_purchase_sha256": "a" * 64,
        "exact_training_objective": 100.0,
    }
    strategy_plan = {
        "M2_minimum_endpoint": shared_minimum,
        "M2_1_validation_selected_endpoint": shared_minimum,
        "zero_autonomous_reserve": {
            "reserve_amount": 0.0, "regular_purchase_sha256": "b" * 64,
            "exact_training_objective": 101.0,
        },
        "fixed_autonomous_reserve_0_10": {
            "reserve_amount": 20.0, "regular_purchase_sha256": "c" * 64,
            "exact_training_objective": 102.0,
        },
        "fixed_autonomous_reserve_0_30": {
            "reserve_amount": 30.0, "regular_purchase_sha256": "d" * 64,
            "exact_training_objective": 103.0,
        },
        "fixed_autonomous_reserve_0_50": {
            "reserve_amount": 40.0, "regular_purchase_sha256": "e" * 64,
            "exact_training_objective": 104.0,
        },
    }
    calls: list[str] = []

    def evaluate(**kwargs):
        calls.append(kwargs["stage"])
        return {
            "plan_oos_status": "complete_feasible", "optimal_scenario_count": 2000,
            "infeasible_scenario_count": 0, "solver_failure_count": 0,
            "mean_total_cost": 1.0, "total_cost_cvar95": 2.0, "service_level": 1.0,
        }

    monkeypatch.setattr(pilot, "_evaluate_plan", evaluate)
    results = pilot._evaluate_test_strategies(
        generated=object(), strategy_plan=strategy_plan, seconds=120.0,
        wall_seconds=7200.0, progress=lambda *args: None,
        test_identity=_scenario_identity("f"), selected_id="minimum_endpoint",
    )
    assert len(calls) == 6
    assert calls == [f"test_{strategy}" for strategy in pilot.TEST_STRATEGIES]
    assert len(results) == 6
    assert 6 * 2000 == 12000
    assert (
        results["M2_minimum_endpoint"]["regular_purchase_sha256"]
        == results["M2_1_validation_selected_endpoint"]["regular_purchase_sha256"]
    )


def test_training_deadline_caps_each_solver_call_and_stops_expired_stage(monkeypatch) -> None:
    times = iter([0.0, 10.0, 119.0, 121.0])
    monkeypatch.setattr(pilot, "perf_counter", lambda: next(times))
    deadline = pilot._TrainingDeadline(wall_seconds=120.0, solver_call_seconds=60.0)
    assert deadline.solver_seconds("first") == 60.0
    assert deadline.solver_seconds("second") == 1.0
    with pytest.raises(TimeoutError, match="before third"):
        deadline.check("third")


@pytest.mark.parametrize(
    "solver_status,message",
    [
        ("time_limit", "direct time limit"),
        ("master_time_limit", "direct master time limit"),
        ("time_limit", "minimum endpoint failed: oracle_failure"),
        ("master_time_limit", "minimum endpoint failed: oracle_failure"),
    ],
)
def test_native_solver_timeout_is_immutable_timeout(
    monkeypatch, tmp_path, solver_status, message,
) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    runner_config = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    monkeypatch.setattr(pilot, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(pilot, "update_projection", lambda **kwargs: {
        "pilot_compute_gate_passed": False,
    })

    def fail(**kwargs):
        kwargs["progress"]("minimum_tolerance_optimal_reserve", {})
        raise pilot.DevelopmentStageError(
            "minimum_tolerance_optimal_reserve", solver_status, message,
        )

    output = tmp_path / "out"
    result = pilot.run_case(
        root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
        pilot=config, design=design, runner=runner_config,
        fingerprints=_fingerprints(), locked_environment={},
        source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=case, run_id=f"timeout_{solver_status}_{len(message)}", science_executor=fail,
    )
    assert result["status"] == "timeout"
    assert result["failure"]["solver_status"] == solver_status
    run_dir = output / "pilot/runs" / f"timeout_{solver_status}_{len(message)}"
    assert json.loads((run_dir / "status_summary.json").read_text(encoding="utf-8"))["status"] == "timeout"
    registry = pilot._read_registry(output / "pilot/pilot_run_registry.csv")
    assert registry[0]["status"] == "timeout"


def test_timeout_stops_remaining_triplets_and_cli_is_nonzero(monkeypatch, tmp_path, capsys) -> None:
    config, design = _configs(); calls: list[str] = []
    monkeypatch.setattr(pilot, "validate_preflight", lambda **kwargs: {
        "pilot": config, "design": design,
        "runner": yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        "fingerprints": _fingerprints(), "locked_environment": {}, "source": {},
    })

    def timed_out_case(**kwargs):
        calls.append(kwargs["case"].case_id)
        return {"status": "timeout", "projection": {"pilot_compute_gate_passed": False}}

    monkeypatch.setattr(pilot, "run_case", timed_out_case)
    results = pilot.run_pilot(
        root=tmp_path, pilot_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
        authorize=True, run_id_prefix="timeout_batch",
    )
    assert len(calls) == 1
    assert len(results) == 1 and results[0]["status"] == "timeout"

    monkeypatch.setattr(cli, "run_pilot", lambda **kwargs: results)
    assert cli.main(["--run-id-prefix", "timeout_batch"]) != 0
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"


def test_primary_subset_and_unbound_diagnostic_are_forbidden(monkeypatch) -> None:
    config, design = _configs()
    monkeypatch.setattr(pilot, "validate_preflight", lambda **kwargs: {
        "pilot": config, "design": design,
        "runner": yaml.safe_load(RUNNER.read_text(encoding="utf-8")),
        "fingerprints": _fingerprints(), "locked_environment": {}, "source": {},
    })
    case_id = pilot.build_pilot_cases(config, design)[0].case_id
    with pytest.raises(ValueError, match="complete frozen"):
        pilot.run_pilot(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", case_ids=[case_id],
        )
    with pytest.raises(ValueError, match="one case_id"):
        pilot.run_pilot(
            root=ROOT, pilot_path=CONFIG, runner_path=RUNNER, approval_path=APPROVAL,
            authorize=True, run_id_prefix="safe", parent_run_id="parent",
        )


@pytest.mark.parametrize("run_id", ["../escape", "a/b", "a\\b", "C:\\absolute"])
def test_run_id_cannot_escape_namespace(run_id, tmp_path) -> None:
    with pytest.raises(ValueError):
        pilot._run_directory(tmp_path, run_id)


def test_failure_is_finalized_and_stops_batch(monkeypatch, tmp_path) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    runner_config = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    monkeypatch.setattr(pilot, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(pilot, "_write_registry", lambda *args, **kwargs: None)
    monkeypatch.setattr(pilot, "update_projection", lambda **kwargs: {"pilot_compute_gate_passed": False})

    def fail(**kwargs):
        kwargs["progress"]("validation_minimum_endpoint", {})
        raise RuntimeError("synthetic failure")

    output = tmp_path / "out"
    result = pilot.run_case(
        root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
        pilot=config, design=design, runner=runner_config,
        fingerprints=_fingerprints(), locked_environment={},
        source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
        case=case, run_id="immutable_failure", science_executor=fail,
    )
    assert result["status"] == "stage_failure"
    path = output / "pilot/runs/immutable_failure/status_summary.json"
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "stage_failure"
    with pytest.raises(ValueError, match="immutable"):
        pilot.run_case(
            root=tmp_path, output_root=output, matrix_path=tmp_path / "matrix.yaml",
            pilot=config, design=design, runner=runner_config,
            fingerprints=_fingerprints(), locked_environment={},
            source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id="immutable_failure", science_executor=fail,
        )


def test_registry_writes_are_lock_serialized(tmp_path) -> None:
    output = tmp_path / "out"
    rows = [
        {"run_id": f"run_{index}", "case_id": f"case_{index}", "status": "optimal"}
        for index in range(2)
    ]
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda row: pilot._write_registry(output, row), rows))
    observed = pilot._read_registry(output / "pilot/pilot_run_registry.csv")
    assert {row["run_id"] for row in observed} == {"run_0", "run_1"}


def test_registry_finalization_failure_writes_bounded_terminal_diagnostic(
    monkeypatch, tmp_path,
) -> None:
    config, design = _configs(); case = pilot.build_pilot_cases(config, design)[0]
    runner_config = yaml.safe_load(RUNNER.read_text(encoding="utf-8"))
    monkeypatch.setattr(pilot, "load_phase6_matrix", lambda path: {})
    monkeypatch.setattr(pilot, "capture_runtime_context", lambda **kwargs: {})
    monkeypatch.setattr(pilot, "_write_registry", lambda *args, **kwargs: (_ for _ in ()).throw(PermissionError("locked registry")))
    with pytest.raises(PermissionError, match="locked registry"):
        pilot.run_case(
            root=tmp_path, output_root=tmp_path / "out", matrix_path=tmp_path / "matrix.yaml",
            pilot=config, design=design, runner=runner_config,
            fingerprints=_fingerprints(), locked_environment={},
            source={"commit_sha": "a" * 40, "tree_sha": "b" * 40},
            case=case, run_id="finalization_failure", science_executor=lambda **kwargs: {},
        )
    diagnostic = tmp_path / "out/pilot/runs/finalization_failure/runner_exception.json"
    payload = json.loads(diagnostic.read_text(encoding="utf-8"))
    assert payload["status"] == "runner_exception"
    assert payload["stage"] == "registry_finalization"
    assert len(diagnostic.read_bytes()) < MAX_BYTES


def test_cli_requires_projection_gate_even_with_three_optimal_runs(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "run_pilot", lambda **kwargs: [
        {"status": "optimal", "projection": {"pilot_compute_gate_passed": False}}
        for _ in range(3)
    ])
    code = cli.main(["--run-id-prefix", "pilot"])
    assert code == 2
    assert json.loads(capsys.readouterr().out)["status"] == "incomplete"


def test_bounded_status_reader_never_uses_result_or_checkpoint(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("src.phase6_m2_1_pilot_status.OUTPUT_ROOT", "outputs/test")
    run = tmp_path / "outputs/test/pilot/runs/r1"; run.mkdir(parents=True)
    (run / "status_summary.json").write_text(json.dumps({"status": "running"}), encoding="utf-8")
    (run / "result.json").write_text("x" * (MAX_BYTES * 10), encoding="utf-8")
    assert read_status(tmp_path, "r1") == {"status": "running"}


def test_revision_records_zero_science_execution() -> None:
    config = pilot.load_pilot_config(CONFIG)
    approval = yaml.safe_load(APPROVAL.read_text(encoding="utf-8"))
    assert config["execution_boundaries"] == {
        "runner_implemented": True, "pilot_authorized": True,
        "formal_training_authorized": False, "formal_validation_authorized": False,
        "selected_plan_freeze_authorized": False, "formal_test_authorized": False,
        "formal_extension_authorized": False, "scenario_generation_count": 0,
        "gurobi_call_count": 0, "pilot_run_count": 0, "formal_run_count": 0,
        "algorithm_performance_runs": 0, "M0_E3_runs": 0,
    }
    assert all(value == 0 for value in approval["execution_counts_in_this_revision"].values())
    assert approval["status"] == "approved_for_pilot_execution"
    assert approval["pilot_authorized"] is True
    assert all(approval[field] is False for field in (
        "formal_training_authorized", "formal_validation_authorized",
        "selected_plan_freeze_authorized", "formal_test_authorized",
        "formal_extension_authorized", "accept_M2_authorization",
    ))
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    assert all(value == 0 for value in audit["execution_counts"].values())
    assert audit["frozen_pilot"]["primary_run_count"] == 3
    assert audit["frozen_pilot"]["validation_candidate_plan_count"] == 9
    assert audit["frozen_pilot"]["validation_exact_recourse_evaluation_count"] == 18000
    assert audit["frozen_pilot"]["test_probe_plan_count"] == 6
    assert audit["frozen_pilot"]["test_probe_exact_recourse_evaluation_count"] == 12000
    assert audit["frozen_pilot"]["test_probe_strategies_evaluated_independently"] is True
    assert audit["safety"]["native_solver_timeouts_are_immutable_timeout"] is True
    assert audit["safety"]["training_hard_deadline_seconds"] == 1800
    assert audit["safety"]["solver_limit_capped_by_remaining_training_seconds"] is True
    assert audit["safety"]["formal_extension_authorized"] is False
    assert audit["CI"] == "recorded_in_pr_body"
